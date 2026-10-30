"""Engineering fixtures only. No test reviewer represents a real approval."""
import copy
import io
import json
import os
from pathlib import Path
import threading
import zipfile

import pytest

from cra_engine.common import EngineError, digest, load, save, sha
from cra_engine.store import Store
from cra_workspace.intake import read_upload
from cra_workspace.security import Credentials, Reviews
from cra_workspace.service import Workspace

NOTE = "TEST FIXTURE ONLY; synthetic software verification, no human research approval"
QUOTE = "This is a synthetic engineering note, not academic evidence or a real research participant."


def approve(w, p, scope):
    ch = w.challenge(p, scope)
    return w.approve(p, scope, ch["nonce"], ch["confirmation"], "TEST FIXTURE ONLY", NOTE, reviewed=True)


def prepare(w):
    p = w.create("Synthetic integration fixture", "How do generated x and y associate?", synthetic=True)["project_id"]
    text = "x,y\n" + "".join(f"{i/10},{2+i/20+(i%3)*.07}\n" for i in range(80))
    w.import_data(p, "synthetic.csv", text.encode(), cloud_consent=True)
    w.measurement(p, w.snapshot(p)["codebook"], {}, "TEST FIXTURE ONLY", NOTE)
    source = w.upload_literature(p, "synthetic.md", QUOTE.encode(), cloud_consent=True)
    w.save_reference(p, {"id": "fixture", "title": "Synthetic engineering note", "authors": ["TEST FIXTURE"], "year": "2026", "source": "Synthetic", "url": "https://example.invalid/fixture", "metadata_declaration": {"reviewer": "TEST ONLY", "note": NOTE}, "spans": [{"id": "fixture_span", "path": source["path"], "locator": {"paragraph": 1}, "quote": QUOTE, "claim": "Synthetic engineering only", "status": "supported", "reviewer": "TEST ONLY", "note": NOTE, "permitted_for_model": False}]})
    w.save_protocol(p, {"schema_version": 2, "rq": "Generated association", "inference": "association", "missing": "complete_case", "results_seen_before_freeze": NOTE, "theory": {"contribution": "Engineering only", "competing_explanation": "Known generator", "boundary": "Synthetic", "evidence_ids": ["fixture_span"]}, "models": [{"id": "main", "family": "ols", "role": "primary", "y": "y", "x": ["x"], "covariance": "HC3"}], "exclusions": []})
    brief = w.snapshot(p)["brief"]
    profile = dict(brief["profile"], sources=[{"kind": "official", "url": "https://example.invalid/synthetic-profile", "accessed_at": "2026-10-29", "note": NOTE}])
    w.save_brief(p, {"profile": profile})
    return p


def wait(w, p):
    w._threads[p].join(timeout=45)
    assert not w._busy(p), "Background worker did not stop within test limit"
    return w.snapshot(p)


@pytest.fixture
def workspace(tmp_path):
    return Workspace(tmp_path / "sessions")


def test_empty_state_is_real_not_demo(workspace):
    p = workspace.create("Study", "Question") ["project_id"]
    s = workspace.snapshot(p)
    assert not s["files_ready"] and not s["materials"]["data"]
    assert not any(s["status"]["approvals"].values())
    assert "analysis" not in s["objects"]
    assert s["status"]["budget"]["spent"] == 0


def test_session_ownership_and_paths(workspace):
    p = workspace.create("Study", "Question")["project_id"]
    other = Workspace(workspace.directory.parent)
    with pytest.raises(EngineError): other.snapshot(p)
    for value in ("../private", "/etc/passwd", "a" * 31, "G" * 32):
        with pytest.raises(EngineError): workspace.snapshot(value)


def test_cloud_consent_before_writes(tmp_path):
    w = Workspace(tmp_path / "sessions", deployment="cloud")
    p = w.create("Cloud", "Question")["project_id"]
    before = set(w._path(p).rglob("*"))
    with pytest.raises(EngineError): w.import_data(p, "test.csv", b"x,y\n1,2\n")
    with pytest.raises(EngineError): w.upload_literature(p, "test.txt", b"research")
    assert set(w._path(p).rglob("*")) == before


def test_csv_original_counts_and_leading_zeros(workspace):
    p = workspace.create("Study", "Question")["project_id"]
    content = b"respondent_id,x\n001,1\n002,2\n"
    record = workspace.import_data(p, "input.csv", content)
    assert workspace._path(p).joinpath(record["original_path"]).read_bytes() == content
    s = workspace.snapshot(p)
    assert record["records"] == 2 and record["fields"] == 2
    assert s["codebook"]["columns"]["respondent_id"]["type"] == "id"
    assert "001" in workspace._path(p).joinpath(record["source_csv"]).read_text()


