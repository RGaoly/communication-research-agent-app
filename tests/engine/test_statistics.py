import copy
import csv
import math

import numpy as np
import pytest
from scipy.optimize import minimize
from scipy.special import expit

from cra_engine.common import EngineError, load, save
from cra_engine.statistics import audit, fit_models
from conftest import demo


def paths(project):
    return project.root / "data/input.csv", project.root / "data/codebook.json"


def test_ols_hc3_matches_independent_sandwich(project):
    csv_path, book = paths(project)
    plan = demo.protocol()
    result = fit_models(csv_path, book, plan)["models"][0]
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    x = np.array([[1, float(r["exposure"])] for r in rows])
    y = np.array([float(r["trust"]) for r in rows])
    inverse = np.linalg.inv(x.T @ x)
    b = inverse @ x.T @ y
    residual = y - x @ b
    hat = np.sum((x @ inverse) * x, axis=1)
    variance = inverse @ x.T @ np.diag(residual ** 2 / (1 - hat) ** 2) @ x @ inverse
    assert [p["estimate"] for p in result["parameters"]] == pytest.approx(b)
    assert [p["se"] for p in result["parameters"]] == pytest.approx(np.sqrt(np.diag(variance)))
    assert result["n"] == 160


def test_wls_fit_metrics_are_explicitly_weighted_and_match_oracle(project):
    csv_path, book = paths(project)
    plan = demo.protocol()
    plan["models"][0].update(family="wls", covariance="classical", weight="weight",
                            weight_kind="inverse_variance", weight_justification="Synthetic inverse-variance oracle")
    model = fit_models(csv_path, book, plan)["models"][0]
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    x = np.asarray([[1, float(row["exposure"])] for row in rows])
    y = np.asarray([float(row["trust"]) for row in rows])
    w = np.asarray([float(row["weight"]) for row in rows])
    beta = np.linalg.solve(x.T @ (w[:, None] * x), x.T @ (w * y))
    expected = 1 - np.sum(w * (y - x @ beta) ** 2) / np.sum(w * (y - np.average(y, weights=w)) ** 2)
    assert model["fit"] == pytest.approx({"weighted_r2": expected,
                                         "weighted_adjusted_r2": 1 - (1-expected)*(len(y)-1)/(len(y)-x.shape[1])})
    assert "ols_r2" not in model["fit"]


def test_logit_matches_independent_optimization(project):
    csv_path, book = paths(project)
    plan = demo.protocol()
    plan["models"][0].update(family="logit", y="binary", covariance="classical")
    result = fit_models(csv_path, book, plan)["models"][0]
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    x = np.array([[1, float(r["exposure"])] for r in rows])
    y = np.array([float(r["binary"]) for r in rows])
    target = lambda b: np.sum(np.logaddexp(0, x @ b) - y * (x @ b))
    optimum = minimize(target, np.zeros(2), jac=lambda b: x.T @ (expit(x @ b) - y), method="BFGS", options={"gtol": 1e-8})
    assert [p["estimate"] for p in result["parameters"]] == pytest.approx(optimum.x, abs=1e-6)
    assert "mcfadden_pseudo_r2" in result["fit"]


def test_wls_independent_normal_equations(project):
    csv_path, book = paths(project)
    plan = demo.protocol()
    plan["models"][0].update(family="wls", covariance="classical", weight="weight", weight_kind="inverse_variance", weight_justification="Synthetic inverse variance fixture")
    result = fit_models(csv_path, book, plan)["models"][0]
    with csv_path.open() as stream:
        rows = list(csv.DictReader(stream))
    x = np.array([[1, float(r["exposure"])] for r in rows]); y = np.array([float(r["trust"]) for r in rows]); w = np.array([float(r["weight"]) for r in rows])
    expected = np.linalg.solve(x.T @ (w[:, None] * x), x.T @ (w * y))
    assert [p["estimate"] for p in result["parameters"]] == pytest.approx(expected)


def test_weighted_description_has_no_survey_ci(project):
    csv_path, book_path = paths(project)
    book = load(book_path)
    book["descriptive_weight"] = {"column": "weight", "kind": "survey", "justification": "Synthetic fixture only"}
    save(book_path, book)
    value = audit(csv_path, book_path)
    assert "weighted_mean" in value["weighted"]["trust"]
    assert "complex-survey" in value["weighted"]["limits"]
    assert "ci" not in value["weighted"]["trust"]


def test_weight_without_meaning_refused(project):
    csv_path, book_path = paths(project)
    book = load(book_path); book["descriptive_weight"] = {"column": "weight"}; save(book_path, book)
    with pytest.raises(EngineError): audit(csv_path, book_path)


