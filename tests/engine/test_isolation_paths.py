"""Real OS workers on synthetic data; no approvals or paid model requests."""
import os
import socket

import pytest

from cra_engine.common import EngineError, safe_text
from cra_engine.isolation import doctor, execute
from cra_engine.store import Store
from conftest import demo


@pytest.mark.skipif(os.environ.get("CRA_ISOLATION_TESTS") != "1", reason="Real OS isolation must be explicitly enabled")
@pytest.mark.parametrize("folder", ["ascii-study", '中文研究 space "复核"'])
def test_actual_worker_reads_authorized_paths_without_control_access(tmp_path, folder):
    root = demo.prepare(tmp_path.resolve() / folder)
    store = Store(root)
    try:
        probe = doctor(store)
        assert probe["result"] == {"network_denied": True, "write_denied": True, "control_read_denied": True}
        csv_path, book_path = root / "data/input.csv", root / "data/codebook.json"
        result = execute(store, "audit", {"csv_path": str(csv_path), "book_path": str(book_path)}, [csv_path, book_path])
        assert result["result"]["sample_flow"]["input_rows"] == 160
        assert not (root / "isolation-escape-test").exists()
    finally:
        store.close()


def test_sensitive_identifiers_after_prose_period_are_not_hidden():
    # Deliberately synthetic sentinels; no real participant values.
    for text in ("TEST phone.13812345678", "TEST ID.110101199001010017"):
        with pytest.raises(EngineError, match="Possible sensitive"):
            safe_text(text)


def test_long_fractional_results_are_not_identifiers():
    safe_text({"estimate": 0.123456789012345678, "se": -0.13812345678})


def test_network_probe_does_not_call_a_live_host_listener_isolated():
    from cra_engine.worker import network_denied
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(2)
        assert network_denied(listener.getsockname()[1]) is False
