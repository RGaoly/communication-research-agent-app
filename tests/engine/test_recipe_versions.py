"""A code/environment change cannot silently reuse old statistical evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

from cra_engine import runtime, statistics
from cra_engine.common import load, save, sha


def test_real_cli_invalidates_after_recipe_code_changes(completed, tmp_path):
    original_input = sha(completed.root / 'data/input.csv')
    original_analysis = completed.object_hash('analysis')
    alternate = tmp_path / 'alternate-install'
    package = alternate / 'cra_engine'
    shutil.copytree(Path(runtime.__file__).parent, package, ignore=shutil.ignore_patterns('__pycache__'))
    env = dict(os.environ, PYTHONPATH=str(alternate), PYTHONDONTWRITEBYTECODE='1')
    env.pop('CRA_API_KEY', None)
    def status():
        result = subprocess.run([sys.executable, '-m', 'cra_engine', 'status', str(completed.root), '--json'],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert status()['complete']
    assert completed.object_hash('analysis') == original_analysis
    source = package / 'statistics.py'
    source.write_text(source.read_text() + '\n# Synthetic changed-recipe identity probe\n')
    changed = status()
    assert not changed['complete']
    assert not changed['approvals']['final']
    assert completed.object_hash('analysis') is None
    assert completed.object_hash('corpus') is not None
    assert sha(completed.root / 'data/input.csv') == original_input


def test_dependency_version_change_invalidates_statistics(completed, monkeypatch):
    original_version = statistics.importlib.metadata.version
    monkeypatch.setattr(statistics.importlib.metadata, 'version',
                        lambda name: 'TEST-DIFFERENT-VERSION' if name == 'numpy' else original_version(name))
    runtime.sync(completed)
    assert completed.object_hash('analysis') is None
    assert not completed.approved('final')
    assert completed.object_hash('corpus') is not None


def test_unchanged_science_can_rebuild_without_reapproving_protocol(completed, monkeypatch):
    original_version = statistics.importlib.metadata.version
    monkeypatch.setattr(statistics.importlib.metadata, 'version',
                        lambda name: 'TEST-DIFFERENT-VERSION' if name == 'numpy' else original_version(name))
    value = runtime.run(completed)
    assert value['readiness']['ready_for_final']
    assert value['approvals']['protocol']
    assert not value['approvals']['final']
    assert not value['complete']
    assert completed.get('analysis', fresh=True)['recipe_identity']['packages']['numpy'] == 'TEST-DIFFERENT-VERSION'


def test_export_source_tamper_is_caught_after_manifest_is_repaired(completed):
    from cra_engine.exporting import export_package
    from cra_engine.package_check import verify_package
    exported = export_package(completed, working=True, include_data=True)
    root = Path(exported['directory'])
    assert verify_package(root)['passed']
    relative = 'recipe/cra_engine/statistics.py'
    source = root / relative
    source.write_text(source.read_text() + '\n# Synthetic source substitution probe\n')
    manifest = load(root / 'manifest.json')
    manifest['files'][relative] = sha(source)
    save(root / 'manifest.json', manifest)
    result = verify_package(root)
    assert not result['passed']
    assert 'recipe source differs' in result['error']


@pytest.mark.parametrize('malformed', ['analysis_array', 'sources_array'])
def test_malformed_recipe_contract_returns_failure_without_traceback(completed, malformed):
    from cra_engine.exporting import export_package
    from cra_engine.package_check import verify_package
    root = Path(export_package(completed, working=True)['directory'])
    data = load(root / 'analysis.json')
    if malformed == 'analysis_array':
        data = []
    else:
        data['recipe_identity']['sources'] = list(data['recipe_identity']['sources'])
    save(root / 'analysis.json', data)
    manifest = load(root / 'manifest.json')
    manifest['files']['analysis.json'] = sha(root / 'analysis.json')
    save(root / 'manifest.json', manifest)
    assert verify_package(root)['passed'] is False
