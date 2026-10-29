"""Independent normal equations / Newton logit oracle; no statsmodels in oracle."""
import csv
from pathlib import Path

from cra_engine.common import save, require
from cra_engine.statistics import fit_models, audit


def dataset(root, variant):
    import numpy as np
    rng = np.random.default_rng(20261028 + variant)
    n = 480
    x, z = rng.normal(size=(2, n))
    group = np.where(np.arange(n) % 2, "B", "A")
    clusters = np.arange(n) % 40
    shocks = rng.normal(scale=.3, size=40)
    y = .6 + .25*x - .1*z + .4*(group == "B") + shocks[clusters] + rng.normal(size=n)*(1 + .2*abs(x))
    binary = rng.binomial(1, 1 / (1 + np.exp(-(.2 + .3*x - .2*z + .2*(group == "B") + shocks[clusters]))))
    weights = .5 + rng.random(n)*2
    rows = []
    for i in range(n):
        row = dict(x=float(x[i]), z=float(z[i]), y=float(y[i]), binary=int(binary[i]), group=str(group[i]), cluster="C%02d" % clusters[i], weight=float(weights[i]))
        if variant == 1 and i % 17 == 0:
            row["z"] = ""
        rows.append(row)
    columns = {key: {"type": "number", "sensitive": False} for key in ("x", "z", "y", "binary", "weight")}
    columns.update(group={"type": "category", "allowed": ["A", "B"], "sensitive": False}, cluster={"type": "category", "allowed": ["C%02d" % i for i in range(40)], "sensitive": False})
    book = {"schema_version": 2, "columns": columns}
    root.mkdir(parents=True, exist_ok=True)
    path = root / "input.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save(root / "codebook.json", book)
    # Oracle reads serialized inputs as well, rather than higher-precision generator arrays.
    with path.open(newline="") as f:
        return list(csv.DictReader(f)), book


def oracle(rows, spec, exclusions):
    import numpy as np
    from scipy.special import expit
    from scipy.stats import norm, t
    kept = [r for r in rows if not exclusions or float(r["x"]) <= 1.2]
    fields = [spec["y"], *spec["x"], *[spec[k] for k in ("weight", "cluster") if spec.get(k)]]
    sample = [r for r in kept if all(r[field] != "" for field in fields)]
    terms = ["const", "x", "z"] + (["group=B"] if "group" in spec["x"] else [])
    X = np.asarray([[1, float(r["x"]), float(r["z"])] + ([float(r["group"] == "B")] if "group" in spec["x"] else []) for r in sample])
    y = np.asarray([float(r[spec["y"]]) for r in sample])
    n, k = X.shape
    w = np.asarray([float(r["weight"]) for r in sample]) if spec["family"] == "wls" else np.ones(n)
    if spec["family"] == "logit":
        b = np.zeros(k)
        for _ in range(100):
            mu = expit(X@b)
            H = X.T @ ((mu*(1-mu))[:, None]*X)
            step = np.linalg.solve(H, X.T@(y-mu))
            b += step
            if np.max(abs(step)) < 1e-12:
                break
        mu = expit(X@b)
        bread = np.linalg.inv(X.T@((mu*(1-mu))[:, None]*X))
        scores = X*(y-mu)[:, None]
        covariance = bread
    else:
        bread = np.linalg.inv(X.T@(w[:, None]*X))
        b = bread@(X.T@(w*y))
        residual = y-X@b
        scores = X*(w*residual)[:, None]
        covariance = bread * (w*residual**2).sum()/(n-k)
        if spec["covariance"] == "HC3":
            leverage = w*np.einsum("ij,jk,ik->i", X, bread, X)
            corrected = X*(residual/(1-leverage))[:, None]
            covariance = bread@corrected.T@corrected@bread
    degrees = n-k
    if spec["covariance"] == "cluster":
        groups = sorted({r["cluster"] for r in sample})
        sums = np.asarray([scores[[r["cluster"] == g for r in sample]].sum(axis=0) for g in groups])
        covariance = bread@sums.T@sums@bread * len(groups)/(len(groups)-1)*(n-1)/(n-k)
        degrees = len(groups)-1
    se = np.sqrt(np.diag(covariance))
    law = norm if spec["family"] == "logit" else t(degrees)
    statistic = b/se
    p = law.sf(abs(statistic))*2
    margin = law.ppf(.975)*se
    return {"n": n, "terms": terms, "values": np.column_stack([b, se, statistic, p, b-margin, b+margin]).tolist(), "retained": len(kept), "degrees": degrees}


