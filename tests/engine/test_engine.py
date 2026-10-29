import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from cra_engine.common import EngineError, digest, load, save, sha
from cra_engine.runtime import plan, readiness, run, status, sync
from cra_engine.store import Store, initialize
from conftest import demo, test_approval as approve_fixture


def test_project_refuses_overwrite_and_unknown_version(project):
    with pytest.raises(EngineError):
        initialize(project.root)
    manifest = load(project.root / "project.json")
    save(project.root / "project.json", dict(manifest, schema_version=999))
    with pytest.raises(EngineError):
        Store(project.root)


def test_plan_has_all_inputs_acceptance_limits_and_no_execution(project):
    value = plan(project)
    assert len(value["tasks"]) == 8
    assert all(t["acceptance"] and t["resource_limit"] and "inputs" in t and t["failure"] for t in value["tasks"])
    assert all(t["status"] == "pending" for t in project.task_rows())
    assert project.budget()["calls"] == 0


def test_no_authorization_no_execution(project, local_recipes):
    plan(project)
    with pytest.raises(EngineError, match="authorization"):
        run(project)


def test_protocol_gate_and_full_offline_loop(prepared, local_recipes):
    first = run(prepared)
    assert first["approvals"]["authorization"]
    assert not first["approvals"]["protocol"]
    assert prepared.get("analysis") is None
    assert next(t for t in first["tasks"] if t["id"] == "analysis")["status"] == "waiting_human"
    approve_fixture(prepared, "protocol")
    second = run(prepared)
    assert second["readiness"]["ready_for_final"]
    assert not second["complete"]
    approve_fixture(prepared, "final")
    assert status(prepared)["complete"]
    assert prepared.get("analysis")["models"][0]["n"] == 160


def test_unrelated_file_does_not_invalidate(completed):
    (completed.root / "personal-note.txt").write_text("unrelated")
    sync(completed)
    assert completed.approved("protocol") and completed.approved("final")


def test_narrative_only_change_preserves_analysis_and_freeze(completed):
    before = completed.object_hash("analysis")
    value = load(completed.root / "manuscript/narrative.json")
    value["limitations"] += " 此处补充适用范围。"
    save(completed.root / "manuscript/narrative.json", value)
    sync(completed)
    assert completed.object_hash("analysis") == before
    assert completed.approved("protocol")
    assert not completed.approved("final")
    assert completed.object_hash("draft") is None


def test_data_changes_invalidate_dependent_evidence(completed):
    path = completed.root / "data/input.csv"
    path.write_text(path.read_text().replace("S000", "S900"))
    sync(completed)
    assert completed.approved("authorization")
    assert not completed.approved("protocol")
    assert completed.object_hash("analysis") is None
    assert completed.object_hash("corpus") is not None


def test_protocol_change_requires_new_freeze(completed):
    value = load(completed.root / "protocol/plan.json")
    value["models"][0]["covariance"] = "classical"
    save(completed.root / "protocol/plan.json", value)
    sync(completed)
    assert not completed.approved("protocol")
    assert not completed.approved("final")


def test_changed_permissions_invalidate_authorization(completed):
    brief = load(completed.root / "brief.json")
    brief["limits"]["max_cost"] = 10
    save(completed.root / "brief.json", brief)
    sync(completed)
    assert not completed.approved("authorization")


def test_output_tampering_is_not_adopted(completed):
    path = completed.root / "artifacts/analysis.json"
    value = load(path)
    value["models"][0]["n"] = 1
    save(path, value)
    sync(completed)
    assert completed.object_hash("analysis") is None
    assert not completed.approved("final")


def test_unchanged_resume_reuses_results(completed, local_recipes):
    attempts = {t["id"]: t["attempts"] for t in completed.task_rows()}
    run(completed)
    assert attempts == {t["id"]: t["attempts"] for t in completed.task_rows()}


def test_missing_evidence_stops_before_statistics(prepared, local_recipes):
    refs = load(prepared.root / "literature/references.json")
    refs[0]["spans"][0]["status"] = "pending"
    save(prepared.root / "literature/references.json", refs)
    value = run(prepared)
    assert prepared.get("analysis") is None
    assert value["last_problem"]["task"] == "protocol"


def test_duplicate_respondents_stop_without_deleting(prepared, local_recipes):
    path = prepared.root / "data/input.csv"
    path.write_text(path.read_text().replace("S001", "S000"))
    before = path.read_bytes()
    value = run(prepared)
    assert value["last_problem"]["task"] == "audit"
    assert before == path.read_bytes()
    assert prepared.get("analysis") is None


def test_repeated_error_is_bounded_and_change_recovers(prepared, local_recipes):
    path = prepared.root / "data/input.csv"
    original = path.read_text()
    path.write_text(original.replace("S001", "S000"))
    run(prepared); run(prepared)
    row = next(t for t in prepared.task_rows() if t["id"] == "audit")
    assert row["error_count"] == 2
    run(prepared)
    assert next(t for t in prepared.task_rows() if t["id"] == "audit")["attempts"] == 2
    path.write_text(original)
    run(prepared)
    assert prepared.object_hash("audit")


def test_pause_persists_and_resume_is_explicit(prepared):
    with prepared.tx():
        prepared.set_meta("paused", True)
    assert status(prepared)["paused"]


def test_active_lease_prevents_second_runner(prepared):
    with prepared.lease():
        other = Store(prepared.root)
        try:
            with pytest.raises(EngineError):
                with other.lease():
                    pass
        finally:
            other.close()