@pytest.mark.parametrize("content", [b"x,x\n1,2\n", b"x,y\n1,2,3\n", b"x,y\n", b"x,y\n1,2\n3\n"])
def test_bad_csv_never_adopted(workspace, content):
    p = workspace.create("Study", "Question")["project_id"]
    with pytest.raises(EngineError): workspace.import_data(p, "bad.csv", content)
    assert not workspace.snapshot(p)["files_ready"]


def test_dta_numeric_labels_preserved_without_applying_values(tmp_path):
    import pandas as pd
    import pyreadstat
    path = tmp_path / "labels.dta"
    pyreadstat.write_dta(pd.DataFrame({"q": [1., 2., 1.]}), str(path), column_labels={"q": "Original item wording"}, variable_value_labels={"q": {1: "Yes", 2: "No"}})
    result = read_upload(path)
    assert result["book"]["columns"]["q"]["type"] == "number"
    assert result["book"]["columns"]["q"]["question"] == "Original item wording"
    assert result["book"]["columns"]["q"]["value_labels"] == {"1": "Yes", "2": "No"}
    assert result["rows"][0] == ["1.0"]


def test_explicit_missing_and_sensitive_exclusion(workspace):
    p = workspace.create("Study", "Question")["project_id"]
    content = b"name,x\nAlice,1\nBob,99\nCarol,3\n"
    record = workspace.import_data(p, "input.csv", content)
    book = workspace.snapshot(p)["codebook"]
    with pytest.raises(EngineError): workspace.measurement(p, book, {}, "TEST", NOTE)
    del book["columns"]["name"]
    book["columns"]["x"].update(min=1, max=3)
    result = workspace.measurement(p, book, {"x": ["99"]}, "TEST", NOTE)
    assert result["retained_records"] == 3 and result["excluded_columns"] == ["name"]
    s = workspace.snapshot(p)
    assert s["measurement_reviewed"]
    assert "99" not in workspace._path(p).joinpath(s["brief"]["data"]["csv"]).read_text()
    assert workspace._path(p).joinpath(record["original_path"]).read_bytes() == content


def test_legacy_missing_rules_are_restored_only_for_the_reviewed_dataset(workspace):
    p = workspace.create("Synthetic legacy rules", "Do not reuse rules across datasets", synthetic=True)["project_id"]
    workspace.import_data(p, "old.csv", b"x,y\n1,2\n99,3\n")
    book = workspace.snapshot(p)["codebook"]
    workspace.measurement(p, book, {"x": ["99"]}, "TEST FIXTURE ONLY", NOTE)
    with workspace._store(p) as store:
        brief = workspace.snapshot(p)["brief"]
        # Emulate a legacy project that recorded rules in its declaration only.
        workspace._path(p).joinpath(brief["data"]["codebook"]).with_name("missing_codes.json").unlink()
        with store.tx():
            store.set_meta("measurement_review", workspace._measurement_hash(store.root, brief))
    assert workspace.snapshot(p)["missing_codes"] == {"x": ["99"]}
    workspace.import_data(p, "new.csv", b"x,y\n99,1\n100,2\n")
    current = workspace.snapshot(p)
    assert not current["measurement_reviewed"]
    assert current["missing_codes"] == {}


def test_review_is_snapshot_bound_single_use_and_not_automatic(workspace):
    p = prepare(workspace)
    ch = workspace.challenge(p, "authorization")
    with pytest.raises(EngineError): workspace.approve(p, "authorization", ch["nonce"], ch["confirmation"], "TEST", NOTE)
    workspace.save_brief(p, {"theme": "Updated question"})
    with pytest.raises(EngineError): workspace.approve(p, "authorization", ch["nonce"], ch["confirmation"], "TEST", NOTE, True)
    ch = workspace.challenge(p, "authorization")
    workspace.approve(p, "authorization", ch["nonce"], ch["confirmation"], "TEST", NOTE, True)
    with pytest.raises(EngineError): workspace.approve(p, "authorization", ch["nonce"], ch["confirmation"], "TEST", NOTE, True)


def test_session_key_no_server_environment_fallback(workspace, monkeypatch):
    from cra_engine.models import ModelAdapter
    p = prepare(workspace)
    brief = workspace.snapshot(p)["brief"]
    model = dict(brief["model"], base_url="https://example.invalid/v1", model="fixture", input_per_million=1, output_per_million=2)
    workspace.save_brief(p, {"model": model, "permissions": {"model": True, "literature_network": False, "allowed_hosts": ["example.invalid"]}, "limits": dict(brief["limits"], max_cost=1)})
    approve(workspace, p, "authorization")
    monkeypatch.setenv("CRA_API_KEY", "SERVER-SECRET-NOT-A-USER-KEY")
    with workspace._store(p) as store:
        with pytest.raises(EngineError): ModelAdapter(store)._call("unit", [{"role": "user", "content": "fixture"}])
        assert store.budget()["calls"] == 0
    workspace.set_key(p, "USER-SECRET-SENTINEL")
    assert workspace.snapshot(p)["has_session_key"]
    for path in workspace._path(p).rglob("*"):
        if path.is_file(): assert b"USER-SECRET-SENTINEL" not in path.read_bytes()
    workspace.save_brief(p, {"model": dict(model, model="other")})
    assert not workspace.snapshot(p)["has_session_key"]


