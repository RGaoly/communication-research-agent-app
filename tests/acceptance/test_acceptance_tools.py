import base64
import datetime
import json
from pathlib import Path
import zipfile

import pytest

from cra_engine.common import EngineError, digest, dumps, load, save
from cra_engine.evidence_bundle import verify_signature, verify_bundle
from cra_engine.package_check import verify_package
from cra_engine.store import initialize, Store
from cra_acceptance.live import price, peak, smoke
from cra_acceptance.numerics import run as numeric_run
from cra_acceptance.cli import prepare


def test_independent_thirty_numerical_cases(tmp_path):
    report = numeric_run(tmp_path)
    assert len(report["cases"]) == 30
    assert all(c["status"] == "passed" and c["sample_match"] for c in report["cases"])


def test_unknown_usage_and_reasoning_are_not_double_charged():
    instant = datetime.datetime(2026, 10, 28, 0, tzinfo=datetime.timezone.utc)
    usage = {"prompt_tokens": 100, "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20, "completion_tokens": 50, "completion_tokens_details": {"reasoning_tokens": 40}}
    result = price(usage, instant, instant)
    assert result["estimated_usd"] == pytest.approx((80*.003+20*.15+50*.60)/1e6)
    assert price(usage, instant, instant.replace(hour=1))["estimated_usd"] == pytest.approx(result["estimated_usd"]*2)
    with pytest.raises(EngineError): price({}, instant, instant)
    usage["prompt_cache_hit_tokens"] = 90
    with pytest.raises(EngineError): price(usage, instant, instant)


@pytest.mark.parametrize("hour,minute,weekday_peak", [(0,59,False),(1,0,True),(3,59,True),(4,0,False),(5,59,False),(6,0,True),(9,59,True),(10,0,False)])
def test_price_period_boundaries(hour, minute, weekday_peak):
    value = datetime.datetime(2026,10,28,hour,minute,tzinfo=datetime.timezone.utc)
    assert peak(value) == weekday_peak
    assert not peak(value.replace(day=31))


def test_smoke_without_key_sends_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("CRA_API_KEY", raising=False)
    with pytest.raises(EngineError, match="unavailable"): smoke(tmp_path)
    assert not (tmp_path/"smoke-ledger.json").exists()


def test_calibration_templates_never_claim_holdout_or_pilots(tmp_path):
    root = tmp_path/"materials"
    prepare(root)
    report = load(root/"literature-calibration-100.json")
    assert len(report["cases"]) == 100
    assert all(c["synthetic"] and not c["independent_holdout"] for c in report["cases"])
    assert all(c["status"] == "pending" for c in load(root/"pilots-template.json")["cases"])
    with pytest.raises(EngineError): prepare(root)


def test_unsigned_and_self_asserted_evidence_cannot_release(tmp_path):
    save(tmp_path/"manifest.json", {"schema_version":1,"files":{}})
    result = verify_bundle(tmp_path)
    assert not result["bundle_valid"] and not result["release_eligible"]


def test_signatures_bind_reviewer_role_and_exact_evidence():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()  # Synthetic test key, never a real reviewer.
    trust = {"reviewers": {"TEST ONLY": {"public_key_pem": key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode(), "roles": ["method_reviewer"], "independent": True}}}
    payload = {"subject_sha256":"a"*64,"candidate_wheel_sha256":"b"*64,"role":"method_reviewer","decision":"pass","reviewed_at":"2026-10-28","note":"Synthetic test signature only"}
    statement = {"signer_id":"TEST ONLY","payload":payload,"signature":base64.b64encode(key.sign(dumps(payload).encode())).decode()}
    assert verify_signature(statement, trust, "a"*64, "b"*64, "method_reviewer") == "TEST ONLY"
    with pytest.raises(EngineError): verify_signature(statement, trust, "c"*64, "b"*64, "method_reviewer")
    with pytest.raises(EngineError): verify_signature(statement, trust, "a"*64, "b"*64, "research_owner")
    statement["payload"]["note"] = "Tampered signature"
    with pytest.raises(EngineError): verify_signature(statement, trust, "a"*64, "b"*64, "method_reviewer")


def test_diagnostic_handoff_without_research_approval(tmp_path):
    from cra_engine.exporting import export_diagnostic
    root = tmp_path/"project"; initialize(root, synthetic=True)
    store = Store(root)
    try:
        result = export_diagnostic(store)
        assert verify_package(result["archive"])["passed"]
        assert not load(Path(result["directory"])/"diagnostic.json")["research_completed"]
        assert store.db.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    finally: store.close()


@pytest.mark.parametrize("name", ["../outside", "/absolute", "bad\\path"])
def test_zip_path_traversal_is_refused(tmp_path, name):
    path = tmp_path/"unsafe.zip"
    with zipfile.ZipFile(path,"w") as archive: archive.writestr(name,"unsafe")
    assert not verify_package(path)["passed"]


def test_paid_response_checkpoint_survives_reopen(tmp_path):
    root = tmp_path/"project"; initialize(root,synthetic=True)
    store = Store(root)
    with store.tx(): store.put("brief","brief",{"limits":{"max_cost":1}})
    call = store.reserve("writer", .1, "fixture")
    store.settle(call, .02, checkpoint={"account":"writer","request_hash":"request","message":{"content":"saved"},"delivery_run":"run1"})
    store.close(); store = Store(root)
    with store.lease():
        assert store.pending_response("writer","request") == {"content":"saved"}
        assert store.budget()["calls"] == 1 and store.budget()["reserved"] == 0
        with store.tx(): store.consume_responses("writer")
        assert store.pending_response("writer","request") is None
    store.close()


def test_known_but_uncertain_cost_is_not_reserved_twice(tmp_path):
    root=tmp_path/"project"; initialize(root,synthetic=True); store=Store(root)
    with store.tx(): store.put("brief","brief",{"limits":{"max_cost":1}})
    call=store.reserve("test",.1,"fixture"); store.settle(call,.02,uncertain=True)
    assert store.budget()["spent"] == .02 and store.budget()["reserved"] == 0
    with pytest.raises(EngineError): store.reserve("test",.1,"fixture")
    store.close()


def test_expert_scores_keep_denominator_uncertainty_and_severe_error_gate():
    from cra_acceptance.scoring import literature_score
    cases=[{"id":str(i),"core_claim":True,"predicted_support":"supported","adjudicated_support":"supported","expert_ratings":[{"reviewer":name,"support":"supported","note":"Synthetic scoring fixture only"} for name in ("TEST A","TEST B")]} for i in range(100)]
    report=literature_score(cases)
    assert report["passed"] and report["n"]==100 and report["wilson_95"][0]<1
    cases[0]["adjudicated_support"]="unsupported"
    for rating in cases[0]["expert_ratings"]:rating["support"]="unsupported"
    report=literature_score(cases)
    assert report["accuracy"]==.99 and not report["passed"] and report["severe_core_misquotes"]==1


def test_expert_disagreements_require_adjudication():
    from cra_acceptance.scoring import literature_score
    case={"id":"test","predicted_support":"supported","adjudicated_support":"supported","expert_ratings":[{"reviewer":"TEST A","support":"supported","note":"Synthetic scoring fixture"},{"reviewer":"TEST B","support":"unsupported","note":"Synthetic scoring fixture"}]}
    with pytest.raises(EngineError,match="adjudication"):literature_score([case])


def test_operator_signature_subject_changes_when_raw_observations_change():
    from cra_engine.evidence_bundle import observations_hash
    original={"candidate.json":"candidate","statistics/result.json":"correct","manual-cli-results.json":"review"}
    changed=dict(original);changed["statistics/result.json"]="tampered"
    assert observations_hash(original)!=observations_hash(changed)
    changed=dict(original);changed["manual-cli-results.json"]="new-review"
    assert observations_hash(original)==observations_hash(changed)