def test_dead_lease_recovers_task_and_marks_call_uncertain(prepared):
    brief = prepared.get("brief")
    brief["limits"]["max_cost"] = 1
    with prepared.tx():
        prepared.put("brief", "research_brief", brief)
        prepared.db.execute("INSERT INTO leases VALUES ('run','dead',99999999,'test')")
        prepared.db.execute("UPDATE tasks SET status='running' WHERE id='audit'")
    call = prepared.reserve("test", 0.1, "fixture")
    with prepared.lease():
        assert next(t for t in prepared.task_rows() if t["id"] == "audit")["status"] == "ready"
        assert prepared.budget()["uncertain"] == 1


def test_budget_transaction_and_uncertain_calls(prepared):
    value = prepared.get("brief")
    value["limits"]["max_cost"] = 1
    with prepared.tx():
        prepared.put("brief", "research_brief", value)
    first = prepared.reserve("test", 0.6, "fixture")
    with pytest.raises(EngineError):
        prepared.reserve("test", 0.6, "fixture")
    prepared.settle(first, 0.2, {"prompt_tokens": 1})
    assert prepared.budget()["remaining"] == pytest.approx(0.8)
    second = prepared.reserve("test", 0.1, "fixture")
    prepared.settle(second, None, uncertain=True)
    with pytest.raises(EngineError, match="Uncertain"):
        prepared.reserve("test", 0.1, "fixture")
    prepared.settle(second, 0.02, {"human_reconciled": True})
    assert prepared.budget()["uncertain"] == 0


def test_event_tampering_detected(project):
    project.db.execute("UPDATE events SET action='fake' WHERE seq=1")
    with pytest.raises(EngineError):
        project.verify_events()


def test_transaction_rolls_back_evidence_and_events(project):
    before = project.meta("event_head")
    with pytest.raises(RuntimeError):
        with project.tx():
            project.put("rollback", "test", {"a": 1})
            project.event("should_rollback", {})
            raise RuntimeError()
    assert project.get("rollback") is None
    assert project.meta("event_head") == before


def test_cli_rejects_noninteractive_human_approval(prepared):
    result = subprocess.run([sys.executable, "-m", "cra_engine", "approve", str(prepared.root), "--scope", "authorization", "--reviewer", "not a person", "--note", "noninteractive attempt"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "interactive" in result.stderr


def test_profile_official_source_required_for_final(completed):
    brief = load(completed.root / "brief.json")
    brief["profile"]["sources"] = []
    save(completed.root / "brief.json", brief)
    sync(completed)
    assert any(i["code"] == "official_profile_missing" for i in readiness(completed)["blocking_issues"])


def test_export_refuses_final_without_approval(prepared, local_recipes):
    from cra_engine.exporting import export_package
    run(prepared); approve_fixture(prepared, "protocol"); run(prepared)
    with pytest.raises(EngineError):
        export_package(prepared)
    result = export_package(prepared, working=True)
    assert result["working"]
    assert "未终审" in (Path(result["directory"]) / "manuscript.md").read_text()


def test_export_hash_manifest_no_credentials_or_data_by_default(completed):
    from cra_engine.exporting import export_package
    result = export_package(completed)
    root = Path(result["directory"])
    manifest = load(root / "manifest.json")
    assert not manifest["input_included"] and not (root / "input.csv").exists()
    assert (root / "manuscript.docx").stat().st_size > 10000
    assert (root / "figure.svg").is_file()
    assert (root / "specification-ledger.json").is_file()
    assert all(sha(root / rel) == signature for rel, signature in manifest["files"].items())
    assert not any(p.name in ("state.sqlite", "brief.json") for p in root.rglob("*"))


def test_exported_recipe_rebuilds_without_engine_installation(completed):
    from cra_engine.exporting import export_package
    import zipfile
    from xml.etree import ElementTree as ET
    output=export_package(completed,include_data=True)
    root=Path(output['directory'])
    process=subprocess.run([sys.executable,str(root/'reproduce.py')],capture_output=True,text=True,cwd=root)
    assert process.returncode==0,process.stdout+process.stderr
    assert 'PASS' in process.stdout
    assert load(root/'reproduced.json')['models']==completed.get('analysis')['models']
    circles=ET.fromstring((root/'figure.svg').read_text()).findall('{http://www.w3.org/2000/svg}circle')
    parameters=completed.get('analysis')['models'][0]['parameters']
    assert len(circles)==len(parameters)
    assert [float(p.attrib['data-estimate']) for p in circles]==pytest.approx([p['estimate'] for p in parameters])
    with zipfile.ZipFile(root/'manuscript.docx') as package:
        document=package.read('word/document.xml').decode()
    assert '0.277357' in document
    assert len(load(root/'runs.json'))==8


def test_legacy_dry_run_migration_has_no_changes(tmp_path):
    from cra_engine.migration import legacy_module, migrate
    legacy = legacy_module()
    root = tmp_path.resolve() / "legacy"
    args = legacy.parser().parse_args(["init", str(root), "--synthetic"])
    legacy.initialize(root, args)
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    report = migrate(root, True)
    after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert report["dry_run"] and before == after
    result = migrate(root, False)
    assert Path(result["backup"]).is_dir()
    new = Store(root)
    assert new.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    assert new.get("legacy_history") is not None
    new.close()


@pytest.mark.skipif(os.environ.get("CRA_ISOLATION_TESTS") != "1", reason="Explicit OS isolation integration run required")
def test_real_os_isolation_and_reproduction(tmp_path):
    from cra_engine.cli import reproduce
    from cra_engine.isolation import doctor
    root = demo.prepare(tmp_path.resolve() / "isolated")
    store = Store(root)
    try:
        assert all(doctor(store)["result"].values())
        plan(store); approve_fixture(store, "authorization")
        run(store); approve_fixture(store, "protocol")
        assert run(store)["readiness"]["ready_for_final"]
        assert reproduce(store)["passed"]
    finally:
        store.close()
