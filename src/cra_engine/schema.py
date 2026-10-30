from urllib.parse import urlsplit

from .common import finite, identifier, require, safe_text

TASKS = [
    ("audit", "audit", []),
    ("corpus", "literature", []),
    ("protocol", "design", ["audit", "corpus"]),
    ("analysis", "statistics", ["audit", "protocol"]),
    ("claims", "claims", ["analysis"]),
    ("draft", "writing", ["claims", "corpus", "protocol"]),
    ("method_review", "method_review", ["analysis", "protocol"]),
    ("evidence_review", "evidence_review", ["draft", "claims", "corpus"]),
]


def default_brief(name):
    return {"schema_version": 2, "name": name, "theme": "", "objective": "", "language": "zh-CN",
            "data": {"csv": "data/input.csv", "codebook": "data/codebook.json", "recruited_n": None},
            "permissions": {"model": False, "literature_network": False, "allowed_hosts": []},
            "model": {"base_url": "", "model": "", "key_env": "CRA_API_KEY", "input_per_million": 0,
                      "output_per_million": 0, "max_input_bytes": 24000, "max_output_tokens": 4000, "timeout": 60},
            "limits": {"max_cost": 0, "currency": "USD", "max_seconds": 7200, "max_parallel": 2,
                       "max_revisions": 2, "min_cell": 10},
            "profile": {"name": "apa7", "target": "", "sources": []}}


