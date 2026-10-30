"""Local-only HTTP worker behind a TLS reverse proxy; fixed audited recipes.

The service never imports user code, receives model keys, or writes frontend
approvals. Each job executes in the engine's fail-closed OS isolation backend.
"""
import argparse
import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cra_engine.common import EngineError, digest, dumps, load, now, require, safe_text, save, sha
from cra_engine.isolation import IsolatedRecipeError, doctor, execute
from cra_engine.schema import validate_analysis_contract
from cra_engine.statistics import effective_book
from cra_engine.store import Store, initialize
from .protocol import JOB, MAX_BODY, MAX_RESULT, VERSION, identity, parse, request_hash, sign


class JobStore:
    """Minimal isolation supervisor; no research permissions/approvals exist here."""
    def __init__(self, root, cancellation):
        self.root, self.cancellation = root, cancellation
    def meta(self, key, default=None):
        return self.cancellation.is_set() if key == "paused" else default


class Worker:
    def __init__(self, root, token, retention_seconds=86400, max_jobs=128):
        require(isinstance(token, str) and len(token) >= 32, "Worker credential must have at least 32 characters")
        self.token = token
        self.root = Path(root).absolute()
        require(not any(p.is_symlink() for p in [self.root, *self.root.parents]), "Worker storage symlinks refused")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.lock, self.wake, self.stop = threading.RLock(), threading.Event(), threading.Event()
        self.cancellations, self.retention_seconds, self.max_jobs = {}, retention_seconds, max_jobs
        # A service restart never pretends a half-written response completed.
        for folder in self.root.iterdir():
            if not folder.is_dir() or not JOB.fullmatch(folder.name): continue
            path = folder / "state.json"
            if not path.exists():
                source = folder / "request.json"
                save(path, {"job": folder.name, "request_hash": request_hash(load(source)) if source.is_file() else "", "status": "unknown", "created_epoch": folder.stat().st_mtime, "updated": now(), "message": "Incomplete durable job; no automatic resubmission"})
        for path in self.root.glob("*/state.json"):
            state = load(path)
            if state["status"] in ("queued", "running"):
                state.update(status="unknown", updated=now(), message="Service restarted; no automatic resubmission")
                save(path, state)
        self.capability = None
        self.thread = threading.Thread(target=self._schedule, daemon=True, name="cra-worker-queue")

    def probe(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="cra-probe-", dir=self.root) as folder:
            root = Path(folder) / "control"
            initialize(root, "Worker isolation control", synthetic=True)
            store = Store(root)
            try:
                actual = doctor(store)
                body = {"protocol": VERSION, "identity": identity(), "passed": True,
                        "isolation": actual["isolation"], "controls": actual["result"], "at": now()}
            except (EngineError, OSError):
                body = {"protocol": VERSION, "identity": identity(), "passed": False, "at": now(),
                        "message": "Actual OS isolation probe failed; statistics refused"}
            finally: store.close()
        self.capability = body
        return body

    def start(self):
        self.probe()
        self.thread.start()

    def close(self):
        self.stop.set()
        for event in self.cancellations.values(): event.set()
        self.wake.set()
        if self.thread.is_alive(): self.thread.join(timeout=8)

    def _path(self, job):
        require(isinstance(job, str) and JOB.fullmatch(job), "Invalid job ID")
        return self.root / job

    def _cleanup(self):
        import shutil
        for folder in self.root.iterdir():
            state_path = folder / "state.json"
            if not JOB.fullmatch(folder.name) or not state_path.is_file(): continue
            state = load(state_path)
            if state["status"] not in ("queued", "running", "expired") and time.time() - state["created_epoch"] > self.retention_seconds:
                # Retain a tombstone, preventing an expired job ID being re-run.
                for path in folder.iterdir():
                    if path.name == "state.json": continue
                    if path.is_dir(): shutil.rmtree(path)
                    else: path.unlink()
                state.pop("result", None); state.pop("progress", None)
                state.update(status="expired", updated=now())
                save(state_path, state)

    def submit(self, job, request):
        folder = self._path(job)
        signature = request_hash(request)
        with self.lock:
            if (folder / "state.json").exists():
                state = load(folder / "state.json")
                require(state["request_hash"] == signature, "Job ID already bound to a different request")
                return state
            self._cleanup()
            require(self.capability and self.capability["passed"], "Worker has not passed real isolation probe")
            require(self.thread.is_alive() and not self.stop.is_set(), "Worker scheduler is not running")
            require(request.get("identity") == identity() and request.get("protocol") == VERSION, "Worker recipe/environment mismatch")
            require(set(request) == {"protocol", "identity", "action", "files", "parameters", "timeout"}, "Unexpected request fields")
            require(request["action"] in ("audit", "analysis"), "Only fixed audit/analysis recipes allowed")
            require(type(request["timeout"]) is int and 1 <= request["timeout"] <= 300, "Invalid worker deadline")
            require(set(request["files"]) == {"csv", "codebook"}, "Only an analysis copy and codebook may be sent")
            params = request["parameters"]
            allowed = {"min_cell", "recruited_n"} if request["action"] == "audit" else {"min_cell", "protocol"}
            require(set(params) <= allowed and type(params.get("min_cell")) is int and 2 <= params["min_cell"] <= 10000, "Invalid recipe parameters")
            if "recruited_n" in params:
                require(params["recruited_n"] is None or type(params["recruited_n"]) is int and params["recruited_n"] >= 0, "Invalid recruitment count")
            data = {}
            for key, item in request["files"].items():
                require(isinstance(item, dict) and set(item) == {"base64", "sha256"}, "Invalid file envelope")
                try: raw = base64.b64decode(item["base64"], validate=True)
                except (ValueError, TypeError) as exc: raise EngineError("Invalid file encoding") from exc
                require(0 < len(raw) <= (32_000_000 if key == "csv" else 1_000_000), "Worker input size exceeded")
                require(hashlib.sha256(raw).hexdigest() == item["sha256"], "Input digest mismatch")
                safe_text(raw.decode("utf-8-sig"))
                data[key] = raw
            book = parse(data["codebook"])
            columns = book.get("columns", {})
            require(columns and len(columns) <= 500 and all(isinstance(v, dict) and v.get("sensitive") is False for v in columns.values()), "Sensitive or unreviewed codebook refused")
            import csv, io
            reader = csv.reader(io.StringIO(data["csv"].decode("utf-8-sig")))
            header = next(reader, [])
            require(set(header) == set(columns) and len(header) == len(columns), "CSV/codebook columns mismatch")
            count = 0
            for row in reader:
                count += 1
                require(len(row) == len(header) and count <= 250000 and count * len(header) <= 5000000, "Worker row/cell limit exceeded")
            require(count > 0, "Empty analysis copy")
            if request["action"] == "analysis":
                require(len(dumps(params.get("protocol")).encode()) <= 128000, "Approved protocol size exceeded")
                require(len(params.get("protocol", {}).get("models", [])) <= 16, "At most sixteen approved models per job")
                require(len(params.get("protocol", {}).get("exclusions", [])) <= 100, "Exclusion rule limit exceeded")
                validate_analysis_contract(params.get("protocol"), effective_book(book))
            states = [load(p) for p in self.root.glob("*/state.json")]
            require(sum(s["status"] != "expired" for s in states) < self.max_jobs and len(states) < 100000, "Worker storage quota reached; operator maintenance required")
            require(sum(s["status"] in ("queued", "running") for s in states) < 4, "Worker queue full")
            folder.mkdir(mode=0o700)
            # The control sentinel exists and must be unreadable by the recipe.
            (folder / ".cra").mkdir(mode=0o700)
            (folder / ".cra/state.sqlite").write_bytes(b"CONTROL-STATE-DO-NOT-READ")
            (folder / "input.csv").write_bytes(data["csv"])
            (folder / "codebook.json").write_bytes(data["codebook"])
            save(folder / "request.json", request)
            state = {"job": job, "request_hash": signature, "status": "queued", "updated": now(), "created_epoch": time.time()}
            save(folder / "state.json", state)
            self.cancellations[job] = threading.Event()
            self.wake.set()
            return state

    def get(self, job):
        with self.lock:
            path = self._path(job) / "state.json"
            if not path.exists(): return {"job": job, "status": "not_found"}
            return load(path)

    def cancel(self, job):
        with self.lock:
            state = self.get(job)
            if state["status"] == "queued":
                state.update(status="cancelled", updated=now()); save(self._path(job) / "state.json", state)
            elif state["status"] == "running":
                self.cancellations[job].set()
            return {"job": job, "cancellation_requested": True, "status": state["status"]}

    def _schedule(self):
        last_cleanup = 0
        while not self.stop.is_set():
            self.wake.wait(1); self.wake.clear()
            if self.stop.is_set(): break
            with self.lock:
                if time.time() - last_cleanup > 60:
                    self._cleanup(); last_cleanup = time.time()
                pending = sorted((load(p) for p in self.root.glob("*/state.json")), key=lambda s: s["created_epoch"])
                state = next((s for s in pending if s["status"] == "queued"), None)
                if state:
                    state.update(status="running", updated=now())
                    save(self._path(state["job"]) / "state.json", state)
            if state:
                self._execute(state)
                self.wake.set()

    def _execute(self, state):
        folder = self._path(state["job"])
        request = load(folder / "request.json")
        store = JobStore(folder, self.cancellations[state["job"]])
        payload = dict(request["parameters"], csv_path=str(folder / "input.csv"), book_path=str(folder / "codebook.json"))
        try:
            actual = execute(store, request["action"], payload, [folder / "input.csv", folder / "codebook.json"], request["timeout"])
            result = actual["result"]
            require(len(dumps(result).encode()) <= MAX_RESULT, "Result size exceeded")
            safe_text(result)
            data_key = "input_sha256" if request["action"] == "audit" else "data_sha256"
            require(result[data_key] == request["files"]["csv"]["sha256"] and result["codebook_sha256"] == request["files"]["codebook"]["sha256"], "Worker result input mismatch")
            if request["action"] == "analysis":
                require(result["protocol_hash"] == digest(request["parameters"]["protocol"]), "Worker result protocol mismatch")
            state.update(status="succeeded", result=result, result_hash=digest(result), isolation=actual["isolation"], identity=identity())
        except Exception as exc:
            state.update(status="cancelled" if store.meta("paused") else "failed", message="Recipe failed, cancelled or timed out; raw data/errors withheld", error_type=type(exc).__name__)
            if isinstance(exc, IsolatedRecipeError) and exc.metadata.get("progress_path"):
                path = folder / exc.metadata["progress_path"]
                if path.is_file() and sha(path) == exc.metadata["progress_sha256"]:
                    progress = load(path)
                    try:
                        safe_text(progress)
                        if len(dumps(progress).encode()) <= MAX_RESULT: state["progress"] = progress
                    except EngineError: pass
        state["updated"] = now()
        with self.lock: save(folder / "state.json", state)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, worker):
        self.worker, self.slots = worker, threading.BoundedSemaphore(8)
        super().__init__(address, Handler)
    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try: super().process_request(request, client_address)
        except BaseException:
            self.slots.release(); raise
    def process_request_thread(self, request, client_address):
        try: super().process_request_thread(request, client_address)
        finally: self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "CRA-Worker"
    def setup(self):
        super().setup(); self.connection.settimeout(30)
    def log_message(self, *_): pass  # Never log request paths, credentials or bodies.
    def _reply(self, status, body):
        raw = dumps(sign(body, self.server.worker.token)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers(); self.wfile.write(raw)
    def _handle(self):
        try:
            supplied = self.headers.get("Authorization", "")
            if len(self.headers.get_all("Authorization", [])) != 1 or not hmac.compare_digest(supplied, "Bearer " + self.server.worker.token):
                self.send_error(401); return
            require(not self.headers.get("Transfer-Encoding") and len(self.headers.get_all("Content-Length", [])) <= 1, "Ambiguous body refused")
            worker = self.server.worker
            if self.command == "GET" and self.path == "/v1/health":
                if worker.capability is None or time.time() - getattr(worker, "last_probe", 0) > 300:
                    worker.probe(); worker.last_probe = time.time()
                capability = dict(worker.capability)
                if not worker.thread.is_alive():
                    capability.update(passed=False, message="Worker scheduler unavailable; statistics refused")
                self._reply(200, capability); return
            parts = self.path.split("/")
            require(len(parts) == 4 and parts[1:3] == ["v1", "jobs"] and JOB.fullmatch(parts[3]), "Unknown worker route")
            job = parts[3]
            if self.command == "GET": body = worker.get(job)
            elif self.command == "DELETE": body = worker.cancel(job)
            elif self.command == "POST":
                length = self.headers.get("Content-Length", "")
                require(length.isdigit() and 0 < int(length) <= MAX_BODY, "Worker request too large or missing length")
                require(self.headers.get("Content-Type", "").split(";")[0] == "application/json", "JSON body required")
                raw = self.rfile.read(int(length))
                require(len(raw) == int(length), "Incomplete request")
                body = worker.submit(job, parse(raw))
            else: raise EngineError("Unsupported operation")
            self._reply(200, body)
        except (EngineError, ValueError, KeyError, TypeError, UnicodeError):
            self._reply(400, {"error": "Request refused; inspect approved contract, worker quota and capability"})
        except (ConnectionError, TimeoutError, OSError): pass
    do_GET = do_POST = do_DELETE = _handle


def main():
    parser = argparse.ArgumentParser(description="Fixed-recipe worker. Public exposure requires an HTTPS reverse proxy.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--port", type=int, default=8781)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(args.token_file)
    # systemd 239 on the supported Alibaba Cloud Linux image has no
    # LoadCredential. Permit only a root-owned 0640 token readable by the
    # dedicated service group; reject other group members and all access for
    # other users. Open with O_NOFOLLOW and validate the opened file to avoid
    # a symlink/permission time-of-check race.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise EngineError("Worker credential could not be opened safely") from exc
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_gid == os.getegid()
                and stat.S_IMODE(info.st_mode) == 0o640,
                "Credential must be a root-owned regular file, mode 0640, readable by the service group only")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            token = stream.read().strip()
    finally:
        os.close(fd)
    worker = Worker(args.root, token)
    if args.check:
        result = worker.probe()
        print(dumps(result))
        if not result["passed"]: raise SystemExit(2)
        return
    worker.start()
    server = Server(("127.0.0.1", args.port), worker)
    try: server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt: pass
    finally: server.server_close(); worker.close()


if __name__ == "__main__": main()
