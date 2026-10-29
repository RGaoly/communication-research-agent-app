"""Explicitly synthetic engineering inputs. These are never real pilot evidence."""
from pathlib import Path
from cra_engine.common import save, atomic, load
from cra_engine.store import initialize
from .numerics import dataset


def prepare(root):
    root = Path(root)
    initialize(root, "SYNTHETIC acceptance fixture", synthetic=True)
    dataset(root/"data", 0)
    brief = load(root/"brief.json")
    brief.update(theme="Synthetic media association", objective="Engineering verification only", language="en")
    brief["profile"]["sources"] = [{"kind": "official", "url": "https://apastyle.apa.org", "accessed_at": "2026-10-28"}]
    save(root/"brief.json", brief)
    quote = "This is a synthetic engineering source, not evidence about communication research."
    atomic(root/"literature/source.md", quote+"\n")
    save(root/"literature/references.json", [{"id": "fixture", "title": "Synthetic source", "authors": ["Fixture"], "year": "2026", "source": "Engineering fixture", "url": "https://example.invalid/fixture", "metadata_declaration": {"reviewer": "TEST ONLY", "note": "Synthetic fixture metadata; no academic review"}, "spans": [{"id": "span_fixture", "path": "literature/source.md", "locator": {"paragraph": 1}, "quote": quote, "claim": "This is a synthetic source", "status": "supported", "reviewer": "TEST ONLY", "note": "Synthetic local source only; not a real source review", "permitted_for_model": True}]}])
    plan = {"schema_version": 2, "rq": "What synthetic association is present?", "inference": "association", "missing": "complete_case", "results_seen_before_freeze": "Known synthetic generating process; not preregistration", "theory": {"contribution": "Engineering fixture only", "competing_explanation": "Known generating process", "boundary": "No real respondents", "evidence_ids": ["span_fixture"]}, "candidates": [], "models": [{"id": "main", "family": "ols", "role": "primary", "y": "y", "x": ["x", "z"], "covariance": "HC3"}], "exclusions": []}
    save(root/"protocol/plan.json", plan)
    save(root/"manuscript/narrative.json", {"introduction": "Engineering demonstration only. [[cite:fixture]]", "theory": "Synthetic materials cannot establish a theoretical contribution. [[cite:fixture]]", "discussion": "{{claim:main_b1}} Association does not identify a causal effect.", "limitations": "Synthetic observations; no validity or population claims."})
    return root


def fixture_approval(store, scope):
    # Component fixture only. Never counted as a human-operated CLI or pilot approval.
    store.approve(scope, "TEST FIXTURE ONLY", "Synthetic engineering setup; never a human research acceptance", "APPROVE "+store.snapshot(scope)[:12])
