import importlib.util
from pathlib import Path

import pytest

from cra_engine.common import load, save
from cra_engine.store import Store

spec = importlib.util.spec_from_file_location("engine_demo", Path(__file__).resolve().parents[2] / "examples/run_engine_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_approval(store, scope):
    # Test fixture only; production CLI requires interactive human confirmation.
    store.approve(scope, "TEST ONLY", "Synthetic fixture assertion; no research approval", "APPROVE " + store.snapshot(scope)[:12])


@pytest.fixture
def project(tmp_path):
    root = demo.prepare(tmp_path.resolve() / "study")
    store = Store(root)
    yield store
    store.close()


@pytest.fixture
def local_recipes(monkeypatch):
    """Unit-test double only. Production has no bypass flag or unsafe fallback."""
    from cra_engine import runtime
    from cra_engine.statistics import audit, fit_models
    def execute(store, action, payload, inputs=(), timeout=300):
        result = {"audit": audit, "analysis": fit_models}[action](**payload)
        return {"result": result, "isolation": "UNIT TEST DOUBLE"}
    monkeypatch.setattr(runtime, "execute", execute)
    monkeypatch.setattr(runtime, "doctor", lambda _: {"test_double": True})


@pytest.fixture
def prepared(project):
    from cra_engine.runtime import plan
    plan(project)
    test_approval(project, "authorization")
    return project


@pytest.fixture
def completed(prepared, local_recipes):
    from cra_engine.runtime import run
    run(prepared)
    test_approval(prepared, "protocol")
    run(prepared)
    test_approval(prepared, "final")
    return prepared
