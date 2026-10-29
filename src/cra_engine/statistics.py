"""Audited local recipes. Never exposes rows, residuals, cluster IDs or raw exceptions."""
import csv
import importlib.metadata
import math
import warnings
from pathlib import Path

from .common import EngineError, digest, finite, identifier, load, require, safe_text, save, sha


def recipe_identity():
    """Content-based recipe/environment identity, portable across install paths."""
    import sys
    packages = {}
    for name in ("numpy", "scipy", "pandas", "statsmodels"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not_installed"
    return {"id": "python-survey-v2", "python_version": sys.version.split()[0], "packages": packages,
            "sources": {name: sha(Path(__file__).with_name(name)) for name in
                        ("__init__.py", "common.py", "statistics.py", "worker.py", "isolation.py")}}


def dependencies():
    try:
        import numpy as np
        import pandas as pd
        import statsmodels.api as sm
    except ImportError as exc:
        raise EngineError("Install the explicit [engine] dependencies; no automatic installation") from exc
    return np, pd, sm


def read_frame(csv_path, book_path):
    np, pd, _ = dependencies()
    book = load(book_path)
    safe_text(Path(csv_path).read_text(encoding="utf-8-sig"))
    require(book.get("schema_version") in (1, 2) and isinstance(book.get("columns"), dict), "Invalid codebook")
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        names = reader.fieldnames
        require(names and len(set(names)) == len(names) and set(names) == set(book["columns"]), "CSV and codebook columns must match without duplicates")
        rows = list(reader)
    require(rows and all(None not in r and all(v is not None for v in r.values()) for r in rows), "Empty or malformed CSV")
    frame = pd.DataFrame(rows).replace(r"^\s*$", np.nan, regex=True)
    issues = []
    for name, spec in book["columns"].items():
        require(identifier(name), "Use non-identifying machine variable names")
        require(spec.get("type") in ("number", "category", "id", "text") and type(spec.get("sensitive")) is bool, "Variable type and explicit sensitive flag required")
        require(not spec["sensitive"], "Sensitive column refused; prepare a de-identified working copy")
        if spec["type"] == "number":
            converted = pd.to_numeric(frame[name], errors="coerce")
            require(not (frame[name].notna() & converted.isna()).any(), "Unparseable numeric value; inspect locally")
            require(np.isfinite(converted.dropna()).all(), "Nonfinite input refused")
            for bound in ("min", "max"):
                if bound in spec:
                    require(finite(spec[bound]), "Scale boundary must be finite")
            require("min" not in spec or (converted.dropna() >= spec["min"]).all(), "Value below declared scale")
            require("max" not in spec or (converted.dropna() <= spec["max"]).all(), "Value above declared scale")
            frame[name] = converted
        elif spec["type"] == "category":
            require(isinstance(spec.get("allowed"), list) and spec["allowed"] and all(isinstance(x, str) for x in spec["allowed"]), "Category enumeration required")
            require(frame[name].dropna().isin(spec["allowed"]).all(), "Unknown category; inspect locally")
        elif spec["type"] == "id":
            require(not frame[name].isna().any() and not frame[name].duplicated().any(), "Missing or duplicate respondent ID; do not silently remove observations")
    scales = []
    for scale in book.get("scales", []):
        ident, items = scale.get("id"), scale.get("items")
        require(identifier(ident) and ident not in frame and isinstance(items, list) and len(items) >= 2 and len(set(items)) == len(items), "Invalid derived scale")
        require(all(x in frame and book["columns"][x]["type"] == "number" for x in items), "Scale items must be numeric")
        reverse = scale.get("reverse", [])
        require(isinstance(reverse, list) and set(reverse) <= set(items), "Reverse item declaration invalid")
        data = frame[items].copy()
        for item in reverse:
            spec = book["columns"][item]
            require("min" in spec and "max" in spec, "Reverse coding requires declared anchors")
            data[item] = spec["min"] + spec["max"] - data[item]
        frame[ident] = data.mean(axis=1).where(data.notna().all(axis=1))
        complete = data.dropna()
        alpha = None
        negative = []
        correlations = {}
        if len(complete) >= 3:
            total_var = complete.sum(axis=1).var(ddof=1)
            if total_var > 0:
                alpha = len(items) / (len(items) - 1) * (1 - complete.var(ddof=1).sum() / total_var)
            for item in items:
                other = complete.drop(columns=[item]).mean(axis=1)
                if other.std() > 0 and complete[item].std() > 0:
                    correlation = float(complete[item].corr(other))
                    correlations[item] = correlation
                    if correlation < 0:
                        negative.append(item)
        if negative:
            issues.append({"code": "negative_item_rest", "severity": "blocking", "scale": ident, "items": negative,
                           "message": "Check reverse coding and construct structure before analysis"})
        scales.append({"id": ident, "n_complete": len(complete), "alpha": float(alpha) if alpha is not None and math.isfinite(alpha) else None,
                       "negative_item_rest": negative, "item_rest_correlations": correlations, "interpretation": "Internal consistency alone does not establish validity or unidimensionality"})
    return frame, book, scales, issues


def effective_book(book):
    import copy
    value = copy.deepcopy(book)
    for scale in value.get("scales", []):
        value["columns"][scale["id"]] = {"type": "number", "sensitive": False, "derived": scale["items"]}
    return value


def audit(csv_path, book_path, min_cell=10, recruited_n=None):
    np, _, _ = dependencies()
    frame, book, scales, issues = read_frame(csv_path, book_path)
    n = len(frame)
    for scale in scales:
        if scale["n_complete"] < min_cell:
            scale.update(alpha=None, item_rest_correlations={}, suppressed=True)
    descriptions = {}
    for name, spec in effective_book(book)["columns"].items():
        column = frame[name]
        summary = {"n": int(column.notna().sum()), "missing": int(column.isna().sum())}
        if summary["n"] < min_cell:
            summary["suppressed"] = True
        elif spec["type"] == "number":
            summary.update(mean=float(column.mean()), sd=float(column.std(ddof=1)) if summary["n"] > 1 else None)
        elif spec["type"] == "category":
            counts = column.value_counts()
            # Complementary suppression: publish no levels if any level is small.
            if any(int(v) < min_cell for v in counts):
                summary["groups_suppressed"] = True
            else:
                summary["counts"] = {str(k): int(v) for k, v in counts.items()}
        descriptions[name] = summary
    weighted = {}
    grouped = {}
    for name in book.get("group_by", []):
        require(name in book["columns"] and book["columns"][name]["type"] == "category", "Group summaries require a declared category variable")
        counts = frame[name].value_counts()
        if any(int(v) < min_cell for v in counts):
            grouped[name] = {"suppressed": True}
            continue
        values = {}
        for level, subset in frame.groupby(name, observed=True):
            summary = {}
            for field, spec in effective_book(book)["columns"].items():
                if spec["type"] == "number":
                    valid = subset[field].dropna()
                    summary[field] = {"n": len(valid), "mean": float(valid.mean()), "sd": float(valid.std(ddof=1))} if len(valid) >= min_cell else {"suppressed": True}
            values[str(level)] = {"n": len(subset), "unweighted_descriptives": summary}
        grouped[name] = values
    weight = book.get("descriptive_weight")
    if weight:
        require(weight.get("column") in frame and weight.get("kind") in ("survey", "frequency", "inverse_probability") and bool(weight.get("justification")), "Descriptive weight meaning and justification required")
        w = frame[weight["column"]]
        require(book["columns"][weight["column"]]["type"] == "number" and (w.dropna() > 0).all(), "Weights must be positive numeric values")
        for name, spec in book["columns"].items():
            if spec["type"] == "number" and name != weight["column"]:
                valid = frame[name].notna() & w.notna()
                if int(valid.sum()) >= min_cell:
                    weighted[name] = {"n": int(valid.sum()), "weighted_mean": float(np.average(frame.loc[valid, name], weights=w[valid]))}
        weighted["limits"] = "Descriptive means only; no complex-survey variance, representativeness or confidence interval implied"
    if n < min_cell:
        issues.append({"code": "insufficient_sample", "severity": "blocking", "message": "Sample below authorized egress cell threshold"})
    if book.get("design", {}).get("psu") or book.get("design", {}).get("strata"):
        issues.append({"code": "complex_survey", "severity": "blocking", "message": "Complex survey variance requires a validated adapter"})
    if book.get("cross_national_latent_comparison") and not book.get("measurement_invariance_evidence"):
        issues.append({"code": "invariance_missing", "severity": "blocking", "message": "Latent cross-national means require measurement equivalence evidence"})
    require(recruited_n is None or type(recruited_n) is int and recruited_n >= n, "Recruitment N must not be smaller than input N")
    return {"schema_version": 2, "input_sha256": sha(csv_path), "codebook_sha256": sha(book_path),
            "sample_flow": {"recruited": recruited_n, "input_rows": n, "excluded_at_audit": 0, "retained": n},
            "descriptions": descriptions, "groups": grouped, "weighted": weighted, "scales": scales, "issues": issues,
            "privacy": "Aggregate, thresholded summary; not proof of anonymity"}


def _fit_specification(frame, book, spec, min_cell):
    """Execute one trusted, approved statistical specification."""
    np, pd, sm = dependencies()
    required = list(dict.fromkeys([spec["y"], *spec["x"], *[spec[k] for k in ("weight", "cluster") if spec.get(k)]]))
    sample = frame[required].dropna().copy()
    require(len(sample) >= min_cell, "Model complete-case N below authorized egress threshold")
    require(len(sample) > len(spec["x"]) + 2, "Too few complete cases for model")
    x = pd.DataFrame(index=sample.index)
    for name in spec["x"]:
        if effective_book(book)["columns"][name]["type"] == "category":
            require((sample[name].value_counts() >= min_cell).all(), "Small predictor category would leak into model coefficients; inspect locally or obtain explicit threshold authorization")
            reference = spec["reference"][name]
            require(reference in sample[name].values, "Reference category absent from model sample")
            for level in book["columns"][name]["allowed"]:
                if level != reference:
                    x[name + "=" + level] = (sample[name] == level).astype(float)
        else:
            x[name] = sample[name].astype(float)
    x = sm.add_constant(x, has_constant="add")
    require(np.linalg.matrix_rank(x.to_numpy()) == x.shape[1], "Rank-deficient model; inspect collinearity or empty categories")
    require(len(sample) > x.shape[1], "Insufficient residual degrees of freedom")
    y = sample[spec["y"]].astype(float)
    require(y.nunique() > 1, "Outcome has no variation; no conventional model inference")
    covariance = spec["covariance"]
    kwargs = {}
    cluster_n = None
    if covariance == "cluster":
        cluster_n = int(sample[spec["cluster"]].nunique())
        require(cluster_n >= 30, "Fewer than 30 clusters: v0.2 refuses unattended cluster inference; obtain method review/another adapter")
        kwargs = {"groups": sample[spec["cluster"]], "use_correction": True}
    cov_type = "nonrobust" if covariance == "classical" else covariance
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            if spec["family"] == "ols":
                fit = sm.OLS(y, x).fit(cov_type=cov_type, cov_kwds=kwargs, use_t=True)
            elif spec["family"] == "wls":
                require((sample[spec["weight"]] > 0).all(), "WLS weights must be positive")
                fit = sm.WLS(y, x, weights=sample[spec["weight"]]).fit(cov_type=cov_type, cov_kwds=kwargs, use_t=True)
            else:
                require(set(y.unique()) == {0.0, 1.0}, "Logit outcome must contain both 0 and 1")
                fit = sm.GLM(y, x, family=sm.families.Binomial()).fit(cov_type=cov_type, cov_kwds=kwargs, maxiter=100)
                require(fit.converged, "Logit did not converge")
                require(not any("separation" in str(w.message).lower() for w in caught), "Logit separation detected; no conventional inference")
                require(np.max(np.abs(fit.params)) < 25 and np.max(fit.bse) < 100, "Logit instability/separation diagnostic failed")
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError("Statistical execution failed; raw data/error details remain local") from exc
    ci = fit.conf_int(alpha=0.05)
    params = []
    for term in x.columns:
        values = [float(fit.params[term]), float(fit.bse[term]), float(fit.tvalues[term]), float(fit.pvalues[term]), float(ci.loc[term, 0]), float(ci.loc[term, 1])]
        require(all(math.isfinite(v) for v in values), "Nonfinite model output")
        params.append(dict(zip(("estimate", "se", "statistic", "p", "ci_low", "ci_high"), values), term=term))
    if spec["family"] == "logit":
        fit_metrics = {"mcfadden_pseudo_r2": float(1 - fit.llf / fit.llnull)}
    elif spec["family"] == "wls":
        # statsmodels WLS uses weighted sums of squares. Do not label this
        # as ordinary unweighted OLS R-squared in the result contract.
        fit_metrics = {"weighted_r2": float(fit.rsquared), "weighted_adjusted_r2": float(fit.rsquared_adj)}
    else:
        fit_metrics = {"ols_r2": float(fit.rsquared), "adjusted_r2": float(fit.rsquared_adj)}
    require(all(math.isfinite(v) for v in fit_metrics.values()), "Undefined fit statistic; inspect degenerate model")
    return {"id": spec["id"], "family": spec["family"], "role": spec["role"], "outcome": spec["y"],
                   "predictors": spec["x"], "reference": spec.get("reference", {}), "n": int(fit.nobs),
                   "missing_dropped": len(frame) - int(fit.nobs), "covariance": covariance, "clusters": cluster_n,
                   "weight": spec.get("weight"), "estimand": "conditional association", "parameters": params,
                   "fit": fit_metrics, "diagnostics": {"rank": int(np.linalg.matrix_rank(x)), "condition_number": float(np.linalg.cond(x)), "warning_count": len(caught)}}


def fit_models(csv_path, book_path, protocol, min_cell=10, progress_path=None):
    np, pd, sm = dependencies()
    frame, book, scales, issues = read_frame(csv_path, book_path)
    require(not any(i["severity"] == "blocking" for i in issues), "Measurement diagnostics block analysis")
    input_n = len(frame)
    flow = []
    for rule in protocol.get("exclusions", []):
        column = frame[rule["column"]]
        value = rule["value"]
        comparison = {"eq": lambda: column == value, "ne": lambda: column != value,
                      "gt": lambda: column > value, "lt": lambda: column < value}[rule["op"]]()
        # Missing data never become an implicit exclusion under 'ne'.
        keep = ~comparison | column.isna()
        before = len(frame)
        frame = frame[keep].copy()
        flow.append({"rule": rule, "removed": before - len(frame), "retained": len(frame)})
    models = []
    entries = [{"id": spec["id"], "specification_hash": digest(spec), "status": "pending"} for spec in protocol["models"]]
    progress = {"schema_version": 2, "kind": "analysis_progress", "research_completed": False,
                "analysis_status": "running", "data_sha256": sha(csv_path), "codebook_sha256": sha(book_path),
                "protocol_hash": digest(protocol), "source_code_sha256": sha(Path(__file__)),
                "entries": entries, "completed_models": models,
                "limits": "Partial execution evidence only; never a completed study or approved analysis"}
    def persist():
        if progress_path is not None:
            save(progress_path, progress)
    persist()
    for index, spec in enumerate(protocol["models"]):
        entries[index]["status"] = "running"
        persist()
        try:
            model = _fit_specification(frame, book, spec, min_cell)
        except BaseException as exc:
            interrupted = not isinstance(exc, Exception)
            message = str(exc) if isinstance(exc, EngineError) else "Statistical specification interrupted or failed; raw details withheld"
            entries[index].update(status="interrupted" if interrupted else "failed",
                                  error_fingerprint=digest({"type": type(exc).__name__, "message": message}))
            for entry in entries[index+1:]:
                entry.update(status="not_run", reason="Stopped after an earlier unsuccessful specification")
            progress["analysis_status"] = "interrupted" if interrupted else "failed"
            persist()
            raise
        models.append(model)
        entries[index].update(status="succeeded", result_hash=digest(model), n=model["n"])
        persist()
    progress["analysis_status"] = "succeeded"
    persist()
    return {"schema_version": 2, "data_sha256": sha(csv_path), "codebook_sha256": sha(book_path), "protocol_hash": digest(protocol), "privacy_min_cell": min_cell,
            "recipe_identity": recipe_identity(),
            "sample_flow": {"input": input_n, "exclusions": flow, "retained": len(frame)}, "models": models, "specification_ledger": entries,
            "environment": {package: importlib.metadata.version(package) for package in ("numpy", "scipy", "pandas", "statsmodels")},
            "limits": "Association only; no complex-survey inference, causal identification or automatic measurement validation"}
