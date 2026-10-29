import pytest

from cra_engine.profiles import check_profile
from cra_engine.research import create_claims, render_draft


def test_official_requirement_blocks_but_empirical_advice_does_not():
    rule={'url':'https://example.invalid/guideline','requirements':[{'code':'max_words','value':2}]}
    official=check_profile({'sources':[dict(rule,kind='official')]},'one two three')
    suggestion=check_profile({'sources':[dict(rule,kind='observed')]},'one two three')
    assert official[0]['severity']=='blocking'
    assert suggestion[0]['severity']=='warning'


def test_required_sections_and_anonymous_labels():
    profile={'sources':[{'kind':'official','url':'https://example.invalid/guideline','requirements':[{'code':'required_sections','value':['Methods']},{'code':'anonymous','value':True}]}]}
    issues=check_profile(profile,'Author: synthetic fixture\n## Results\n')
    assert len(issues)==2 and all(i['severity']=='blocking' for i in issues)


def test_unsupported_page_limit_stays_manual():
    profile={'sources':[{'kind':'official','url':'https://example.invalid/guideline','requirements':[{'code':'max_pages','value':20}]}]}
    issue=check_profile(profile,'text')[0]
    assert issue['code']=='manual_target_check' and issue['severity']=='warning'


def test_english_draft_localizes_computed_sections(completed):
    analysis=completed.get('analysis')
    claims=create_claims(analysis,'en')
    narrative={'introduction':'Engineering evidence only. [[cite:method_note]]','theory':'The source is a synthetic methods note. [[cite:method_note]]','discussion':'The estimate is an association, not a causal identification.','limitations':'Synthetic data cannot establish empirical claims.'}
    draft=render_draft(completed.get('protocol'),analysis,completed.get('corpus'),claims,narrative,True,'en')
    assert '## Methods' in draft['text'] and '## Conclusions' in draft['text']
    assert 'complete-case N = 160' in draft['text']
    assert 'Synthetic data' in draft['text']