def test_category_reference_and_cluster_covariance(project):
    csv_path, book = paths(project)
    plan = demo.protocol()
    plan["models"][0].update(x=["exposure", "group"], reference={"group": "A"}, covariance="cluster", cluster="cluster")
    result = fit_models(csv_path, book, plan)["models"][0]
    assert result["clusters"] == 40
    assert "group=B" in [p["term"] for p in result["parameters"]]


def test_too_few_clusters_refuses_unattended_inference(project):
    csv_path, book = paths(project)
    plan = demo.protocol(); plan["models"][0].update(covariance="cluster", cluster="group")
    with pytest.raises(EngineError, match="30 clusters"):
        fit_models(csv_path, book, plan)


def test_logit_complete_separation_stops(project):
    csv_path, book = paths(project)
    with csv_path.open() as stream: rows = list(csv.DictReader(stream))
    for r in rows: r["binary"] = int(float(r["exposure"]) > 2)
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    plan = demo.protocol(); plan["models"][0].update(family="logit", y="binary", covariance="classical")
    with pytest.raises(EngineError, match="separation|instability|failed"):
        fit_models(csv_path, book, plan)


def test_small_group_complementary_suppression(project):
    csv_path, book_path = paths(project)
    with csv_path.open() as stream: rows = list(csv.DictReader(stream))
    for i,r in enumerate(rows): r["group"] = "B" if i == 0 else "A"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    report = audit(csv_path, book_path)
    assert report["descriptions"]["group"]["groups_suppressed"]
    assert "counts" not in report["descriptions"]["group"]


def test_missing_cases_flow_no_imputation(project):
    csv_path, book = paths(project)
    with csv_path.open() as stream: rows = list(csv.DictReader(stream))
    rows[0]["trust"] = ""
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    report = fit_models(csv_path, book, demo.protocol())
    assert report["models"][0]["n"] == 159
    assert report["models"][0]["missing_dropped"] == 1


def test_no_significance_search_on_null_outcome(project):
    csv_path, book = paths(project)
    import random
    rng=random.Random(19)
    with csv_path.open() as stream: rows = list(csv.DictReader(stream))
    for row in rows: row["trust"] = 2 + rng.uniform(-0.5,0.5)
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    value = fit_models(csv_path, book, demo.protocol())
    assert len(value["models"]) == 1
    assert value["models"][0]["parameters"][1]["p"] > 0.05


def test_complex_survey_and_invariance_block(project):
    csv_path, book_path = paths(project)
    book = load(book_path);book.update(design={"psu":"cluster"},cross_national_latent_comparison=True);save(book_path,book)
    issues=audit(csv_path,book_path)["issues"]
    assert {"complex_survey","invariance_missing"} <= {i["code"] for i in issues}


def test_sensitive_content_never_echoed(project):
    csv_path, book_path=paths(project)
    raw=csv_path.read_text().replace('S000','person.private@example.invalid')
    csv_path.write_text(raw)
    with pytest.raises(EngineError) as caught:audit(csv_path,book_path)
    assert 'person.private' not in str(caught.value)


def test_scale_reverse_coding_detection(tmp_path):
    csv_path=tmp_path/'data.csv';book_path=tmp_path/'book.json'
    csv_path.write_text('a,b\n'+''.join(f'{i%5+1},{5-i%5}\n' for i in range(30)))
    book={'schema_version':2,'columns':{k:{'type':'number','sensitive':False,'min':1,'max':5} for k in ('a','b')},'scales':[{'id':'scale','items':['a','b'],'reverse':[]}]}
    save(book_path,book)
    assert any(i['code']=='negative_item_rest' for i in audit(csv_path,book_path)['issues'])
    book['scales'][0]['reverse']=['b'];save(book_path,book)
    fixed=audit(csv_path,book_path)
    assert not fixed['issues']
    assert fixed['scales'][0]['alpha']==pytest.approx(1)


def test_grouped_descriptives_and_small_predictor_safety(project):
    csv_path,book_path=paths(project)
    book=load(book_path);book['group_by']=['group'];save(book_path,book)
    report=audit(csv_path,book_path)
    assert report['groups']['group']['A']['n']==80
    assert 'mean' in report['groups']['group']['A']['unweighted_descriptives']['trust']
    with csv_path.open() as stream:rows=list(csv.DictReader(stream))
    for i,row in enumerate(rows):row['group']='B' if i==0 else 'A'
    with csv_path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    assert audit(csv_path,book_path)['groups']['group']['suppressed']
    proto=demo.protocol();proto['models'][0].update(x=['exposure','group'],reference={'group':'A'})
    with pytest.raises(EngineError,match='Small predictor'):fit_models(csv_path,book_path,proto)
