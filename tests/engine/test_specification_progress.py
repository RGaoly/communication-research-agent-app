"""A later failed specification must not erase an earlier null result."""
import copy
import csv
import os
import random

import pytest

from cra_engine.common import EngineError, digest, load, save, sha
from cra_engine.statistics import fit_models
from conftest import demo


def prepare_failure(root):
    csv_path, book_path = root / 'data/input.csv', root / 'data/codebook.json'
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    rng = random.Random(19)
    for row in rows:
        row['trust'] = 2 + rng.uniform(-.5, .5)
        row['flat'] = 0
    with csv_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    book = load(book_path)
    book['columns']['flat'] = {'type': 'number', 'sensitive': False, 'min': 0, 'max': 0}
    save(book_path, book)
    plan = demo.protocol()
    good = plan['models'][0]
    bad = dict(copy.deepcopy(good), id='constant_outcome', y='flat', role='robustness')
    after = dict(copy.deepcopy(good), id='not_executed', role='robustness')
    plan['models'] = [good, bad, after]
    return csv_path, book_path, plan


def test_later_failure_preserves_null_result_and_unexecuted_status(project, tmp_path):
    csv_path, book_path, plan = prepare_failure(project.root)
    original_hash = sha(csv_path)
    path = tmp_path / 'specification-progress.json'
    with pytest.raises(EngineError, match='Outcome has no variation'):
        fit_models(csv_path, book_path, plan, progress_path=path)
    progress = load(path)
    assert [e['status'] for e in progress['entries']] == ['succeeded', 'failed', 'not_run']
    assert progress['entries'][1]['id'] == 'constant_outcome'
    assert progress['protocol_hash'] == digest(plan)
    assert [m['id'] for m in progress['completed_models']] == [plan['models'][0]['id']]
    slope = progress['completed_models'][0]['parameters'][1]
    assert slope['p'] > .05 and slope['ci_low'] <= 0 <= slope['ci_high']
    assert progress['research_completed'] is False
    assert sha(csv_path) == original_hash


def test_successful_specification_ledger_is_deterministic(project, tmp_path):
    csv_path, book_path = project.root / 'data/input.csv', project.root / 'data/codebook.json'
    plan = demo.protocol()
    first = fit_models(csv_path, book_path, plan, progress_path=tmp_path / 'first.json')
    second = fit_models(csv_path, book_path, plan, progress_path=tmp_path / 'second.json')
    assert first == second
    assert first['specification_ledger'][0]['status'] == 'succeeded'
    assert first['specification_ledger'][0]['result_hash'] == digest(first['models'][0])


@pytest.mark.skipif(os.environ.get('CRA_ISOLATION_TESTS') != '1', reason='Real OS worker integration required')
def test_real_worker_failure_is_retained_in_state_and_diagnostic(tmp_path):
    from cra_engine.exporting import export_diagnostic
    from cra_engine.package_check import verify_package
    from cra_engine.runtime import plan, run
    from cra_engine.store import Store
    from conftest import test_approval as fixture_approval
    root = demo.prepare(tmp_path.resolve() / '失败规格研究')
    csv_path, book_path, protocol = prepare_failure(root)
    save(root / 'protocol/plan.json', protocol)
    original_hash = sha(csv_path)
    store = Store(root)
    try:
        plan(store); fixture_approval(store, 'authorization')
        run(store); fixture_approval(store, 'protocol')
        result = run(store)
        assert result['last_problem']['task'] == 'analysis'
        assert store.object_hash('analysis') is None
        attempts = [__import__('json').loads(r[0]) for r in store.db.execute("SELECT body FROM objects WHERE kind='specification_attempt'")]
        assert len(attempts) == 1 and attempts[0]['status'] == 'failed'
        progress = attempts[0]['model_progress']
        assert [e['status'] for e in progress['entries']] == ['succeeded', 'failed', 'not_run']
        assert progress['completed_models'][0]['parameters'][1]['p'] > .05
        evidence = attempts[0]['execution']
        assert sha(root / evidence['progress_path']) == evidence['progress_sha256']
        exported = export_diagnostic(store)
        from pathlib import Path
        ledger = load(Path(exported['directory']) / 'specification-ledger.json')
        assert ledger[0]['model_progress'] == progress
        assert verify_package(exported['archive'])['passed']
        assert sha(csv_path) == original_hash
    finally:
        store.close()