def run(root):
    import numpy as np
    root = Path(root)
    combinations = [("ols", "classical"), ("ols", "HC3"), ("ols", "cluster"), ("wls", "classical"), ("wls", "cluster"), ("logit", "classical"), ("logit", "cluster")]
    cases = []
    for variant in range(4):
        rows, _ = dataset(root / ("data-%s" % variant), variant)
        data = root / ("data-%s" % variant)
        for family, cov in combinations:
            ident = "%s-%s-v%s" % (family, cov, variant)
            spec = {"id": "main", "family": family, "covariance": cov, "role": "primary", "y": "binary" if family == "logit" else "y", "x": ["x", "z"]}
            if variant == 2:
                spec.update(x=["x", "z", "group"], reference={"group": "A"})
            if family == "wls":
                spec["weight"] = "weight"
            if cov == "cluster":
                spec["cluster"] = "cluster"
            rules = [{"column": "x", "op": "gt", "value": 1.2}] if variant == 3 else []
            plan = {"models": [spec], "exclusions": rules}
            actual = fit_models(data / "input.csv", data / "codebook.json", plan)
            expected = oracle(rows, spec, rules)
            model = actual["models"][0]
            fields = ["estimate", "se", "statistic", "p", "ci_low", "ci_high"]
            values = [[p[k] for k in fields] for p in model["parameters"]]
            numeric = bool(np.allclose(values, expected["values"], atol=1e-7, rtol=1e-6))
            sample = model["n"] == expected["n"] and actual["sample_flow"]["retained"] == expected["retained"] and [p["term"] for p in model["parameters"]] == expected["terms"] and model["reference"] == spec.get("reference", {})
            observation = {"actual": actual, "oracle": expected, "absolute_tolerance": 1e-7, "relative_tolerance": 1e-6, "spec": plan}
            filename = ident + ".json"
            save(root / filename, observation)
            cases.append({"id": ident, "status": "passed" if numeric and sample else "failed", "numeric_match": numeric, "sample_match": sample, "oracle": "independent_numpy_scipy", "artifacts": ["statistics/" + filename]})
    for variant in range(2):
        data = root / ("data-%s" % variant)
        from cra_engine.common import load
        book = load(data / "codebook.json")
        book["descriptive_weight"] = {"column": "weight", "kind": "survey", "justification": "Synthetic known weights, descriptive oracle only"}
        save(data / "weighted-book.json", book)
        result = audit(data / "input.csv", data / "weighted-book.json")
        with (data / "input.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        expected = {name: sum(float(r[name])*float(r["weight"]) for r in rows if r[name] != "")/sum(float(r["weight"]) for r in rows if r[name] != "") for name in ("x", "z", "y", "binary")}
        numeric = all(abs(result["weighted"][name]["weighted_mean"]-value) <= 1e-10 for name, value in expected.items())
        filename = "weighted-descriptive-%s.json" % variant
        save(root / filename, {"actual": result, "oracle": expected})
        cases.append({"id": filename[:-5], "status": "passed" if numeric else "failed", "numeric_match": numeric, "sample_match": all(result["weighted"][name]["n"] == sum(r[name] != "" for r in rows) for name in expected), "oracle": "independent_numpy_scipy", "artifacts": ["statistics/" + filename]})
    require(len(cases) == 30, "Numerical coverage changed")
    return {"cases": cases, "scope": "Actual statistical adapter; independent NumPy/SciPy oracle. No research-quality or human approval claim."}
