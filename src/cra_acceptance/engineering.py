"""Installed-wheel CLI, actual isolation, boundary and positive-control observations."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from cra_engine.common import EngineError, load, save, sha, safe_text, within
from cra_engine.store import Store
from cra_engine.runtime import plan, run as execute, sync
from cra_engine.statistics import audit, fit_models
from cra_engine.schema import validate_brief, validate_protocol
from cra_engine.package_check import verify_package
from .fixtures import prepare, fixture_approval


def cli(*arguments):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "cra_engine", *map(str, arguments), "--json"], capture_output=True, text=True, env=env, timeout=60)
    return {"arguments": list(map(str, arguments)), "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def run(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    def observe(ident, operation, expected_refusal=False):
        try:
            value = operation()
            passed = bool(value) if not expected_refusal else False
            observation = {"result": value, "refused": False}
        except EngineError as exc:
            passed = expected_refusal
            observation = {"refused": True, "reason": str(exc)}
        except Exception as exc:
            passed = False
            observation = {"unexpected_exception": type(exc).__name__}
        save(root/(ident+".json"), observation)
        cases.append({"id": ident, "status": "passed" if passed else "failed", "artifacts": ["boundaries/"+ident+".json"]})
    project = prepare(root/"synthetic")
    store = Store(project)
    plan(store)
    book = load(project/"data/codebook.json")
    protocol = load(project/"protocol/plan.json")
    corpus = {"items": [{"spans": [{"id": "span_fixture", "status": "supported"}]}]}
    def brief_change(path, value):
        brief = load(project/"brief.json")
        brief[path[0]][path[1]] = value
        return validate_brief(brief)
    observe("noninteractive-approval", lambda: cli("approve", project, "--scope", "authorization", "--reviewer", "TEST", "--note", "Cannot auto-approve research")["returncode"] != 0)
    observe("authorization-required", lambda: execute(store), True)
    observe("symlink-path", lambda: within(project, "../../outside"), True)
    observe("email-egress", lambda: safe_text("respondent@example.invalid"), True)
    observe("key-egress", lambda: safe_text("sk-"+"s"*30), True)
    observe("negative-budget", lambda: brief_change(("limits", "max_cost"), -1), True)
    observe("parallel-limit", lambda: brief_change(("limits", "max_parallel"), 3), True)
    observe("plaintext-secret", lambda: brief_change(("model", "api_key"), "synthetic-secret"), True)
    for label, field, value in [("causal-inference", "inference", "causal"), ("unsupported-missing", "missing", "multiple_imputation")]:
        changed = copy.deepcopy(protocol); changed[field] = value
        observe(label, lambda p=changed: validate_protocol(p, book, corpus), True)
    for label, field, value in [("unsupported-sem", "family", "sem"), ("missing-construct", "y", "latent_trust"), ("weighted-ols", "weight", "weight")]:
        changed = copy.deepcopy(protocol); changed["models"][0][field] = value
        observe(label, lambda p=changed: validate_protocol(p, book, corpus), True)
    altered = copy.deepcopy(book); altered["columns"]["x"]["sensitive"] = True
    save(root/"sensitive-book.json", altered)
    observe("sensitive-column", lambda: audit(project/"data/input.csv", root/"sensitive-book.json"), True)
    altered = copy.deepcopy(book); altered["columns"]["x"]["min"] = 100
    save(root/"range-book.json", altered)
    observe("invalid-scale", lambda: audit(project/"data/input.csv", root/"range-book.json"), True)
    altered = copy.deepcopy(book); altered["design"] = {"strata": "group"}
    save(root/"complex-book.json", altered)
    observe("complex-survey", lambda: any(i["code"] == "complex_survey" for i in audit(project/"data/input.csv", root/"complex-book.json")["issues"]))
    altered = copy.deepcopy(book); altered["cross_national_latent_comparison"] = True
    save(root/"invariance-book.json", altered)
    observe("cross-national-invariance", lambda: any(i["code"] == "invariance_missing" for i in audit(project/"data/input.csv", root/"invariance-book.json")["issues"]))
    changed = copy.deepcopy(protocol); changed["models"][0].update(covariance="cluster", cluster="group")
    observe("too-few-clusters", lambda: fit_models(project/"data/input.csv", project/"data/codebook.json", changed), True)
    from cra_engine.isolation import doctor
    observe("actual-os-isolation", lambda: doctor(store)["result"] == {"network_denied": True, "write_denied": True, "control_read_denied": True})
    observe("zero-budget", lambda: store.reserve("blocked", .1, "fixture"), True)
    installation = []
    for init_args in (("init",root/"cli-new-project","--synthetic"),("init",root/"legacy-project","--schema","1","--synthetic"),("migrate",root/"legacy-project","--dry-run"),("migrate",root/"legacy-project")):
        observation=cli(*init_args);observation["expected_returncode"]=0;installation.append(observation)
    for command, expected in (("plan", 0), ("status", 0), ("doctor", 0), ("pause", 0), ("status", 0), ("resume", 2), ("validate", 1)):
        observation = cli(command, project)
        observation["expected_returncode"] = expected
        installation.append(observation)
    # Diagnostic export must work without fabricating a human approval.
    diagnostic = cli("export", project, "--diagnostic")
    diagnostic["expected_returncode"] = 0
    installation.append(diagnostic)
    try:
        diagnostic_check = verify_package(json.loads(diagnostic["stdout"])["archive"])
    except (ValueError, KeyError):
        diagnostic_check = {"passed": False}
    save(root/"installation.json", {"commands": installation, "diagnostic_check": diagnostic_check, "python": sys.executable, "origin": "installed_public_cli", "human_checkpoints": "pending actual operator; never automatically typed"})
    # A synthetic, explicitly nonhuman fixture exercises the real worker/package
    # pipeline. It is supplementary component evidence, not manual CLI acceptance.
    fixture_approval(store, "authorization")
    execute(store)
    fixture_approval(store, "protocol")
    outcome = execute(store)
    from cra_engine.exporting import export_package
    exported = export_package(store, working=True, include_data=True)
    check = verify_package(exported["directory"])
    import shutil
    reconstruction = root/"independent-directory"
    shutil.copytree(exported["directory"], reconstruction)
    reproduction = subprocess.run([sys.executable, str(reconstruction/"reproduce.py"), str(project/"data/input.csv")], capture_output=True, text=True, timeout=120)
    save(root/"synthetic-pipeline.json", {"outcome": outcome, "export": exported, "package_check": check, "reproduction_returncode": reproduction.returncode, "reproduction_stdout": reproduction.stdout, "reproduction_stderr": reproduction.stderr, "approval_origin": "TEST FIXTURE ONLY, never a real pilot or human CLI sign-off"})
    # Wrong coefficient positive control repairs hashes so only semantic checks catch it.
    table = Path(exported["directory"])/"table.csv"
    text = table.read_text(); lines = text.splitlines(); values = lines[1].split(","); values[4] = str(float(values[4])+1); lines[1] = ",".join(values)
    table.write_text("\n".join(lines)+"\n")
    manifest_path = table.parent/"manifest.json"; manifest = load(manifest_path); manifest["files"]["table.csv"] = sha(table); save(manifest_path, manifest)
    mutated = verify_package(table.parent)
    # Restore the fixture package for downstream reproduction/export review.
    table.write_text(text); manifest["files"]["table.csv"] = sha(table); save(manifest_path, manifest)
    stale_before = store.approved("protocol")
    data = project/"data/input.csv"; data.write_text(data.read_text()+"\n")
    sync(store)
    stale_detected = stale_before and not store.approved("protocol") and not store.object_hash("analysis")
    # Test the outbound observer with a deliberately disallowed synthetic canary.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading, urllib.request
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            captured.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%s" % server.server_port, b'CONTROL_UNAUTHORIZED_CANARY'), timeout=5).read()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    mutation_results = [("wrong_coefficient", not mutated["passed"], mutated), ("stale_approval", stale_detected, {"old_approval_invalidated": stale_detected}), ("unauthorized_request", any("CONTROL_UNAUTHORIZED_CANARY" in item for item in captured), {"captured": captured, "scope": "Observer sensitivity control; not evidence of product preventing every egress path"})]
    mutations = []
    for name, detected, observation in mutation_results:
        save(root/("mutation-"+name+".json"), observation)
        mutations.append({"id": name, "mutation": name, "detected": detected, "status": "passed" if detected else "failed", "artifacts": ["boundaries/mutation-"+name+".json"]})
    store.close()
    installed = all(i["returncode"] == i["expected_returncode"] for i in installation) and diagnostic_check["passed"] and check["passed"] and reproduction.returncode == 0
    return {"boundaries": {"cases": cases, "scope": "Actual adapter and public CLI negatives plus OS isolation probe. Does not establish real-model injection resistance."}, "installation": {"cases": [{"id": "installed-cli-and-synthetic-worker", "status": "passed" if installed else "failed", "artifacts": ["boundaries/installation.json", "boundaries/synthetic-pipeline.json"]}], "manual_cli_approval": "pending"}, "mutations": {"cases": mutations}}