def test_key_expiry_and_mismatch(monkeypatch):
    import cra_workspace.security as module
    clock = [100.]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    vault = Credentials()
    vault.put("p", "version", "sentinel", 10)
    assert vault.get("p", "version") == "sentinel"
    clock[0] = 111
    assert vault.get("p", "version") is None
    vault.put("p", "version", "sentinel")
    assert vault.get("p", "changed") is None


def test_backup_restore_no_key_no_inherited_approval(workspace):
    p = prepare(workspace)
    approve(workspace, p, "authorization")
    with pytest.raises(EngineError): workspace.backup(p)
    blob = workspace.backup(p, True)["bytes"]
    restored = workspace.restore(blob)["project_id"]
    s = workspace.snapshot(restored)
    assert s["materials"]["data"][-1]["records"] == 80
    assert not s["status"]["approvals"]["authorization"]
    assert s["status"]["paused"] and not s["has_session_key"]
    assert workspace.snapshot(p)["status"]["approvals"]["authorization"]


@pytest.mark.parametrize("path", ["../escape", "/tmp/escape", "folder/../../escape", "folder\\escape"])
def test_recovery_traversal_refused(workspace, path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("cra-recovery.json", '{"format":1,"schema_version":2}')
        z.writestr(path, "untrusted")
    before = workspace.projects()
    with pytest.raises(EngineError): workspace.restore(stream.getvalue())
    assert workspace.projects() == before


def test_event_polling_concurrent_commits(workspace):
    p = prepare(workspace)
    errors = []
    def writer():
        try:
            with workspace._store(p) as store:
                for i in range(80):
                    with store.tx(): store.event("concurrent_fixture", {"i": i})
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=writer)
    thread.start()
    for _ in range(30):
        with workspace._store(p) as store: store.verify_events()
    thread.join()
    assert not errors


def test_local_sessions_observe_running_lease_and_cannot_edit(workspace):
    p = prepare(workspace)
    other = Workspace(workspace.directory.parent, owner=workspace.directory.name)
    with workspace._store(p) as store:
        with store.tx(): store.db.execute("INSERT INTO leases VALUES ('workspace','synthetic-supervisor',?, 'TEST')", (os.getpid(),))
    try:
        assert other.running(p)
        assert other.snapshot(p)["running"]
        with pytest.raises(EngineError): other.save_brief(p, {"theme": "Must not race the worker"})
        assert other.snapshot(p)["brief"]["theme"] == "How do generated x and y associate?"
    finally:
        with workspace._store(p) as store:
            with store.tx(): store.db.execute("DELETE FROM leases WHERE name='workspace'")


def test_failed_thread_start_releases_supervisor_lease(workspace, monkeypatch):
    p = prepare(workspace)
    approve(workspace, p, "authorization")
    def fail(_): raise RuntimeError("SYNTHETIC thread-start failure")
    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(RuntimeError): workspace.start(p)
    assert not workspace.running(p)
    assert workspace.snapshot(p)["job"]["state"] == "failed"


def test_reproduction_is_visible_to_other_sessions_and_releases_after_failure(workspace, monkeypatch):
    from cra_engine import cli
    p = workspace.create("Synthetic reproduction concurrency", "Protect reproduction inputs", synthetic=True)["project_id"]
    other = Workspace(workspace.directory.parent, owner=workspace.directory.name)
    for fail in (False, True):
        def controlled_reproduction(store):
            assert other.running(p)
            with pytest.raises(EngineError, match="正在执行"):
                other.save_brief(p, {"theme": "Must not change during reproduction"})
            assert other.snapshot(p)["brief"]["theme"] == "Protect reproduction inputs"
            if fail:
                raise EngineError("SYNTHETIC reproduction failure")
            return {"passed": True}
        monkeypatch.setattr(cli, "reproduce", controlled_reproduction)
        if fail:
            with pytest.raises(EngineError, match="SYNTHETIC reproduction failure"):
                workspace.reproduce(p)
        else:
            assert workspace.reproduce(p) == {"passed": True}
        assert not other.running(p)
        with workspace._store(p) as store:
            assert not store.db.execute("SELECT 1 FROM leases").fetchone()
    other.save_brief(p, {"objective": "Editing is available after reproduction stops"})
    assert workspace.snapshot(p)["brief"]["objective"] == "Editing is available after reproduction stops"


