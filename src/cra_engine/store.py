"""Transactional state, evidence dependencies, approvals, leases and budget ledger."""
import os
import sqlite3
import uuid
import time
from contextlib import contextmanager
from pathlib import Path

from .common import EngineError, atomic, digest, dumps, finite, load, now, require, sha, within

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE objects(id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, hash TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, stale INTEGER NOT NULL DEFAULT 0);
CREATE TABLE edges(parent TEXT NOT NULL, child TEXT NOT NULL, PRIMARY KEY(parent,child));
CREATE TABLE versions(object_id TEXT, version INTEGER, body TEXT, hash TEXT, at TEXT, PRIMARY KEY(object_id,version));
CREATE TABLE tasks(id TEXT PRIMARY KEY, kind TEXT NOT NULL, deps TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, input_hash TEXT, attempts INTEGER NOT NULL DEFAULT 0, error_hash TEXT, error_count INTEGER NOT NULL DEFAULT 0, started TEXT, finished TEXT);
CREATE TABLE approvals(id TEXT PRIMARY KEY, scope TEXT, snapshot TEXT, reviewer TEXT, note TEXT, at TEXT);
CREATE TABLE calls(id TEXT PRIMARY KEY, task TEXT, status TEXT, reserved REAL, actual REAL, model TEXT, usage TEXT, at TEXT);
CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, action TEXT, body TEXT, previous TEXT, hash TEXT);
CREATE TABLE leases(name TEXT PRIMARY KEY, owner TEXT NOT NULL, pid INTEGER NOT NULL, at TEXT NOT NULL);
"""


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        require(self.root.is_dir(), "Project does not exist")
        require(not any(p.is_symlink() for p in self.root.rglob("*")), "Project symlinks refused")
        manifest = load(self.root / "project.json")
        require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 2, "Expected project schema 2; migrate explicitly")
        db = within(self.root, ".cra/state.sqlite")
        require(db.is_file(), "Project database missing; restore a complete backup")
        self.db = sqlite3.connect(str(db), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        require(self.db.execute("PRAGMA quick_check").fetchone()[0] == "ok", "Database integrity failure")
        require(self.meta("schema_version") == 2, "Unsupported database schema")
        self.verify_events()

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return __import__("json").loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, dumps(value)))

    def event(self, action, body):
        previous = self.meta("event_head")
        item = {"at": now(), "action": action, "body": body, "previous": previous}
        signature = digest(item)
        self.db.execute("INSERT INTO events(at,action,body,previous,hash) VALUES (?,?,?,?,?)",
                        (item["at"], action, dumps(body), previous, signature))
        self.set_meta("event_head", signature)

    def verify_events(self):
        # GUI status polling can race a committing worker. Verify both event rows
        # and their head in one SQLite read snapshot, not two database generations.
        own_snapshot = not self.db.in_transaction
        if own_snapshot: self.db.execute("BEGIN")
        try:
            previous = None
            for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
                item = {"at": row["at"], "action": row["action"], "body": __import__("json").loads(row["body"]), "previous": row["previous"]}
                require(previous == row["previous"] and digest(item) == row["hash"], "Event chain damaged")
                previous = row["hash"]
            require(previous == self.meta("event_head"), "Event chain truncated")
        finally:
            if own_snapshot: self.db.execute("ROLLBACK")

    def get(self, ident, fresh=False):
        row = self.db.execute("SELECT * FROM objects WHERE id=?", (ident,)).fetchone()
        if not row:
            return None
        require(not fresh or not row["stale"], "Evidence is stale: " + ident)
        return __import__("json").loads(row["body"])

    def object_hash(self, ident):
        row = self.db.execute("SELECT hash,stale FROM objects WHERE id=?", (ident,)).fetchone()
        return None if not row or row["stale"] else row["hash"]

    def invalidate(self, parent):
        descendants = [r[0] for r in self.db.execute("WITH RECURSIVE d(id) AS (SELECT child FROM edges WHERE parent=? UNION SELECT e.child FROM edges e JOIN d ON e.parent=d.id) SELECT id FROM d", (parent,))]
        for ident in descendants:
            self.db.execute("UPDATE objects SET stale=1 WHERE id=?", (ident,))
            self.db.execute("UPDATE tasks SET status='stale',error_hash=NULL,error_count=0 WHERE id=?", (ident,))
        return descendants

    def put(self, ident, kind, body, parents=()):
        require(ident not in parents, "Self dependency refused")
        signature = digest(body)
        old = self.db.execute("SELECT hash,version,stale FROM objects WHERE id=?", (ident,)).fetchone()
        if old and old["hash"] == signature and not old["stale"]:
            return False
        if old:
            self.invalidate(ident)
        version = old["version"] + 1 if old else 1
        self.db.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,0)", (ident, kind, dumps(body), signature, version))
        self.db.execute("INSERT INTO versions VALUES (?,?,?,?,?)", (ident, version, dumps(body), signature, now()))
        self.db.execute("DELETE FROM edges WHERE child=?", (ident,))
        for parent in parents:
            self.db.execute("INSERT INTO edges VALUES (?,?)", (parent, ident))
        return True

    def snapshot(self, scope):
        subjects = {"authorization": ["brief"], "protocol": ["brief", "dataset", "codebook", "audit", "corpus", "protocol"],
                    "final": ["brief", "dataset", "codebook", "corpus", "protocol", "analysis", "claims", "draft", "method_review", "evidence_review"]}
        require(scope in subjects, "Unknown approval scope")
        values = {key: self.object_hash(key) for key in subjects[scope]}
        require(all(values.values()), "Approval dependencies missing or stale")
        return digest(values)

    def approved(self, scope):
        try:
            snapshot = self.snapshot(scope)
        except EngineError:
            return False
        return bool(self.db.execute("SELECT 1 FROM approvals WHERE scope=? AND snapshot=?", (scope, snapshot)).fetchone())

    def approve(self, scope, reviewer, note, confirmation):
        require(confirmation == "APPROVE " + self.snapshot(scope)[:12], "Approval confirmation did not match current evidence")
        require(len(reviewer.strip()) >= 2 and len(note.strip()) >= 8, "A real reviewer and substantive note are required")
        with self.tx():
            self.db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, scope, self.snapshot(scope), reviewer, note, now()))
            self.event("human_approval", {"scope": scope, "snapshot": self.snapshot(scope)})

    def add_task(self, ident, kind, deps, body=None):
        self.db.execute("INSERT OR IGNORE INTO tasks(id,kind,deps,status,body) VALUES (?,?,?,'pending',?)", (ident, kind, dumps(deps), dumps(body or {})))

    def task_rows(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM tasks ORDER BY rowid")]

    def budget(self):
        brief = self.get("brief") or {}
        ceiling = brief.get("limits", {}).get("max_cost", 0)
        rows = self.db.execute("SELECT * FROM calls").fetchall()
        spent = sum(r["actual"] or 0 for r in rows)
        reserved = sum(r["reserved"] for r in rows if r["status"] in ("reserved", "uncertain") and r["actual"] is None)
        by_task = {}
        for row in rows:
            account = by_task.setdefault(row["task"], {"spent": 0, "reserved": 0, "calls": 0})
            account["spent"] += row["actual"] or 0
            account["reserved"] += row["reserved"] if row["status"] in ("reserved", "uncertain") and row["actual"] is None else 0
            account["calls"] += 1
        return {"ceiling": ceiling, "spent": spent, "reserved": reserved, "remaining": max(0, ceiling - spent - reserved),
                "calls": len(rows), "uncertain": sum(r["status"] == "uncertain" for r in rows), "by_task": by_task, "currency": brief.get("limits", {}).get("currency", "USD")}

    def reserve(self, task, amount, model):
        require(finite(amount) and amount > 0, "Call reservation must be positive")
        with self.tx():
            budget = self.budget()
            require(not budget["uncertain"], "Uncertain paid call requires human reconciliation; no automatic resend")
            require(amount <= budget["remaining"] + 1e-12, "Budget exhausted; no new call started")
            ident = uuid.uuid4().hex
            self.db.execute("INSERT INTO calls VALUES (?,?, 'reserved',?,NULL,?,NULL,?)", (ident, task, amount, model, now()))
            self.event("call_reserved", {"call": ident, "task": task, "reserved": amount, "run": self.meta("active_run_id")})
        return ident

    def settle(self, ident, amount, usage=None, uncertain=False, checkpoint=None):
        require(amount is None or finite(amount) and amount >= 0, "Invalid actual cost")
        with self.tx():
            row = self.db.execute("SELECT * FROM calls WHERE id=?", (ident,)).fetchone()
            require(row and row["status"] in ("reserved", "uncertain"), "Call already settled or unknown")
            exceeded = amount is not None and amount > row["reserved"] + 1e-12
            uncertain = uncertain or exceeded
            self.db.execute("UPDATE calls SET status=?,actual=?,usage=? WHERE id=?", ("uncertain" if uncertain else "settled", amount, dumps(usage or {}), ident))
            if checkpoint is not None and not uncertain:
                self.put("response_" + ident, "model_response", dict(checkpoint, call_id=ident, consumed=False))
            self.event("call_uncertain" if uncertain else "call_settled", {"call": ident, "actual": amount})
            if exceeded:
                self.event("call_reservation_exceeded", {"call": ident, "reserved": row["reserved"], "actual": amount})
        # Commit observed costs before raising. Rolling back would erase billing
        # evidence and permit an unsafe resend. An overrun cannot be replayed.
        require(not exceeded, "Provider usage exceeded the reserved cost; human billing reconciliation required")

    def pending_response(self, account, request_hash):
        for row in self.db.execute("SELECT id,body FROM objects WHERE kind='model_response' ORDER BY rowid DESC"):
            body = __import__("json").loads(row["body"])
            if not body.get("consumed") and body.get("account") == account and body.get("request_hash") == request_hash:
                with self.tx():
                    body["delivery_run"] = self.meta("active_run_id") or account
                    self.put(row["id"], "model_response", body)
                    self.event("model_response_replayed", {"response": row["id"], "delivery_run": body["delivery_run"]})
                return body["message"]
        return None

    def consume_responses(self, delivery_run):
        # Caller holds the same transaction that commits the corresponding task.
        for row in self.db.execute("SELECT id,body FROM objects WHERE kind='model_response'").fetchall():
            body = __import__("json").loads(row["body"])
            if not body.get("consumed") and body.get("delivery_run") == delivery_run:
                self.put(row["id"], "model_response", dict(body, consumed=True))

    @contextmanager
    def lease(self):
        owner = uuid.uuid4().hex
        with self.tx():
            old = self.db.execute("SELECT * FROM leases WHERE name='run'").fetchone()
            if old:
                try:
                    os.kill(old["pid"], 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
                require(not alive, "Another run is active")
                self.db.execute("DELETE FROM leases WHERE name='run'")
            self.db.execute("INSERT INTO leases VALUES ('run',?,?,?)", (owner, os.getpid(), now()))
            # A crashed HTTP request is not safe to retry automatically.
            self.db.execute("UPDATE calls SET status='uncertain' WHERE status='reserved'")
            self.db.execute("UPDATE tasks SET status='ready' WHERE status='running'")
            self.set_meta("paused", False)
            self.set_meta("active_run_id", None)
            for row in self.db.execute("SELECT id,body FROM objects WHERE kind='run_record'").fetchall():
                body = __import__("json").loads(row["body"])
                if body.get("status") == "running":
                    self.put(row["id"], "run_record", dict(body, status="interrupted", finished=now()))
            self.set_meta("run_deadline", time.time() + (self.get("brief") or {}).get("limits", {}).get("max_seconds", 7200))
            self.event("run_started", {"owner": owner})
        try:
            yield
        finally:
            with self.tx():
                self.db.execute("DELETE FROM leases WHERE name='run' AND owner=?", (owner,))
                self.event("run_stopped", {})


def initialize(root, name="Communication research", synthetic=False):
    root = Path(root).absolute()
    require(root == root.resolve() and not root.exists(), "Use a new canonical project path; existing work is never overwritten")
    root.mkdir(parents=True)
    for rel in (".cra", "data", "protocol", "literature", "artifacts", "manuscript", "reports", "exports"):
        (root / rel).mkdir()
    db = sqlite3.connect(str(root / ".cra/state.sqlite"))
    db.executescript(SCHEMA)
    db.execute("INSERT INTO meta VALUES ('schema_version','2')")
    db.commit()
    db.close()
    from . import __version__
    atomic(root / "project.json", dumps({"schema_version": 2, "engine_version": __version__, "name": name, "synthetic": synthetic}) + "\n")
    from .schema import default_brief
    from .common import save
    save(root / "brief.json", default_brief(name))
    store = Store(root)
    with store.tx():
        store.set_meta("synthetic", synthetic)
        store.set_meta("stage", "design")
        store.set_meta("complete", False)
        store.event("initialized", {"schema_version": 2, "synthetic": synthetic})
    store.close()
    return {"project": str(root), "schema_version": 2, "next": "Fill brief.json, data/input.csv, data/codebook.json; then plan"}
