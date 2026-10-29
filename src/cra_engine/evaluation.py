"""Explicit release gate. Synthetic tests can never stand in for real pilot reviews."""
from pathlib import Path
from .common import load, require, sha
from .runtime import readiness, sync


def release_check(store, registry=None, software_report=None, acceptance_bundle=None, trust_store=None):
    sync(store)
    pilots = load(registry) if registry else []
    require(isinstance(pilots, list), "Pilot registry must be a list")
    accepted, rejected = [], []
    ids = set()
    for pilot in pilots:
        ident = pilot.get("project_id")
        valid = isinstance(ident, str) and ident and ident not in ids and pilot.get("synthetic") is False and pilot.get("data_authorized") is True
        for role in ("research_owner", "method_reviewer"):
            review = pilot.get(role, {})
            valid = valid and review.get("decision") == "pass" and bool(review.get("reviewer")) and len(review.get("note", "")) >= 8
        valid = valid and isinstance(pilot.get("evidence_package_hash"), str) and len(pilot["evidence_package_hash"]) == 64
        (accepted if valid else rejected).append(ident)
        ids.add(ident)
    blockers = []
    from .evidence_bundle import verify_bundle
    acceptance = verify_bundle(acceptance_bundle, trust_store) if acceptance_bundle else {"release_eligible": False, "problems": ["Acceptance bundle missing"]}
    if not acceptance["release_eligible"]:
        blockers.append("Hash-bound acceptance observations, independent signed reviews and real pilot packages are required; caller pass declarations do not suffice")
    software_passed = acceptance.get("software_evidence_passed") is True
    if software_report:
        # A separate caller-provided summary cannot replace the signed bundle subject.
        bound = Path(acceptance_bundle) / "reports/software.json" if acceptance_bundle else None
        software_passed = software_passed and bound is not None and bound.is_file() and sha(software_report) == sha(bound)
    if not software_passed:
        blockers.append("Raw JUnit regression evidence with every frozen case, no skips/failures, and matching source must be bound to the acceptance bundle and operator review")
    if len(accepted) < 3:
        blockers.append("Three authorized non-synthetic pilots with research-owner and method-reviewer declarations are required")
    if not readiness(store)["ready_for_final"] or not store.approved("final"):
        blockers.append("Current project has unresolved evidence or lacks final human approval")
    if store.meta("synthetic"):
        blockers.append("This project is synthetic; it is an engineering example, not a real pilot")
    # Research-quality/performance targets require actual measurements, not model self-ratings.
    if not all(p.get("independent_reproduction_passed") is True and p.get("expert_support_check_passed") is True for p in pilots if p.get("project_id") in accepted):
        blockers.append("Independent reproduction and expert evidence checks must be documented for each accepted pilot")
    return {"release_eligible": not blockers, "software_evidence_passed": software_passed, "acceptance": acceptance, "accepted_pilots": accepted, "rejected_pilots": rejected, "blockers": blockers,
            "limits": "Registry entries are human declarations, not authenticated research certification. Software CI and performance target evaluation remain independent release evidence."}
