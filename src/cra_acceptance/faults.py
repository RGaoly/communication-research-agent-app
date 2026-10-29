"""Kill actual subprocesses at persistence boundaries; no replacement store or I/O."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from cra_engine.common import EngineError, atomic, load, save, require
from cra_engine.store import Store, initialize

SCENARIOS = ("before_commit", "after_commit", "reserved", "request_sent", "response_received",
             "response_checkpoint", "file_written", "published", "dependency_changed", "running_task")


def child(root, scenario, marker, endpoint):
    store = Store(root)
    def stop():
        atomic(marker, "ready")
        while True:
            time.sleep(1)
    with store.lease():
        if scenario == "before_commit":
            with store.tx():
                store.put("probe", "probe", {"committed": False})
                stop()
        elif scenario == "after_commit":
            with store.tx():
                store.put("probe", "probe", {"committed": True})
            stop()
        elif scenario in ("reserved", "request_sent", "response_received", "response_checkpoint"):
            ident = store.reserve("fault-probe", .1, "LOCAL PROTOCOL FIXTURE")
            if scenario == "reserved":
                stop()
            import urllib.request
            request = urllib.request.Request(endpoint, b'{"synthetic":true}', {"Content-Type": "application/json"})
            if scenario == "request_sent":
                # Server records the request before blocking response. Parent kills us there.
                urllib.request.urlopen(request, timeout=30).read()
            else:
                urllib.request.urlopen(request, timeout=30).read()
                if scenario == "response_received":
                    stop()
                store.settle(ident, .02, {"fixture": True}, checkpoint={"account": "fault-probe", "request_hash": "frozen-request", "message": {"content": "durable reply"}, "delivery_run": "old-run"})
                stop()
        elif scenario in ("file_written", "published"):
            atomic(Path(root)/"artifacts/probe.txt", "committed file")
            if scenario == "published":
                with store.tx():
                    store.put("probe", "artifact", {"path": "artifacts/probe.txt"})
            stop()
        elif scenario == "dependency_changed":
            with store.tx():
                store.put("parent", "input", {"version": 1})
                store.put("child", "result", {"value": 1}, ["parent"])
                store.put("parent", "input", {"version": 2})
            stop()
        elif scenario == "running_task":
            with store.tx():
                store.add_task("probe", "probe", [])
                store.db.execute("UPDATE tasks SET status='running' WHERE id='probe'")
                store.put("run_probe", "run_record", {"status": "running"})
            stop()


def run(root, repetitions=10):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    root = Path(root)
    cases = []
    observed = {"requests": 0, "hold": False, "marker": None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            observed["requests"] += 1
            if observed["hold"]:
                atomic(observed["marker"], "request-observed")
                time.sleep(.5)
            try:
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    endpoint = "http://127.0.0.1:%s/probe" % server.server_port
    try:
        for scenario in SCENARIOS:
            for repeat in range(repetitions):
                ident = "%s-%02d" % (scenario, repeat)
                project = root/ident
                initialize(project, "SYNTHETIC crash boundary", synthetic=True)
                with_store = Store(project)
                with with_store.tx():
                    with_store.put("brief", "research_brief", {"limits": {"max_cost": 1, "max_seconds": 120}})
                with_store.close()
                marker = project/"ready"
                observed.update(hold=scenario == "request_sent", marker=marker)
                before = observed["requests"]
                process = subprocess.Popen([sys.executable, "-m", "cra_acceptance.faults", str(project), scenario, str(marker), endpoint], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic()+15
                    while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    reached = marker.exists()
                    process.kill() if process.poll() is None else None
                    out, err = process.communicate(timeout=5)
                    require(reached, "Crash marker not reached")
                    store = Store(project)
                    with store.lease():
                        checks = {"events_valid": True, "exit_was_sigkill": process.returncode == -signal.SIGKILL}
                        if scenario == "before_commit": checks["rolled_back"] = store.get("probe") is None
                        if scenario == "after_commit": checks["preserved"] = store.get("probe") == {"committed": True}
                        if scenario in ("reserved", "request_sent", "response_received"):
                            checks["unknown_request_not_retried"] = store.budget()["uncertain"] == 1
                            try:
                                store.reserve("forbidden-retry", .1, "fixture")
                                checks["unknown_request_not_retried"] = False
                            except Exception as exc:
                                from cra_engine.common import EngineError
                                if not isinstance(exc, EngineError): raise
                            checks["request_count"] = observed["requests"]-before == (0 if scenario == "reserved" else 1)
                        if scenario == "response_checkpoint":
                            checks["durable_paid_reply"] = store.pending_response("fault-probe", "frozen-request") == {"content": "durable reply"}
                            checks["exactly_one_charge"] = store.budget()["calls"] == 1 and store.budget()["spent"] == .02 and store.budget()["reserved"] == 0
                        if scenario in ("file_written", "published"):
                            checks["file_intact"] = (project/"artifacts/probe.txt").read_text() == "committed file"
                            checks["only_committed_registered"] = bool(store.get("probe")) == (scenario == "published")
                        if scenario == "dependency_changed": checks["stale_result_rejected"] = store.object_hash("child") is None
                        if scenario == "running_task": checks["task_recoverable"] = store.task_rows()[0]["status"] == "ready" and store.get("run_probe")["status"] == "interrupted"
                    store.close()
                    success = all(checks.values())
                    observation = {"scenario": scenario, "repetition": repeat, "checks": checks, "returncode": process.returncode, "requests_observed": observed["requests"]-before, "limits": "Synthetic transaction/transport boundary. Not a real paid provider or complete fault-state exploration."}
                except Exception as exc:
                    success = False
                    observation = {"scenario": scenario, "failure_type": type(exc).__name__}
                finally:
                    if process.poll() is None: process.kill(); process.wait()
                save(root/(ident+".json"), observation)
                cases.append({"id": ident, "status": "passed" if success else "failed", "recovered": success, "critical_violation": not success, "artifacts": ["faults/"+ident+".json"]})
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    return {"cases": cases, "boundaries": list(SCENARIOS), "scope": "Actual SIGKILL at ten transaction/file/HTTP boundaries, ten repetitions each. Pause/worker cancellation verified separately. No retry-count padding."}


if __name__ == "__main__":
    if sys.argv[1] == "--worker-child":
        from cra_engine.isolation import execute
        from cra_engine.cli import cancellation_signals
        store = Store(sys.argv[2])
        try:
            with cancellation_signals():
                execute(store,"audit",{"csv_path":str(store.root/"data/input.csv"),"book_path":str(store.root/"data/codebook.json")},inputs=[store.root/"data/input.csv",store.root/"data/codebook.json"])
        except (EngineError, KeyboardInterrupt):
            sys.exit(130)
        finally: store.close()
    else:
        child(*sys.argv[1:])
