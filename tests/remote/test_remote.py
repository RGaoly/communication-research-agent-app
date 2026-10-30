"""Synthetic engineering evidence only; fixture approvals are NOT human acceptance."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request

import pytest

from cra_engine.common import EngineError, digest, load, save, sha
from cra_engine.execution import execute
from cra_engine.runtime import run, sync
from cra_engine.store import Store
from cra_remote.client import RemoteExecutor
from cra_remote.protocol import identity, parse, sign, verify
from cra_remote.worker import Server, Worker

spec = importlib.util.spec_from_file_location("remote_demo", Path(__file__).resolve().parents[2] / "examples/run_engine_demo.py")
demo = importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    worker = Worker(tmp_path_factory.mktemp("real-remote-worker").resolve(), secrets.token_hex(32))
    worker.start()
    assert worker.capability["passed"], "Actual OS isolation must pass; never skip the remote blackbox chain"
    server = Server(("127.0.0.1", 0), worker)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    client = RemoteExecutor("http://127.0.0.1:" + str(server.server_port), worker.token, test_loopback=True)
    yield worker, client
    server.shutdown(); server.server_close(); worker.close(); thread.join(5)


def approve(store, scope):
    store.approve(scope, "SYNTHETIC TEST ONLY", "Engineering fixture; no human acceptance", "APPROVE " + store.snapshot(scope)[:12])


@pytest.fixture
def project(tmp_path, server):
    worker, client = server
    root = demo.prepare(tmp_path.resolve() / "project")
    brief = load(root / "brief.json")
    brief["execution"] = {"backend": "remote", "endpoint": client.endpoint, "identity_hash": digest(identity())}
    brief["permissions"]["remote_statistics"] = True
    save(root / "brief.json", brief)
    store = Store(root); store.remote_executor = client
    sync(store)
    with store.tx(): store.set_meta("measurement_review", digest({k: sha(root / brief["data"][k]) for k in ("csv", "codebook")}))
    approve(store, "authorization")
    yield store
    store.close()


def payload(store, action="audit"):
    brief = store.get("brief")
    paths = [store.root / brief["data"][k] for k in ("csv", "codebook")]
    value = {"csv_path": str(paths[0]), "book_path": str(paths[1]), "min_cell": 10}
    if action == "analysis": value["protocol"] = store.get("protocol")
    return value, paths


def test_real_http_isolated_full_research_and_fresh_reproduction(project, server):
    """No replacement of transport, statistics, OS execution or engine in this test."""
    from cra_engine.cli import reproduce
    run(project)
    assert project.get("audit", fresh=True)["sample_flow"]["input_rows"] > 0
    assert project.get("analysis") is None
    approve(project, "protocol"); run(project)
    assert project.get("analysis", fresh=True)["models"]
    before = len(list(server[0].root.glob("*/state.json")))
    report = reproduce(project)
    assert report["passed"] and report["remote_receipt"]
    assert len(list(server[0].root.glob("*/state.json"))) == before + 1
    assert reproduce(project)["remote_receipt"]["job"] != report["remote_receipt"]["job"]
    for path in server[0].root.glob("*/request.json"):
        raw = path.read_text()
        assert server[0].token not in raw and "approvals" not in raw and "api_key" not in raw


def test_response_loss_resumes_same_id_even_with_different_deadline(project, server, monkeypatch):
    client = server[1]
    original = client._request
    def lost(method, path, body=None):
        result = original(method, path, body)
        if method == "POST": raise EngineError("TEST lost response after server acceptance")
        return result
    monkeypatch.setattr(client, "_request", lost)
    value, paths = payload(project)
    before = len(list(server[0].root.glob("*/state.json")))
    with pytest.raises(EngineError, match="lost response"): execute(project, "audit", value, paths, 30)
    monkeypatch.setattr(client, "_request", original)
    result = execute(project, "audit", value, paths, 25)
    assert result["result"] and len(list(server[0].root.glob("*/state.json"))) == before + 1


def test_no_permission_no_upload(project, server):
    brief = project.get("brief"); brief["permissions"]["remote_statistics"] = False
    save(project.root / "brief.json", brief); sync(project); approve(project, "authorization")
    value, paths = payload(project)
    before = len(list(server[0].root.glob("*/state.json")))
    with pytest.raises(EngineError, match="Authorize remote"): execute(project, "audit", value, paths)
    assert len(list(server[0].root.glob("*/state.json"))) == before


def test_no_measurement_review_no_upload(project, server):
    with project.tx(): project.set_meta("measurement_review", None)
    value, paths = payload(project)
    before = len(list(server[0].root.glob("*/state.json")))
    with pytest.raises(EngineError, match="measurement review"): execute(project, "audit", value, paths)
    assert len(list(server[0].root.glob("*/state.json"))) == before


def test_mismatched_worker_identity_precedes_upload(project, server, monkeypatch):
    original = server[1]._request
    def wrong(method, path, body=None):
        result = copy.deepcopy(original(method, path, body))
        if path == "/v1/health": result["identity"]["protocol"] = 999
        return result
    monkeypatch.setattr(server[1], "_request", wrong)
    value, paths = payload(project)
    before = len(list(server[0].root.glob("*/state.json")))
    with pytest.raises(EngineError, match="mismatch"): execute(project, "audit", value, paths)
    assert len(list(server[0].root.glob("*/state.json"))) == before


def test_result_tampering_fails(project, server, monkeypatch):
    original = server[1]._request
    def wrong(method, path, body=None):
        result = copy.deepcopy(original(method, path, body))
        if result.get("status") == "succeeded": result["result"]["data_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(server[1], "_request", wrong)
    value, paths = payload(project)
    with pytest.raises(EngineError, match="digest mismatch"): execute(project, "audit", value, paths)


def test_missing_operator_configuration_never_falls_back(project):
    project.remote_executor = None
    value, paths = payload(project)
    with pytest.raises(EngineError, match="configuration missing"): execute(project, "audit", value, paths)


def test_revoked_authorization_and_changed_inputs_do_not_upload(project, server):
    value, paths = payload(project)
    before = len(list(server[0].root.glob("*/state.json")))
    with project.tx(): project.db.execute("DELETE FROM approvals")
    with pytest.raises(EngineError, match="Authorize remote"): execute(project, "audit", value, paths)
    approve(project, "authorization")
    paths[0].write_text(paths[0].read_text() + "\n")
    with pytest.raises(EngineError, match="measurement review"): execute(project, "audit", value, paths)
    assert len(list(server[0].root.glob("*/state.json"))) == before


def test_unknown_remote_result_never_creates_another_job(project, server, monkeypatch):
    worker, client = server
    original = client._request
    counts = {"posts": 0}
    def unknown(method, path, body=None):
        result = original(method, path, body)
        if method == "POST": counts["posts"] += 1
        if "/jobs/" in path and result.get("status") not in ("not_found",):
            result = {"job": result["job"], "request_hash": result["request_hash"], "status": "unknown"}
        return result
    monkeypatch.setattr(client, "_request", unknown)
    value, paths = payload(project)
    for timeout in (30, 20):
        with pytest.raises(EngineError, match="did not complete"): execute(project, "audit", value, paths, timeout)
    assert counts["posts"] == 1


def test_credential_and_redirect_boundaries(server):
    client = server[1]
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(client.endpoint + "/v1/health")
    assert error.value.code == 401
    for url in ("http://127.0.0.1:8781", "https://user:pass@example.com", "https://example.com/v1", "https://example.com:8443"):
        with pytest.raises(EngineError): RemoteExecutor(url, "x" * 40)
    from cra_remote.client import NoRedirect
    with pytest.raises(EngineError): NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")


def test_signed_protocol_rejects_tamper_duplicate_keys_and_nan():
    envelope = sign({"status": "succeeded"}, "x" * 40)
    envelope["body"]["status"] = "failed"
    with pytest.raises(EngineError): verify(envelope, "x" * 40)
    for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
        with pytest.raises(EngineError): parse(raw)


def wire_request(project):
    value, paths = payload(project)
    files = {}
    for key, path in zip(("csv", "codebook"), paths):
        raw = path.read_bytes()
        files[key] = {"base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"protocol": 1, "identity": identity(), "action": "audit", "files": files, "parameters": {"min_cell": 10}, "timeout": 30}


@pytest.mark.parametrize("mutation", ["command", "path", "hash", "sensitive", "malformed_csv", "timeout"])
def test_worker_rejects_unapproved_contract(project, server, mutation):
    request = wire_request(project)
    if mutation == "command": request["action"] = "exec"
    if mutation == "path": request["parameters"]["csv_path"] = "/etc/passwd"
    if mutation == "hash": request["files"]["csv"]["sha256"] = "0" * 64
    if mutation == "timeout": request["timeout"] = 1000000
    if mutation == "sensitive":
        book = parse(base64.b64decode(request["files"]["codebook"]["base64"]))
        next(iter(book["columns"].values()))["sensitive"] = True
        raw = json.dumps(book).encode()
        request["files"]["codebook"] = {"base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    if mutation == "malformed_csv":
        raw = b"x,y\n1,2,3\n"
        request["files"]["csv"] = {"base64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    before = len(list(server[0].root.glob("*/state.json")))
    with pytest.raises(EngineError): server[0].submit(secrets.token_hex(16), request)
    assert len(list(server[0].root.glob("*/state.json"))) == before


def test_restart_marks_inflight_unknown_and_does_not_resubmit(tmp_path):
    root = tmp_path.resolve() / "worker"
    job = "a" * 32
    save(root / job / "state.json", {"job": job, "request_hash": "old", "status": "running", "created_epoch": time.time()})
    worker = Worker(root, "x" * 40)
    assert worker.get(job)["status"] == "unknown"
    with pytest.raises(EngineError): worker.submit(job, {})


def test_real_running_job_cancellation_retains_terminal_record(project, server):
    worker = server[0]
    job = secrets.token_hex(16)
    worker.submit(job, wire_request(project))
    deadline = time.monotonic() + 10
    while worker.get(job)["status"] == "queued" and time.monotonic() < deadline: time.sleep(.01)
    assert worker.get(job)["status"] == "running"
    worker.cancel(job)
    while worker.get(job)["status"] == "running" and time.monotonic() < deadline: time.sleep(.02)
    assert worker.get(job)["status"] == "cancelled"
    assert "result" not in worker.get(job)


def test_real_failed_analysis_preserves_completed_and_failed_specifications(project):
    from cra_engine.isolation import IsolatedRecipeError
    from cra_engine.schema import validate_protocol
    run(project)
    protocol = copy.deepcopy(project.get("protocol"))
    # The second model violates the binary-outcome premise, after a valid OLS.
    protocol["models"].append(dict(protocol["models"][0], id="bad_binary", family="logit", covariance="classical"))
    save(project.root / "protocol/plan.json", protocol)
    sync(project)
    run(project)
    approve(project, "protocol")
    value, paths = payload(project, "analysis")
    with pytest.raises(IsolatedRecipeError) as error: execute(project, "analysis", value, paths)
    progress = load(project.root / error.value.metadata["progress_path"])
    assert [r["status"] for r in progress["entries"]] == ["succeeded", "failed"]
    assert len(progress["completed_models"]) == 1


def test_expiry_deletes_materials_but_preserves_idempotency_tombstone(tmp_path):
    root = tmp_path.resolve() / "worker"
    worker = Worker(root, "x" * 40, retention_seconds=1)
    job = "b" * 32
    save(root / job / "state.json", {"job": job, "request_hash": "old", "status": "unknown", "created_epoch": 0, "result": {"n": 10}})
    (root / job / "input.csv").write_text("SYNTHETIC ONLY")
    worker._cleanup()
    assert worker.get(job)["status"] == "expired" and "result" not in worker.get(job)
    assert not (root / job / "input.csv").exists()
    with pytest.raises(EngineError): worker.submit(job, {})


def test_graphical_remote_consent_is_separate_and_invalidates_authorization(tmp_path, server, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from cra_workspace import app as presentation
    presentation.hosting_environment.clear()
    monkeypatch.setattr(presentation, "operator_executor", lambda: server[1])
    monkeypatch.setenv("CRA_DEPLOYMENT", "cloud")
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui"))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=20).run()
    assert not app.exception
    app.text_input[0].set_value("Remote UI synthetic fixture")
    app.text_area[0].set_value("Synthetic transfer consent engineering test")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    p = app.session_state["project"]; workspace = app.session_state["workspace"]
    workspace.import_data(p, "fixture.csv", b"x,y\n1,2\n2,3\n3,5\n", cloud_consent=True)
    workspace.measurement(p, workspace.snapshot(p)["codebook"], {}, "TEST ONLY", "Synthetic engineering fixture review")
    challenge = workspace.challenge(p, "authorization")
    workspace.approve(p, "authorization", challenge["nonce"], challenge["confirmation"], "TEST ONLY", "Synthetic engineering fixture approval", True)
    app.radio[0].set_value("研究概览").run()
    assert next(b for b in app.button if b.label == "继续执行获批研究").disabled
    app.radio[0].set_value("模型与设置").run()
    next(c for c in app.checkbox if c.label == "本项目使用上述独立统计服务器").check()
    next(b for b in app.button if b.label == "保存统计执行范围").click().run()
    assert any("明确允许" in e.value for e in app.error)
    assert workspace.snapshot(p)["brief"].get("execution", {}).get("backend", "local") == "local"
    next(c for c in app.checkbox if c.label.startswith("我有权并明确同意将本项目")).check()
    next(b for b in app.button if b.label == "保存统计执行范围").click().run()
    assert not app.exception
    state = workspace.snapshot(p)
    assert state["brief"]["execution"]["backend"] == "remote" and state["brief"]["permissions"]["remote_statistics"]
    assert not state["status"]["approvals"]["authorization"]
    assert server[0].token not in json.dumps(state)
    presentation.hosting_environment.clear()
