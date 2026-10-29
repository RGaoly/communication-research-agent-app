import importlib.util
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

from .common import EngineError, atomic, dumps, load, now, require, save
from .schema import default_brief
from .store import SCHEMA, Store


def legacy_module():
    candidates = [Path(__file__).resolve().parents[2] / "skills/communication-research-agent/scripts/cra.py",
                  Path(sys.prefix) / "share/communication-research-agent/legacy/cra.py"]
    path = next((p for p in candidates if p.is_file()), None)
    require(path is not None, "Legacy standalone CLI not found in installation")
    spec = importlib.util.spec_from_file_location("cra_legacy_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(root, dry_run=True):
    root = Path(root).resolve()
    old = load(root / "project.json")
    require(old.get("schema_version") == 1, "Migration accepts schema 1 only")
    require(not (root / ".cra").exists(), "Destination engine state already exists")
    legacy = legacy_module()
    checked = legacy.load_state(root)
    legacy.check_log(root, checked)
    report = {"from": 1, "to": 2, "dry_run": dry_run, "historical_reviews": len(old.get("reviews", {})),
              "new_approvals": 0, "raw_data_overwritten": False,
              "required_after_migration": ["complete brief.json", "verify literature evidence", "prepare protocol/plan.json", "new human authorization and protocol freeze"]}
    if dry_run:
        return report
    backup = root.parent / (root.name + ".v1-backup-" + uuid.uuid4().hex[:8])
    shutil.copytree(root, backup)
    original = (root / "project.json").read_text(encoding="utf-8")
    temporary = root / (".cra-migrate-" + uuid.uuid4().hex)
    temporary.mkdir()
    try:
        db = sqlite3.connect(str(temporary / "state.sqlite"))
        db.executescript(SCHEMA)
        db.execute("INSERT INTO meta VALUES ('schema_version','2')")
        db.commit()
        db.close()
        temporary.rename(root / ".cra")
        from . import __version__
        save(root / "project.json", {"schema_version": 2, "engine_version": __version__, "name": old["name"], "synthetic": old["synthetic"]})
        require(not (root / "brief.json").exists(), "Existing brief refused; restore backup and reconcile explicitly")
        brief = default_brief(old["name"])
        brief["profile"].update(name=old["profile"], target=old["target"])
        save(root / "brief.json", brief)
        for directory in ("literature", "exports"):
            (root / directory).mkdir(exist_ok=True)
        store = Store(root)
        with store.tx():
            store.set_meta("synthetic", old["synthetic"])
            store.set_meta("stage", "design")
            store.put("legacy_history", "historical_declarations", old)
            store.event("migrated", {"from": 1, "to": 2, "backup": backup.name, "new_approvals": 0})
        store.close()
    except BaseException:
        atomic(root / "project.json", original)
        if (root / ".cra").exists():
            shutil.rmtree(root / ".cra")
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return dict(report, backup=str(backup), dry_run=False)
