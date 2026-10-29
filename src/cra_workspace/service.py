"""Session-owned project operations shared by the graphical interfaces.

All counts/results come from files or the engine. Research approvals are explicit
snapshot-bound user actions; no function constructs approvals on behalf of an agent.
"""
from contextlib import contextmanager, closing
import copy
import csv
import io
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import uuid

from cra_engine import __version__
from cra_engine.common import EngineError, atomic, digest, load, now, require, save, sha, within
from cra_engine.store import Store, initialize
from cra_engine.schema import validate_brief, validate_protocol
from cra_engine.runtime import sync, plan, run, status, readiness
from cra_engine.statistics import effective_book
from cra_engine.literature import build_corpus, locate, import_bibliography
from cra_engine.research import validate_narrative

from .intake import MAX_UPLOAD, read_upload, csv_text, analysis_copy
from .security import Credentials, Reviews

ID = re.compile(r"^[a-f0-9]{32}$")


class Workspace:
    def __init__(self, root, owner=None, deployment="local"):
        require(deployment in ("local", "cloud"), "工作区运行方式无效")
        owner = owner or secrets.token_hex(16)
        require(isinstance(owner, str) and ID.fullmatch(owner), "工作区会话标识无效")
        self.directory = Path(root).resolve() / owner
        require(not self.directory.is_symlink(), "工作区拒绝符号链接")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.deployment = deployment
        self.credentials, self.reviews = Credentials(), Reviews()
        self._threads, self._lock = {}, threading.RLock()

    def _path(self, project):
        require(isinstance(project, str) and ID.fullmatch(project), "项目标识无效")
        path = within(self.directory, project)
        require((path / "project.json").is_file(), "当前会话没有这个项目")
        return path

    @contextmanager
    def _store(self, project):
        store = Store(self._path(project))
        # An unset graphical-session key must NEVER fall back to another user's
        # server environment key. The callback is never persisted or sent to workers.
        store.credential_provider = lambda: self.credentials.get(project, digest((store.get("brief") or load(store.root / "brief.json"))["model"]))
        if self.deployment == "cloud":
            from .network import public_fetch_json
            store.model_transport = public_fetch_json
        try:
            yield store
        finally:
            store.close()

    def _busy(self, project):
        worker = self._threads.get(project)
        return worker is not None and worker.is_alive()

    def _editable(self, project):
        require(not self._busy(project), "请先安全暂停运行，再修改输入或方案")
        import os
        with closing(sqlite3.connect(str(self._path(project) / ".cra/state.sqlite"))) as db:
            for (pid,) in db.execute("SELECT pid FROM leases"):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    pass
                raise EngineError("项目已有运行租约，请先安全暂停；不会并发改写输入")

    def _ready_files(self, root, brief):
        return all(within(root, brief["data"][k]).is_file() for k in ("csv", "codebook"))

    def create(self, name, question, objective=None, synthetic=False):
        require(isinstance(name, str) and 0 < len(name.strip()) <= 80, "请输入1–80字研究名称")
        require(isinstance(question, str) and question.strip(), "请填写实际研究问题或方向")
        project = uuid.uuid4().hex
        root = self.directory / project
        initialize(root, name.strip(), synthetic=synthetic)
        brief = load(root / "brief.json")
        brief.update(theme=question.strip(), objective=(objective or question).strip())
        validate_brief(brief)
        save(root / "brief.json", brief)
        save(root / ".cra/materials.json", {"data": [], "literature": []})
        return {"project_id": project, "name": name.strip()}

    def projects(self):
        result = []
        for root in sorted(self.directory.iterdir()):
            if root.is_dir() and ID.fullmatch(root.name) and (root / "project.json").is_file():
                brief = load(root / "brief.json")
                result.append({"project_id": root.name, "name": brief["name"], "question": brief["theme"],
                               "synthetic": load(root / "project.json")["synthetic"], "running": self._busy(root.name)})
        return result

    def snapshot(self, project):
        with self._lock, self._store(project) as store:
            brief = load(store.root / "brief.json")
            ready = self._ready_files(store.root, brief)
            if ready and not self._busy(project):
                sync(store)
            elif not ready:
                with store.tx(): store.put("brief", "research_brief", validate_brief(brief))
            output = status(store)
            rows = list(store.db.execute("SELECT id,kind,hash,version,stale FROM objects ORDER BY rowid"))
            objects = {r["id"]: {"kind": r["kind"], "hash": r["hash"], "version": r["version"],
                                  "stale": bool(r["stale"]), "value": store.get(r["id"])}
                       for r in rows if r["kind"] not in ("run_record", "specification_attempt")}
            specs = [json.loads(r[0]) for r in store.db.execute("SELECT body FROM objects WHERE kind='specification_attempt'")]
            calls = [{k: r[k] for k in ("id", "task", "status", "reserved", "actual", "model", "at")}
                     for r in store.db.execute("SELECT * FROM calls ORDER BY at")]
            events = [dict(r) for r in store.db.execute("SELECT seq,at,action FROM events ORDER BY seq DESC LIMIT 30")]
            return {"project_id": project, "engine_version": __version__, "deployment": self.deployment,
                    "synthetic": store.meta("synthetic", False), "brief": brief, "status": output,
                    "running": self._busy(project), "job": store.meta("workspace_job"), "environment": store.meta("workspace_environment"), "materials": load(store.root / ".cra/materials.json"),
                    "codebook": load(within(store.root, brief["data"]["codebook"])) if ready else None,
                    "files_ready": ready, "objects": objects, "specifications": specs, "calls": calls,
                    "events": events, "has_session_key": self.credentials.get(project, digest(brief["model"])) is not None,
                    "measurement_reviewed": ready and store.meta("measurement_review") == self._measurement_hash(store.root, brief),
                    "draft_source": load(store.root / "manuscript/narrative.json") if (store.root / "manuscript/narrative.json").is_file() else None,
                    "protocol_source": load(store.root / "protocol/plan.json") if (store.root / "protocol/plan.json").is_file() else None,
                    "exports": [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha(p)} for p in (store.root / "exports").glob("*.zip")]}

    @staticmethod
    def _measurement_hash(root, brief):
        return digest({k: sha(within(root, brief["data"][k])) for k in ("csv", "codebook")})

    def _consent(self, consent):
        require(self.deployment != "cloud" or consent is True, "云端接入前需明确同意将所选材料上传并在此服务处理")

    def import_data(self, project, filename, content, cloud_consent=False):
        self._consent(cloud_consent)
        require(isinstance(filename, str) and Path(filename).suffix.lower() in (".csv", ".dta"), "请选择CSV或DTA")
        require(isinstance(content, bytes) and 0 < len(content) <= MAX_UPLOAD, "数据大小超出当前接入范围")
        with self._lock, self._store(project) as store:
            self._editable(project)
            version = uuid.uuid4().hex
            raw = store.root / ".cra/uploads" / (version + Path(filename).suffix.lower())
            raw.parent.mkdir(exist_ok=True)
            raw.write_bytes(content)
            try:
                parsed = read_upload(raw)
            except BaseException:
                # Preserve an explicit failed-upload record, never silently adopt it.
                with store.tx(): store.event("upload_rejected", {"format": raw.suffix, "sha256": sha(raw)})
                raise
            folder = store.root / "data/versions" / version
            folder.mkdir(parents=True)
            text = csv_text(parsed["names"], parsed["rows"])
            atomic(folder / "source.csv", text)
            atomic(folder / "input.csv", text)
            save(folder / "codebook.json", parsed["book"])
            brief = load(store.root / "brief.json")
            brief["data"].update(csv=(folder / "input.csv").relative_to(store.root).as_posix(), codebook=(folder / "codebook.json").relative_to(store.root).as_posix())
            save(store.root / "brief.json", brief)
            catalog = load(store.root / ".cra/materials.json")
            record = dict(parsed["summary"], id=version, name=filename, original_path=raw.relative_to(store.root).as_posix(),
                          sha256=sha(raw), source_csv=(folder / "source.csv").relative_to(store.root).as_posix(),
                          cloud_processing_consented=cloud_consent is True, imported_at=now())
            catalog["data"].append(record)
            save(store.root / ".cra/materials.json", catalog)
            sync(store)
            with store.tx(): store.event("data_imported", {"id": version, "records": record["records"], "fields": record["fields"]})
            return record

    def measurement(self, project, book, missing_codes, reviewer, note):
        require(isinstance(reviewer, str) and len(reviewer.strip()) >= 2 and isinstance(note, str) and len(note.strip()) >= 8, "请填写实际核查人和题项/编码核查依据")
        with self._lock, self._store(project) as store:
            self._editable(project)
            catalog = load(store.root / ".cra/materials.json")
            require(catalog["data"], "请先接入数据")
            source = within(store.root, catalog["data"][-1]["source_csv"])
            text, flow = analysis_copy(source, book, missing_codes)
            version = uuid.uuid4().hex
            folder = store.root / "data/versions" / version
            folder.mkdir(parents=True)
            atomic(folder / "input.csv", text)
            save(folder / "codebook.json", book)
            brief = load(store.root / "brief.json")
            brief["data"].update(csv=(folder / "input.csv").relative_to(store.root).as_posix(), codebook=(folder / "codebook.json").relative_to(store.root).as_posix())
            save(store.root / "brief.json", brief)
            sync(store)
            with store.tx():
                store.set_meta("measurement_review", self._measurement_hash(store.root, brief))
                store.put("measurement_declaration", "human_declaration", {"reviewer": reviewer, "note": note, "flow": flow, "at": now(), "identity_certified": False})
                store.event("measurement_reviewed", {"version": version})
            return flow

    def save_brief(self, project, changes):
        require(isinstance(changes, dict) and set(changes) <= {"name", "theme", "objective", "language", "profile", "permissions", "model", "limits"}, "设置字段不在允许范围内")
        with self._lock, self._store(project) as store:
            self._editable(project)
            brief = load(store.root / "brief.json")
            brief.update(copy.deepcopy(changes))
            validate_brief(brief)
            if brief["permissions"]["model"] and self.deployment == "cloud":
                self._public_model(brief["model"]["base_url"])
            save(store.root / "brief.json", brief)
            if self._ready_files(store.root, brief): sync(store)
            return {"saved": True, "authorization_requires_current_snapshot": True}

    @staticmethod
    def _public_model(base):
        from urllib.parse import urlsplit
        from .network import addresses
        url = urlsplit(base)
        require(url.scheme == "https" and url.port in (None, 443) and not url.fragment, "云端模型端点须为公网HTTPS服务")
        addresses(url.hostname)

    def set_key(self, project, key):
        with self._store(project) as store:
            brief = load(store.root / "brief.json")
            require(brief["permissions"]["model"], "请先保存模型范围，密钥不等于项目授权")
            self.credentials.put(project, digest(brief["model"]), key, brief["limits"]["max_seconds"])
        return {"session_key_present": True, "persisted": False}

    def clear_key(self, project):
        self.credentials.clear(project)
        return self.pause(project)

    def upload_literature(self, project, filename, content, cloud_consent=False):
        self._consent(cloud_consent)
        suffix = Path(filename).suffix.lower()
        require(suffix in (".pdf", ".md", ".txt", ".bib", ".ris") and isinstance(content, bytes) and 0 < len(content) <= 20_000_000, "请选择20MB以内的PDF/TXT/MD/BibTeX/RIS")
        with self._lock, self._store(project) as store:
            self._editable(project)
            ident = "source_" + uuid.uuid4().hex
            path = store.root / "literature" / (ident + suffix)
            path.write_bytes(content)
            if suffix in (".bib", ".ris"):
                import_bibliography(store.root, path)
            catalog = load(store.root / ".cra/materials.json")
            record = {"id": ident, "name": filename, "path": path.relative_to(store.root).as_posix(),
                      "sha256": sha(path), "bytes": len(content), "cloud_processing_consented": cloud_consent is True}
            catalog["literature"].append(record)
            save(store.root / ".cra/materials.json", catalog)
            return record

    def literature_text(self, project, source, position=1):
        root = self._path(project)
        materials = load(root / ".cra/materials.json")["literature"]
        record = next((r for r in materials if r["id"] == source), None)
        require(record is not None and type(position) is int and position >= 1, "当前项目没有该材料或定位无效")
        path = within(root, record["path"])
        if path.suffix == ".pdf":
            from pypdf import PdfReader
            pages = PdfReader(path).pages
            require(position <= len(pages), "页码超出材料范围")
            return {"text": pages[position-1].extract_text() or "", "position": position, "total": len(pages), "kind": "page"}
        require(path.suffix in (".txt", ".md"), "题录文件不是授权全文")
        paragraphs = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
        require(position <= len(paragraphs), "段落超出材料范围")
        return {"text": paragraphs[position-1], "position": position, "total": len(paragraphs), "kind": "paragraph"}

    def save_reference(self, project, reference):
        with self._lock, self._store(project) as store:
            self._editable(project)
            require(isinstance(reference, dict), "文献记录格式无效")
            records_path = store.root / "literature/references.json"
            previous = load(records_path) if records_path.exists() else []
            records = [r for r in previous if r.get("id") != reference.get("id")] + [reference]
            # Validate local identifiers and evidence before adopting this record.
            from cra_engine.common import identifier
            require(identifier(reference.get("id")), "文献ID须为字母、数字和下划线组成的标识")
            span_ids = [s.get("id") for r in records for s in r.get("spans", [])]
            require(all(identifier(x) for x in span_ids) and len(span_ids) == len(set(span_ids)), "证据片段ID须有效且全项目唯一")
            for span in reference.get("spans", []): locate(store.root, span)
            if reference.get("doi"):
                require(re.fullmatch(r"10\.\d{4,9}/\S+", reference["doi"]), "DOI基础格式无效")
            for field in ("id", "title", "year", "source", "url"):
                require(isinstance(reference.get(field), str) and reference[field], "请补齐题录必需字段")
            require(isinstance(reference.get("authors"), list) and reference["authors"], "请填写实际作者")
            save(records_path, records)
            return {"saved": True, "reference_id": reference["id"], "semantic_support_is_human_declaration": True}

    def references(self, project):
        path = self._path(project) / "literature/references.json"
        return load(path) if path.is_file() else []

    def backup(self, project, confirmed=False):
        """Explicit private recovery file, not a publication/export package."""
        require(confirmed is True, "恢复备份包含原始材料与项目状态，请确认仅保存到受控位置")
        import zipfile
        with self._lock, self._store(project) as store:
            self._editable(project)
            stream = io.BytesIO()
            # SQLite's backup API includes committed WAL records consistently.
            database = store.root / ".cra/backup.sqlite"
            with closing(sqlite3.connect(database)) as target: store.db.backup(target)
            try:
                with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("cra-recovery.json", json.dumps({"format": 1, "at": now(), "schema_version": 2}))
                    for path in store.root.rglob("*"):
                        if not path.is_file() or path.is_symlink(): continue
                        rel = path.relative_to(store.root).as_posix()
                        if rel.startswith(("exports/", ".cra/runs/")) or rel in (".cra/state.sqlite", ".cra/state.sqlite-wal", ".cra/state.sqlite-shm", ".cra/backup.sqlite"): continue
                        archive.write(path, rel)
                    archive.write(database, ".cra/state.sqlite")
            finally:
                database.unlink(missing_ok=True)
            with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as archive:
                require(sum(i.file_size for i in archive.infolist()) <= 128_000_000 and len(stream.getvalue()) <= 64_000_000, "项目历史材料超过当前恢复容量；没有生成无法导入的备份。请先导出成果与授权输入并保留原运行目录。")
            return {"filename": "cra-private-recovery-" + project[:8] + ".zip", "bytes": stream.getvalue()}

    def restore(self, content, cloud_consent=False):
        self._consent(cloud_consent)
        import shutil, zipfile
        require(isinstance(content, bytes) and 0 < len(content) <= 64_000_000, "恢复备份须为64MB以内的ZIP")
        project = uuid.uuid4().hex
        root = self.directory / project
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                require(len(entries) <= 5000 and sum(i.file_size for i in entries) <= 128_000_000, "恢复备份解压容量超限")
                require(len({i.filename for i in entries}) == len(entries), "恢复备份存在重复路径")
                for info in entries:
                    require(not info.is_dir() and not (info.external_attr >> 16) & 0o170000 == 0o120000, "恢复备份不接受目录或符号链接条目")
                    require(not info.filename.startswith(("/", "\\")) and "\\" not in info.filename and ".." not in Path(info.filename).parts, "恢复备份含非法路径")
                marker = json.loads(archive.read("cra-recovery.json"))
                require(marker.get("format") == 1 and marker.get("schema_version") == 2, "恢复格式不支持；未修改既有项目")
                root.mkdir(mode=0o700)
                for info in entries:
                    if info.filename == "cra-recovery.json": continue
                    path = within(root, info.filename)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.read(info))
            validate_brief(load(root / "brief.json"))
            # A recovery file is user input, not an executable SQLite extension.
            # Reject programmable schema objects before opening the engine store.
            with closing(sqlite3.connect(root / ".cra/state.sqlite")) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                schema = list(db.execute("SELECT type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
                require(all(t in ("table", "index") and "VIRTUAL TABLE" not in (sql or "").upper() for t, sql in schema), "恢复数据库含不支持的可执行结构")
            with self._store(project) as store:
                with store.tx():
                    store.db.execute("DELETE FROM leases")
                    store.db.execute("UPDATE tasks SET status='ready' WHERE status='running'")
                    store.db.execute("DELETE FROM approvals")
                    store.db.execute("UPDATE calls SET status='uncertain' WHERE status='reserved'")
                    store.set_meta("paused", True)
                    store.set_meta("workspace_job", {"state": "restored", "at": now()})
                    store.event("workspace_restored", {"approvals_require_review": True, "cloud_processing_consented": cloud_consent is True})
            return {"project_id": project, "restored": True, "new_approvals_required": True}
        except Exception as exc:
            shutil.rmtree(root, ignore_errors=True)
            if isinstance(exc, EngineError): raise
            raise EngineError("恢复备份不完整或状态无法验证；未改写既有项目") from exc

    def save_protocol(self, project, protocol):
        with self._lock, self._store(project) as store:
            self._editable(project); sync(store)
            book = effective_book(store.get("codebook", fresh=True))
            corpus = build_corpus(store.root, store.get("brief", fresh=True))
            validate_protocol(protocol, book, corpus)
            save(store.root / "protocol/plan.json", protocol)
            sync(store)
            return {"saved": True, "protocol_sha256": digest(protocol), "freeze_required": True}

    def save_narrative(self, project, narrative):
        with self._lock, self._store(project) as store:
            self._editable(project); sync(store)
            validate_narrative(narrative, store.get("corpus", fresh=True), store.get("claims", fresh=True))
            save(store.root / "manuscript/narrative.json", narrative)
            sync(store)
            return {"saved": True}

    def challenge(self, project, scope):
        with self._lock, self._store(project) as store:
            self._editable(project); sync(store)
            require(scope in ("authorization", "protocol", "final"), "确认范围无效")
            if scope == "protocol":
                require(store.approved("authorization"), "请先审阅项目授权")
                require(store.meta("measurement_review") == self._measurement_hash(store.root, store.get("brief")), "题项与编码尚未完成当前版本核查")
            if scope == "final":
                require(readiness(store)["ready_for_final"], "核心证据缺失、过期或存在阻断复核，不能终审")
            return self.reviews.issue(project, scope, store.snapshot(scope))

    def approve(self, project, scope, nonce, confirmation, reviewer, note, reviewed=False):
        require(reviewed is True, "请实际查看当前范围并确认，而非自动代签")
        require(isinstance(reviewer, str) and len(reviewer.strip()) >= 2 and isinstance(note, str) and len(note.strip()) >= 8, "请填写实际核查人与至少8字符的依据")
        with self._lock, self._store(project) as store:
            self._editable(project); sync(store)
            if scope == "protocol":
                require(store.approved("authorization") and store.meta("measurement_review") == self._measurement_hash(store.root, store.get("brief")), "计划核查前提已经变化")
            if scope == "final": require(readiness(store)["ready_for_final"], "当前成果仍有缺口或阻断")
            require(confirmation == "APPROVE " + store.snapshot(scope)[:12], "请输入当前版本的准确确认短语")
            self.reviews.consume(nonce, project, scope, store.snapshot(scope))
            store.approve(scope, reviewer, note, confirmation)
            if scope == "final": self.credentials.clear(project)
            return {"recorded": True, "scope": scope, "identity_certified": False}

    def start(self, project, model_test=False):
        with self._lock, self._store(project) as store:
            self._editable(project); sync(store)
            require(store.approved("authorization"), "请先批准当前项目授权")
            if store.get("brief")["permissions"]["model"]:
                require(self.credentials.get(project, digest(store.get("brief")["model"])), "本次运行需要重新填写当前会话密钥")
            with store.tx():
                store.set_meta("paused", False)
                store.set_meta("workspace_job", {"state": "starting", "at": now(), "kind": "model_contract" if model_test else "research"})
            thread = threading.Thread(target=self._run, args=(project, model_test), daemon=True, name="cra-" + project[:8])
            self._threads[project] = thread
            thread.start()
        return {"started": True, "project_id": project}

    def _run(self, project, model_test):
        try:
            with self._store(project) as store:
                if model_test:
                    from cra_engine.models import ModelAdapter
                    with store.lease(): ModelAdapter(store).contract_test()
                else:
                    run(store)
                with store.tx(): store.set_meta("workspace_job", {"state": "stopped", "at": now()})
        except Exception as exc:
            with self._store(project) as store:
                with store.tx():
                    store.set_meta("workspace_job", {"state": "failed", "at": now(), "message": str(exc) if isinstance(exc, EngineError) else "执行失败，请检查材料或运行环境；原始内容不回显"})

    def pause(self, project):
        with self._store(project) as store:
            with store.tx():
                store.set_meta("paused", True)
                store.event("workspace_pause_requested", {})
        return {"pause_requested": True, "still_running": self._busy(project)}

    def reconcile(self, project, call, amount, note, confirmed=False):
        require(confirmed is True and isinstance(note, str) and len(note.strip()) >= 8, "请根据实际账单核对并说明依据")
        with self._lock, self._store(project) as store:
            self._editable(project)
            row = store.db.execute("SELECT status FROM calls WHERE id=?", (call,)).fetchone()
            require(row and row["status"] == "uncertain", "当前请求不处于待核对状态")
            store.settle(call, amount, {"human_reconciled": True, "note": note})
            return store.budget()

    def export(self, project, kind="working", include_data=False, sharing_confirmed=False):
        require(kind in ("working", "final", "diagnostic"), "请选择工作稿、终审成果或诊断")
        require(not include_data or sharing_confirmed is True, "包含数据需要另行确认共享授权")
        with self._lock, self._store(project) as store:
            self._editable(project)
            from cra_engine.exporting import export_package, export_diagnostic
            result = export_diagnostic(store) if kind == "diagnostic" else export_package(store, working=kind == "working", include_data=include_data)
            path = Path(result["archive"])
            return {"filename": path.name, "bytes": path.read_bytes(), "sha256": sha(path), "kind": kind}

    def reproduce(self, project):
        with self._lock, self._store(project) as store:
            self._editable(project)
            from cra_engine.cli import reproduce
            return reproduce(store)

    def check_environment(self, project):
        """An actual non-billing isolation probe, not an availability guess."""
        with self._lock, self._store(project) as store:
            self._editable(project)
            from cra_engine.isolation import doctor
            from cra_engine.statistics import recipe_identity
            report = {"at": now(), "engine_version": __version__, "recipe": digest(recipe_identity())}
            from cra_engine.common import source_fingerprint
            report.update(engine_source_sha256=source_fingerprint(), workspace_source_sha256=sha(Path(__file__)))
            import platform
            report["platform"] = {"system": platform.system(), "kernel": platform.release(), "machine": platform.machine()}
            if platform.system() == "Linux":
                import ctypes, ctypes.util, errno
                report["platform"]["libseccomp_available"] = bool(ctypes.util.find_library("seccomp"))
                if platform.machine() in ("x86_64", "aarch64", "riscv64"):
                    libc = ctypes.CDLL(None, use_errno=True)
                    libc.syscall.restype = ctypes.c_long
                    abi = libc.syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
                    report["platform"]["landlock_abi"] = abi if abi >= 0 else None
                    if abi < 0: report["platform"]["landlock_error"] = errno.errorcode.get(ctypes.get_errno(), "UNKNOWN")
            try:
                result = doctor(store)
                report.update(passed=True, isolation=result["isolation"], controls=result["result"])
            except EngineError:
                report.update(passed=False, message="当前托管环境未通过真实隔离自检，已拒绝无人值守统计；可整理材料或导出备份至经验证的本机运行。")
            with store.tx():
                store.set_meta("workspace_environment", report)
                store.event("workspace_environment_checked", report)
            return report