def validate_brief(value):
    require(isinstance(value, dict) and value.get("schema_version") == 2, "brief schema_version must be 2")
    require(all(isinstance(value.get(k), str) and value[k].strip() for k in ("theme", "objective", "name", "language")), "Fill theme, objective, name and language")
    require(value["language"] in ("zh", "zh-CN", "en", "en-US", "en-GB"), "v0.2 currently supports Simplified Chinese and English output")
    require(isinstance(value.get("data"), dict) and all(isinstance(value["data"].get(k), str) for k in ("csv", "codebook")), "Data paths required")
    permissions = value.get("permissions", {})
    require(all(type(permissions.get(k)) is bool for k in ("model", "literature_network")), "Explicit permission booleans required")
    require(isinstance(permissions.get("allowed_hosts"), list) and all(isinstance(h, str) and h and "/" not in h for h in permissions["allowed_hosts"]), "Invalid allowed hosts")
    require(type(permissions.get("remote_statistics", False)) is bool, "Explicit remote statistics permission required")
    execution = value.get("execution", {"backend": "local"})
    require(isinstance(execution, dict) and execution.get("backend") in ("local", "remote"), "Unknown statistics execution backend")
    if execution["backend"] == "local":
        require(set(execution) == {"backend"} and not permissions.get("remote_statistics", False), "Local statistics cannot grant remote transfer")
    else:
        require(set(execution) == {"backend", "endpoint", "identity_hash"}, "Only endpoint and recipe identity may be persisted; no worker secrets")
        endpoint = urlsplit(execution["endpoint"])
        require(endpoint.scheme == "https" or endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1", "Worker requires HTTPS; loopback HTTP for synthetic tests only")
        require(endpoint.hostname and not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment and endpoint.path in ("", "/"), "Invalid worker origin")
        import re
        require(isinstance(execution["identity_hash"], str) and re.fullmatch(r"[a-f0-9]{64}", execution["identity_hash"]), "Worker identity must be frozen")
    limits = value.get("limits", {})
    require(finite(limits.get("max_cost")) and limits["max_cost"] >= 0, "Invalid budget")
    for key, minimum, maximum in (("max_seconds", 1, 86400), ("max_parallel", 1, 2), ("max_revisions", 0, 2), ("min_cell", 2, 10000)):
        require(type(limits.get(key)) is int and minimum <= limits[key] <= maximum, "Invalid authorized resource limit: " + key)
    require(isinstance(limits.get("currency"), str) and limits["currency"], "Budget currency required")
    model = value.get("model", {})
    require(isinstance(model, dict) and not any(k in model for k in ("api_key", "token", "secret")), "Only environment variable names may store credentials")
    if permissions["model"]:
        endpoint = urlsplit(model.get("base_url", ""))
        require(endpoint.scheme == "https" or endpoint.scheme == "http" and endpoint.hostname in ("127.0.0.1", "localhost", "::1"), "Model endpoint requires HTTPS (HTTP only on loopback)")
        require(endpoint.hostname in permissions["allowed_hosts"] and not endpoint.username and not endpoint.password and not endpoint.query, "Model endpoint not authorized or contains credentials")
        require(bool(model.get("model")) and identifier(model.get("key_env")), "Model identity and key environment name required")
        require(all(finite(model.get(k)) and model[k] > 0 for k in ("input_per_million", "output_per_million")), "Configure positive provider prices before paid calls")
        require(type(model.get("max_input_bytes")) is int and 1000 <= model["max_input_bytes"] <= 100000, "Invalid input byte limit")
        require(type(model.get("max_output_tokens")) is int and 100 <= model["max_output_tokens"] <= 16000, "Invalid output limit")
        require(type(model.get("timeout")) is int and 1 <= model["timeout"] <= 300, "Invalid HTTP timeout")
    profile = value.get("profile", {})
    require(profile.get("name") in ("apa7", "ica", "cssci", "custom"), "Unknown target profile")
    require(isinstance(profile.get("sources"), list), "Profile sources must be a list")
    for source in profile["sources"]:
        require(source.get("kind") in ("official", "editorial", "observed", "suggestion"), "Profile source classification required")
        require(isinstance(source.get("url"), str) and source["url"].startswith("https://") and bool(source.get("accessed_at")), "Profile source URL and access date required")
        require(isinstance(source.get("requirements", []), list) and all(isinstance(r, dict) and isinstance(r.get("code"), str) for r in source.get("requirements", [])), "Target requirements must be typed rule objects")
    safe_text({k: value[k] for k in ("theme", "objective", "name", "language")})
    return value


def validate_protocol(value, book, corpus):
    require(isinstance(value, dict) and value.get("schema_version") == 2, "Protocol schema_version must be 2")
    require(isinstance(value.get("rq"), str) and value["rq"].strip(), "Protocol research question required")
    require(value.get("inference") == "association", "v0.2 survey adapter supports association, not causal identification")
    require(value.get("missing") == "complete_case", "Only explicit complete-case missing strategy supported")
    require(isinstance(value.get("results_seen_before_freeze"), str) and value["results_seen_before_freeze"].strip(), "Disclose prior exposure to results; freezing is not preregistration")
    theory = value.get("theory", {})
    require(all(isinstance(theory.get(k), str) and theory[k].strip() for k in ("contribution", "competing_explanation", "boundary")), "Theory contribution, competing explanation and boundary required")
    evidence = {span["id"] for item in corpus.get("items", []) for span in item.get("spans", []) if span.get("status") == "supported"}
    require(isinstance(theory.get("evidence_ids"), list) and theory["evidence_ids"] and set(theory["evidence_ids"]) <= evidence, "Theory must reference supported, located literature evidence")
    candidates = value.get("candidates", [])
    require(isinstance(candidates, list) and len(candidates) <= 3, "At most three candidate directions")
    for candidate in candidates:
        require(all(isinstance(candidate.get(k), str) and candidate[k] for k in ("rq", "theory_tension", "measurement", "boundary")), "Each candidate needs theory, measurement and boundary")
    validate_analysis_contract(value, book)
    return value


def validate_analysis_contract(value, book):
    """Statistical contract only; never certifies literature or human approval."""
    require(isinstance(value, dict) and value.get("schema_version") == 2, "Protocol schema_version must be 2")
    require(value.get("inference") == "association", "Survey adapter supports association only")
    require(value.get("missing") == "complete_case", "Only explicit complete-case strategy supported")
    columns = book.get("columns", {})
    require(isinstance(value.get("models"), list) and value["models"], "At least one approved model required")
    ids = set()
    for model in value["models"]:
        require(identifier(model.get("id")) and model["id"] not in ids, "Unique model ID required")
        ids.add(model["id"])
        require(model.get("family") in ("ols", "wls", "logit"), "Unsupported statistical adapter")
        require(model.get("role") in ("primary", "robustness", "exploratory"), "Model role required")
        require(model.get("y") in columns and columns[model["y"]].get("type") == "number", "Outcome must map to a numeric codebook variable")
        predictors = model.get("x")
        require(isinstance(predictors, list) and predictors and len(set(predictors)) == len(predictors) and model["y"] not in predictors, "Distinct predictor list required")
        require(all(x in columns and columns[x].get("type") in ("number", "category") for x in predictors), "Predictors must map to numeric/category variables")
        require(model.get("covariance") in ("classical", "HC3", "cluster"), "Unsupported covariance")
        require(model["family"] == "ols" or model["covariance"] != "HC3", "HC3 is supported only for unweighted OLS")
        if model["family"] == "wls":
            require(model.get("weight") in columns and model.get("weight_kind") == "inverse_variance", "WLS requires explicitly justified inverse-variance weights, not survey weights")
            require(bool(model.get("weight_justification")), "Weight justification required")
        if model["family"] != "wls":
            require(not model.get("weight"), "Weighted GLM/OLS requires a separately validated adapter")
        if model["covariance"] == "cluster":
            require(model.get("cluster") in columns, "Cluster variable required")
        for x in predictors:
            if columns[x]["type"] == "category":
                require(model.get("reference", {}).get(x) in columns[x].get("allowed", []), "Category reference group required")
    require(any(m["role"] == "primary" for m in value["models"]), "Primary model required")
    require(isinstance(value.get("exclusions", []), list), "Exclusions must be declared")
    for rule in value.get("exclusions", []):
        require(rule.get("column") in columns and rule.get("op") in ("eq", "ne", "gt", "lt") and bool(rule.get("reason")), "Exclusion rule requires a known column, operator and reason")
    safe_text(value)
    return value
