"""Human CLI and stable JSON interface. Approval is deliberately interactive."""
import argparse
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .common import EngineError, digest, finite, load, require, save, within
from .store import Store, initialize


@contextmanager
def cancellation_signals():
    import signal, threading
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    def cancelled(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, cancelled)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("project", type=Path)
    init.add_argument("--name", default="Communication research")
    init.add_argument("--schema", type=int, choices=(1, 2), default=2)
    init.add_argument("--synthetic", action="store_true")
    for name in ("plan", "run", "resume", "pause", "status", "validate", "approve", "evidence", "reproduce", "export", "migrate", "doctor", "model-test", "literature", "budget", "analyze", "review", "advance", "configure", "release-check"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
        if name == "approve":
            command.add_argument("--scope", choices=("authorization", "protocol", "final"), required=True)
            command.add_argument("--reviewer", required=True)
            command.add_argument("--note", required=True)
        elif name == "export":
            command.add_argument("--working", action="store_true")
            command.add_argument("--include-data", action="store_true")
            command.add_argument("--diagnostic", action="store_true")
        elif name == "migrate":
            command.add_argument("--dry-run", action="store_true")
        elif name == "release-check":
            command.add_argument("--pilot-registry", type=Path)
            command.add_argument("--software-report", type=Path)
            command.add_argument("--acceptance-bundle", type=Path)
            command.add_argument("--trust-store", type=Path)
        elif name == "evidence":
            command.add_argument("--id")
        elif name == "literature":
            command.add_argument("--import-file", type=Path)
            command.add_argument("--query")
            command.add_argument("--rows", type=int, default=10)
        elif name == "budget":
            command.add_argument("--resolve")
            command.add_argument("--actual", type=float)
        elif name == "configure":
            command.add_argument("--profile", choices=("apa7", "ica", "cssci", "custom"), required=True)
            command.add_argument("--target", required=True)
        elif name == "validate":
            command.add_argument("--full", action="store_true")
    return p


def confirm(store, scope, reviewer, note):
    require(sys.stdin.isatty(), "Human confirmation requires an interactive terminal; Agent/noninteractive approvals refused")
    from .runtime import readiness, sync
    sync(store)
    if scope == "protocol":
        require(store.approved("authorization"), "Authorize the project first")
        require(store.object_hash("protocol"), "Prepare and validate protocol first")
    if scope == "final":
        require(readiness(store)["ready_for_final"], "Resolve missing/stale evidence and blocking reviews before final approval")
    token = "APPROVE " + store.snapshot(scope)[:12]
    print("This is your research declaration, not automated review. Inspect the current evidence and all limitations.\nType exactly: " + token, file=sys.stderr)
    answer = input()
    store.approve(scope, reviewer, note, answer)
    return {"scope": scope, "recorded": True, "snapshot": store.snapshot(scope), "identity_certified": False}


def reproduce(store):
    from .execution import execute
    from .runtime import sync
    sync(store)
    require(store.approved("protocol"), "Current frozen protocol required")
    expected = store.get("analysis", fresh=True)
    require(expected is not None, "No fresh analysis to reproduce")
    brief = store.get("brief")
    csv_path, book_path = (within(store.root, brief["data"][k]) for k in ("csv", "codebook"))
    execution = execute(store, "analysis", {"csv_path": str(csv_path), "book_path": str(book_path), "protocol": store.get("protocol", fresh=True), "min_cell": brief["limits"]["min_cell"]}, [csv_path, book_path], fresh=True)
    actual = execution["result"]
    differences = []
    def compare(a, b, path=""):
        if finite(a) and finite(b):
            if not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-9):
                differences.append(path)
        elif isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
            for key in a:
                compare(a[key], b[key], path + "." + key)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                compare(x, y, path + "." + str(i))
        elif a != b:
            differences.append(path)
    compare(expected, actual)
    report = {"passed": not differences, "differences": differences, "relative_tolerance": 1e-7, "absolute_tolerance": 1e-9, "remote_receipt": execution.get("remote_receipt")}
    save(store.root / "reports/reproduction.json", report)
    with store.tx():
        store.event("reproduced", {"passed": report["passed"]})
    return report


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    # Unchanged schema-1 CLI semantics, including original argument parsing.
    try:
        if len(argv) >= 2 and argv[0] not in ("migrate", "init"):
            manifest = Path(argv[1]) / "project.json"
            if manifest.is_file() and load(manifest).get("schema_version") == 1:
                from .migration import legacy_module
                return legacy_module().main(argv)
    except (EngineError, OSError, TypeError, AttributeError):
        print('{"error":"Invalid project manifest; inspect locally"}', file=sys.stderr)
        return 2
    args = parser().parse_args(argv)
    store = None
    try:
        root = args.project.absolute()
        require(root == root.resolve(), "Use a canonical path without symlinks")
        if args.command == "init":
            if args.schema == 1:
                from .migration import legacy_module
                legacy_args = ["init", str(root), "--name", args.name] + (["--synthetic"] if args.synthetic else [])
                return legacy_module().main(legacy_args)
            output = initialize(root, args.name, args.synthetic)
        elif args.command == "migrate":
            from .migration import migrate
            output = migrate(root, args.dry_run)
        else:
            store = Store(root)
            from .runtime import plan, readiness, run, status, sync
            if args.command == "plan":
                output = plan(store)
            elif args.command in ("run", "resume", "advance", "analyze"):
                with cancellation_signals():
                    output = run(store)
            elif args.command == "pause":
                with store.tx():
                    store.set_meta("paused", True)
                    store.event("pause_requested", {})
                output = {"paused": True, "next": "resume"}
            elif args.command == "approve":
                output = confirm(store, args.scope, args.reviewer, args.note)
            elif args.command in ("status", "validate", "review"):
                sync(store)
                output = status(store)
            elif args.command == "doctor":
                from .execution import doctor
                output = doctor(store)
            elif args.command == "model-test":
                from .models import ModelAdapter
                sync(store)
                with store.lease():
                    output = ModelAdapter(store).contract_test()
            elif args.command == "evidence":
                sync(store)
                if args.id:
                    row = store.db.execute("SELECT id,kind,hash,version,stale FROM objects WHERE id=?", (args.id,)).fetchone()
                    require(row is not None, "Unknown evidence ID")
                    output = {"object": dict(row), "body": store.get(args.id), "parents": [r[0] for r in store.db.execute("SELECT parent FROM edges WHERE child=?", (args.id,))], "children": [r[0] for r in store.db.execute("SELECT child FROM edges WHERE parent=?", (args.id,))]}
                else:
                    output = {"objects": [dict(r) for r in store.db.execute("SELECT id,kind,version,hash,stale FROM objects ORDER BY rowid")], "edges": [dict(r) for r in store.db.execute("SELECT parent,child FROM edges")]}
            elif args.command == "reproduce":
                output = reproduce(store)
            elif args.command == "release-check":
                from .evaluation import release_check
                output = release_check(store, args.pilot_registry, args.software_report, args.acceptance_bundle, args.trust_store)
            elif args.command == "export":
                from .exporting import export_package, export_diagnostic
                require(not args.diagnostic or not args.include_data, "Diagnostic exports never include raw data")
                output = export_diagnostic(store) if args.diagnostic else export_package(store, args.working, args.include_data)
            elif args.command == "literature":
                from .literature import crossref_search, import_bibliography
                if args.import_file:
                    output = import_bibliography(root, args.import_file)
                else:
                    brief = sync(store)
                    require(store.approved("authorization") and brief["permissions"]["literature_network"], "Authorize literature network access first")
                    require(bool(args.query), "Supply --query or --import-file")
                    output = crossref_search(args.query, brief["permissions"]["allowed_hosts"], args.rows)
                    save(root / "literature/search-results.json", output)
            elif args.command == "budget":
                if args.resolve:
                    require(args.actual is not None and finite(args.actual) and args.actual >= 0, "Actual reconciled cost required")
                    require(sys.stdin.isatty(), "Budget reconciliation requires human terminal confirmation")
                    require(input("Type RECONCILE " + args.resolve + ": ") == "RECONCILE " + args.resolve, "Reconciliation cancelled")
                    store.settle(args.resolve, args.actual, {"human_reconciled": True})
                output = store.budget()
            else:
                brief = load(root / "brief.json")
                brief["profile"].update(name=args.profile, target=args.target)
                save(root / "brief.json", brief)
                sync(store)
                output = {"profile": brief["profile"], "authorization_invalidated": True}
        if json_mode or args.command not in ("status", "run", "resume"):
            print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        else:
            print("阶段: %s | 完成: %s | 预算: %s\n任务: %s\n待处理: %s" % (output.get("stage"), output.get("complete"), output.get("budget"), ", ".join(r["id"] + "=" + r["status"] for r in output.get("tasks", [])), output.get("last_problem") or output.get("readiness")))
        if output.get("passed") is False:
            return 1
        if output.get("release_eligible") is False:
            return 1
        if args.command == "validate" and (output.get("readiness", {}).get("blocking_issues") or output.get("readiness", {}).get("missing")):
            return 1
        return 0
    except KeyboardInterrupt:
        if store and not store.db.in_transaction:
            with store.tx():
                store.set_meta("paused", True)
                store.event("user_cancelled", {})
        print('{"cancelled":true,"checkpoint_retained":true}', file=sys.stderr)
        return 130
    except (EngineError, OSError, ValueError, KeyError, TypeError, sqlite_error()) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, EngineError) else "Local input/state failure; inspect files locally without transmitting raw content"}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()


def sqlite_error():
    import sqlite3
    return sqlite3.Error