def test_bad_evidence_never_saved(workspace):
    p = prepare(workspace)
    reference = workspace.references(p)[0]
    reference["spans"][0]["quote"] = "This quotation does not exist anywhere"
    with pytest.raises(EngineError): workspace.save_reference(p, reference)
    assert workspace.references(p)[0]["spans"][0]["quote"] == QUOTE


def test_environment_check_reports_configured_remote_worker_without_changing_project_scope(workspace, monkeypatch):
    from cra_workspace import environment

    class RemoteFixture:
        endpoint = "https://worker.example.invalid"
        def __init__(self): self.calls = 0
        def health(self):
            self.calls += 1
            return {"passed": True, "isolation": "linux-bubblewrap", "controls": {
                "network_denied": True, "write_denied": True, "control_read_denied": True},
                "identity": {"protocol": 1, "recipe": "SYNTHETIC"}}

    remote = RemoteFixture()
    workspace.remote_executor = remote
    monkeypatch.setattr(environment, "inspect_environment", lambda store: {
        "passed": False, "message": "SYNTHETIC local sandbox unavailable"})
    p = workspace.create("Synthetic worker health fixture", "No research data is transferred", synthetic=True)["project_id"]

    report = workspace.check_environment(p)

    assert report["passed"] is False
    assert report["remote_worker_check"]["passed"] is True
    assert report["remote_worker_check"]["isolation"] == "linux-bubblewrap"
    assert remote.calls == 1
    assert workspace.snapshot(p)["brief"].get("execution", {"backend": "local"}) == {"backend": "local"}


def test_environment_check_reports_remote_failure_without_sending_project_data(workspace, monkeypatch):
    from cra_engine.common import EngineError
    from cra_workspace import environment

    class RemoteFixture:
        endpoint = "https://worker.example.invalid"
        def health(self): raise EngineError("SYNTHETIC health failure")

    workspace.remote_executor = RemoteFixture()
    monkeypatch.setattr(environment, "inspect_environment", lambda store: {
        "passed": False, "message": "SYNTHETIC local sandbox unavailable"})
    p = workspace.create("Synthetic failed worker fixture", "No research data is transferred", synthetic=True)["project_id"]

    report = workspace.check_environment(p)

    assert report["remote_worker_check"]["passed"] is False
    assert "没有发送研究材料" in report["remote_worker_check"]["message"]
    assert workspace.snapshot(p)["brief"].get("execution", {"backend": "local"}) == {"backend": "local"}


@pytest.mark.skipif(os.environ.get("CRA_ISOLATION_TESTS") != "1", reason="Explicit real OS isolation integration opt-in")
def test_real_worker_end_to_end_and_export(workspace):
    p = prepare(workspace)
    with pytest.raises(EngineError): workspace.start(p)
    environment = workspace.check_environment(p)
    assert environment["passed"] and environment["controls"] == {"network_denied": True, "write_denied": True, "control_read_denied": True}
    approve(workspace, p, "authorization")
    workspace.start(p)
    s = wait(workspace, p)
    assert s["objects"]["audit"]["value"]["sample_flow"]["input_rows"] == 80
    assert s["objects"]["protocol"]["value"]["rq"] == "Generated association"
    assert "analysis" not in s["objects"]
    approve(workspace, p, "protocol")
    workspace.start(p)
    s = wait(workspace, p)
    assert s["objects"]["analysis"]["value"]["models"][0]["n"] == 80
    assert s["status"]["last_problem"]
    workspace.save_narrative(p, {"introduction": "Synthetic engineering materials only. [[cite:fixture]]", "theory": "This note tests a software workflow. [[cite:fixture]]", "discussion": "The generated association is {{claim:main_b1}}. It is not evidence about real respondents.", "limitations": "Synthetic data cannot establish measurement validity or population representation."})
    workspace.start(p)
    s = wait(workspace, p)
    assert s["status"]["last_problem"] is None
    assert not s["status"]["complete"]
    assert workspace.reproduce(p)["passed"]
    bundle = workspace.export(p)
    with zipfile.ZipFile(io.BytesIO(bundle["bytes"])) as z:
        assert any(n.endswith("manuscript.docx") for n in z.namelist())
        assert not any(n.endswith("input.csv") for n in z.namelist())
    with pytest.raises(EngineError): workspace.export(p, "final")
    approve(workspace, p, "final")
    assert workspace.snapshot(p)["status"]["complete"]
    assert workspace.export(p, "final")["bytes"].startswith(b"PK")
    workspace.import_data(p, "changed.csv", b"x,y\n1,2\n2,3\n")
    s = workspace.snapshot(p)
    assert not s["status"]["complete"] and s["objects"]["analysis"]["stale"]
