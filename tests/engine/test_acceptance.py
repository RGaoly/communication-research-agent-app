import json
import os
import subprocess
import sys

import pytest

from cra_engine.common import EngineError, load, save
from cra_engine.evaluation import release_check
from cra_engine.literature import build_corpus
from cra_engine.runtime import plan, run, sync, status
from cra_engine.schema import validate_protocol
from cra_engine.statistics import effective_book
from cra_engine.store import Store
from conftest import demo, test_approval as approve_fixture


def test_synthetic_tests_cannot_pass_release_gate(completed):
    result=release_check(completed)
    assert not result['release_eligible']
    assert len(result['accepted_pilots'])==0
    assert any('synthetic' in s for s in result['blockers'])


def test_pilot_registry_requires_both_real_review_roles(completed,tmp_path):
    path=tmp_path/'pilots.json'
    save(path,[{'project_id':'fake','synthetic':True,'data_authorized':True}])
    result=release_check(completed,path)
    assert result['accepted_pilots']==[]
    assert result['rejected_pilots']==['fake']


def test_release_report_must_match_actual_source(completed,tmp_path):
    from cra_engine.common import source_fingerprint
    report=tmp_path/'software.json'
    from cra_engine import __version__
    value={'version':__version__,'source_tree_sha256':source_fingerprint(),'software_tests':{'tests':1,'failures':0,'errors':0,'skipped':0}}
    save(report,value)
    # Even matching version/count fields are caller declarations, not a raw run.
    assert not release_check(completed,software_report=report)['software_evidence_passed']
    value['source_tree_sha256']='wrong';save(report,value)
    assert not release_check(completed,software_report=report)['software_evidence_passed']


def test_actual_process_crash_recovers_lease_task_and_unknown_cost(prepared):
    script='''import sys,os
from cra_engine.store import Store
s=Store(sys.argv[1])
with s.tx():
 b=s.get('brief');b['limits']['max_cost']=1;s.put('brief','research_brief',b)
with s.lease():
 with s.tx(): s.db.execute("UPDATE tasks SET status='running' WHERE id='audit'")
 s.reserve('crash-fixture',0.1,'fixture')
 os._exit(99)
'''
    result=subprocess.run([sys.executable,'-c',script,str(prepared.root)],capture_output=True)
    assert result.returncode==99
    with prepared.lease():
        assert prepared.budget()['uncertain']==1
        assert next(t for t in prepared.task_rows() if t['id']=='audit')['status']=='ready'


def test_no_isolation_has_no_unrestricted_fallback(prepared,monkeypatch):
    monkeypatch.setattr('cra_engine.runtime.doctor',lambda _: (_ for _ in ()).throw(EngineError('Isolation unavailable')))
    with pytest.raises(EngineError,match='Isolation'): run(prepared)
    assert prepared.get('analysis') is None
    assert all(t['attempts']==0 for t in prepared.task_rows())


def test_discovery_without_fulltext_stays_metadata_only(project,monkeypatch):
    (project.root/'literature/references.json').unlink()
    brief=load(project.root/'brief.json');brief['permissions'].update(literature_network=True,allowed_hosts=['api.crossref.org'])
    result={'query':'fixture','accessed_at':'2026-10-28','items':[{'id':'metadata_only','title':'Test metadata fixture','year':'2026','source':'fixture','authors':['Synthetic Author'],'url':'https://example.invalid/test','doi':'10.1234/test-only','metadata':{'status':'verified','method':'Crossref fixture'},'spans':[]}]}
    monkeypatch.setattr('cra_engine.literature.crossref_search',lambda *a,**k:result)
    corpus=build_corpus(project.root,brief)
    assert corpus['discovery']['status'].startswith('metadata_only')
    assert corpus['items'][0]['spans']==[]
    with pytest.raises(EngineError):validate_protocol(demo.protocol(),effective_book(load(project.root/'data/codebook.json')),corpus)


def test_matching_title_wrong_author_not_verified(project,monkeypatch):
    refs=load(project.root/'literature/references.json');refs[0]['doi']='10.1234/test-only';save(project.root/'literature/references.json',refs)
    brief=load(project.root/'brief.json');brief['permissions'].update(literature_network=True,allowed_hosts=['api.crossref.org'])
    monkeypatch.setattr('cra_engine.literature.fetch_json',lambda *a,**k:{'message':{'title':[refs[0]['title']],'issued':{'date-parts':[[2026]]},'author':[{'family':'WrongAuthor'}]}})
    assert build_corpus(project.root,brief)['items'][0]['metadata']['status']=='mismatch'


def test_model_cannot_claim_causal_or_weighted_survey_regression(project):
    corpus=build_corpus(project.root,load(project.root/'brief.json'));book=effective_book(load(project.root/'data/codebook.json'))
    proto=demo.protocol();proto['models'][0].update(family='wls',weight='weight',weight_kind='survey',weight_justification='not inverse variance')
    with pytest.raises(EngineError):validate_protocol(proto,book,corpus)


def test_exploratory_outcome_must_be_frozen(prepared,local_recipes):
    path=prepared.root/'protocol/plan.json';value=load(path);value['exploratory']=True;save(path,value)
    run(prepared);approve_fixture(prepared,'protocol');run(prepared);approve_fixture(prepared,'final')
    assert status(prepared)['outcome']=='exploratory_package'


def test_unknown_json_does_not_print_traceback(project):
    (project.root/'project.json').write_text('{DO_NOT_ECHO_SECRET')
    result=subprocess.run([sys.executable,'-m','cra_engine','status',str(project.root)],capture_output=True,text=True)
    assert result.returncode==2
    assert 'Traceback' not in result.stderr and 'DO_NOT_ECHO_SECRET' not in result.stderr


def test_saved_specification_failure_is_not_discarded(prepared,local_recipes):
    proto=load(prepared.root/'protocol/plan.json');proto['models'][0].update(family='logit',y='trust',covariance='classical');save(prepared.root/'protocol/plan.json',proto)
    run(prepared);approve_fixture(prepared,'protocol');run(prepared)
    specs=[json.loads(row[0]) for row in prepared.db.execute("SELECT body FROM objects WHERE kind='specification_attempt'")]
    assert len(specs)==1 and specs[0]['status']=='failed'
    assert prepared.get('analysis') is None


def test_paid_network_unknown_does_not_auto_retry(prepared,monkeypatch):
    from cra_engine.models import ModelAdapter
    brief=prepared.get('brief');brief['permissions'].update(model=True,allowed_hosts=['fixture.invalid']);brief['limits']['max_cost']=1
    brief['model'].update(base_url='https://fixture.invalid/v1',model='fixture',input_per_million=1,output_per_million=2)
    with prepared.tx():prepared.put('brief','research_brief',brief)
    approve_fixture(prepared,'authorization');monkeypatch.setenv('CRA_API_KEY','FIXTURE-ONLY')
    calls=[]
    def failed(*args,**kwargs):
        calls.append(True)
        raise EngineError('Unknown remote result')
    monkeypatch.setattr('cra_engine.models.fetch_json',failed)
    for _ in range(2):
        with pytest.raises(EngineError):ModelAdapter(prepared).contract_test()
    assert len(calls)==1 and prepared.budget()['uncertain']==1
