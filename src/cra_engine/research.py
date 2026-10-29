"""Evidence-backed drafting and reviews. Model text cannot supply computed statistics."""
import re

from .common import EngineError, digest, require, safe_text


def create_claims(analysis, language="zh-CN"):
    claims = []
    for model in analysis["models"]:
        n_text = "%s complete-case N = %d" if language.startswith("en") else "%s 模型完整案例 N = %d"
        claims.append({"id": model["id"] + "_n", "kind": "statistic", "source": "analysis", "model": model["id"], "field": "n", "value": model["n"], "text": n_text % (model["id"], model["n"])})
        for index, parameter in enumerate(model["parameters"]):
            ident = model["id"] + "_b" + str(index)
            template = "%s / %s: b = %.6f, SE = %.6f, 95%% CI [%.6f, %.6f], p = %.6g" if language.startswith("en") else "%s 的 %s：b = %.6f，SE = %.6f，95%% CI [%.6f, %.6f]，p = %.6g"
            claims.append({"id": ident, "kind": "statistic", "source": "analysis", "model": model["id"], "term": parameter["term"],
                           "field": "estimate", "value": parameter["estimate"], "reported": parameter, "text": template %
                           (model["id"], parameter["term"], parameter["estimate"], parameter["se"], parameter["ci_low"], parameter["ci_high"], parameter["p"])})
    return {"schema_version": 2, "analysis_hash": digest(analysis), "items": claims}


def validate_narrative(value, corpus, claims):
    require(isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip() for k in ("introduction", "theory", "discussion", "limitations")), "Narrative sections incomplete")
    refs = {r["id"]: r for r in corpus["items"]}
    claim_ids = {c["id"] for c in claims["items"]}
    for section in value.values():
        require(isinstance(section, str), "Narrative fields must be strings")
        safe_text(section)
        citations = re.findall(r"\[\[cite:([\w-]+)\]\]", section)
        for ident in citations:
            require(ident in refs and refs[ident]["metadata"]["status"] in ("verified", "declared") and any(s["status"] == "supported" for s in refs[ident]["spans"]), "Unknown/unverified/unsupported narrative citation")
        for ident in re.findall(r"\{\{claim:([\w-]+)\}\}", section):
            require(ident in claim_ids, "Narrative requested an unknown computed claim")
        stripped = re.sub(r"\[\[cite:[\w-]+\]\]|\{\{claim:[\w-]+\}\}", "", section)
        require(not re.search(r"\d", stripped), "Narrative numbers must use supplied claim anchors; model-generated statistics refused")
        # Narrow, explicit limitation phrases must not trip the causal-claim
        # keyword check. Other causal clauses in the same sentence remain checked.
        stripped = re.sub(r"\bdoes not identify (?:a |the )?causal effect\b", "", stripped, flags=re.I)
        stripped = re.sub(r"(?:不能|无法)(?:据此)?(?:识别|推断|证明)因果效应", "", stripped)
        require(not re.search(r"导致|证明了|因果效应|causes?\b|proves?\b|causal effect", stripped, re.I), "Causal language exceeds survey adapter scope")
    for key in ("introduction", "theory"):
        require(re.search(r"\[\[cite:[\w-]+\]\]", value[key]), "Theory/introduction require a located supported reference")
    return value


def render_draft(protocol, analysis, corpus, claims, narrative, synthetic, language="zh-CN"):
    mapping = {c["id"]: c["text"] + " [[stat:" + c["id"] + "]]" for c in claims["items"]}
    def materialize(text):
        return re.sub(r"\{\{claim:([\w-]+)\}\}", lambda m: mapping[m[1]], text)
    results = "\n\n".join(c["text"] + " [[stat:" + c["id"] + "]]" for c in claims["items"])
    conclusions = []
    for model in analysis["models"]:
        if model["role"] != "primary":
            continue
        for index, parameter in enumerate(model["parameters"]):
            if parameter["term"] == "const":
                continue
            interpretation = "区间包含零，当前证据不足以明确条件关联的方向；这不证明不存在关联" if parameter["ci_low"] <= 0 <= parameter["ci_high"] else ("估计区间位于零以上，呈正向条件关联" if parameter["estimate"] > 0 else "估计区间位于零以下，呈负向条件关联")
            conclusions.append(mapping[model["id"] + "_b" + str(index)] + "。" + interpretation + "。")
    conclusion = "\n\n".join(conclusions) + "\n\n以上回答受当前测量、样本与模型限制，不识别因果关系，也不能直接推广到总体。"
    abstract = "围绕“" + protocol["rq"] + "”，使用冻结方案中的模型与完整案例策略，报告条件关联及其不确定性。" + (conclusions[0] if conclusions else "当前证据不足，不能补造研究发现。") + "理论贡献、效度与外部适用性仍须研究者结合证据核查。"
    cited = set(re.findall(r"\[\[cite:([\w-]+)\]\]", "\n".join(narrative.values())))
    references = "\n".join("- [[ref:%s]] %s (%s). %s. %s. %s" % (r["id"], "; ".join(r["authors"]), r["year"], r["title"], r["source"], r["url"]) for r in corpus["items"] if r["id"] in cited and r["metadata"]["status"] in ("verified", "declared"))
    text = ("# " + protocol["rq"] + "\n\n" + ("**模拟数据 Synthetic data；仅用于工程验证，无真实受访者或实证贡献。**\n\n" if synthetic else "") +
            "## 摘要\n\n" + abstract + "\n\n" +
            "## 引言\n\n" + materialize(narrative["introduction"]) + "\n\n## 理论与研究问题\n\n" + materialize(narrative["theory"]) +
            "\n\n## 方法\n\n完整案例分析；估计对象为条件关联，不作因果识别。计划冻结前结果接触情况：" + protocol["results_seen_before_freeze"] +
            "\n\n模型类型、变量、参照组、标准误、排除与缺失均见 analysis.json 和冻结方案。\n\n## 结果\n\n[[Table:T1]] 报告主分析及已批准的其他规格；[[Figure:F1]] 呈现各系数及置信区间。\n\n" + results +
            "\n\n零结果与区间较宽的估计均保留，不以显著性筛选规格。\n\n## 结论\n\n" + conclusion + "\n\n## 讨论\n\n" + materialize(narrative["discussion"]) +
            "\n\n## 限制\n\n" + materialize(narrative["limitations"]) +
            "\n\n## 透明性与AI使用\n\n统计由本地适配器执行；文字与自动评审可能由配置的模型协助。人工终审另行记录。资料许可、抽样代表性和内容效度须由研究者核实。\n\n## 参考文献\n\n" + references + "\n")
    if language.startswith("en"):
        conclusions = []
        for model in analysis["models"]:
            if model["role"] == "primary":
                for index, p in enumerate(model["parameters"]):
                    if p["term"] != "const":
                        interpretation = "The interval includes zero; it does not establish absence of association." if p["ci_low"] <= 0 <= p["ci_high"] else "The interval excludes zero in this conditional association model; it does not identify causation."
                        conclusions.append(mapping[model["id"] + "_b" + str(index)] + ". " + interpretation)
        conclusion = "\n\n".join(conclusions)
        abstract = "This study addresses: " + protocol["rq"] + ". The frozen analysis uses complete cases and estimates conditional associations. " + (conclusions[0] if conclusions else "The available evidence is insufficient for a finding.") + " Measurement validity, theoretical contribution and external scope require researcher assessment."
        text = ("# " + protocol["rq"] + "\n\n" + ("**Synthetic data for engineering validation only; no real participants or empirical contribution.**\n\n" if synthetic else "") +
                "## Abstract\n\n" + abstract + "\n\n## Introduction\n\n" + materialize(narrative["introduction"]) +
                "\n\n## Theory and research question\n\n" + materialize(narrative["theory"]) +
                "\n\n## Methods\n\nComplete-case analysis of conditional associations, without causal identification. Prior exposure to results: " + protocol["results_seen_before_freeze"] +
                "\n\nModel families, coding, reference levels, covariance estimators, exclusions and sample flow are in analysis.json and the frozen protocol.\n\n## Results\n\n[[Table:T1]] reports all approved specifications. [[Figure:F1]] shows coefficients and confidence intervals.\n\n" + results +
                "\n\nNull and imprecise estimates are retained. Coefficients from different model families have different units and must not be directly compared.\n\n## Conclusions\n\n" + conclusion +
                "\n\n## Discussion\n\n" + materialize(narrative["discussion"]) + "\n\n## Limitations\n\n" + materialize(narrative["limitations"]) +
                "\n\n## Transparency and AI use\n\nStatistics were executed locally. Prose and automated reviews may use the configured model. Human final review is recorded separately. Data permissions, sampling scope and validity require researcher verification.\n\n## References\n\n" + references + "\n")
    return {"schema_version": 2, "language": language, "text": text, "narrative": narrative, "analysis_hash": digest(analysis), "limits": "Internal evidence-marked draft; human entailment, methods, and target-format review remain required"}


def review_evidence(draft, claims, corpus, analysis):
    issues = []
    if claims["analysis_hash"] != digest(analysis) or draft["analysis_hash"] != digest(analysis):
        issues.append({"code": "stale_numbers", "severity": "blocking", "location": "draft", "evidence": "analysis hash differs", "resolution": "Rebuild claims and draft"})
    text = draft["text"]
    for claim in claims["items"]:
        if claim["text"] + " [[stat:" + claim["id"] + "]]" not in text:
            issues.append({"code": "claim_missing", "severity": "blocking", "location": claim["id"], "evidence": "canonical claim not in draft", "resolution": "Restore canonical computed text"})
    known = {r["id"]: r for r in corpus["items"]}
    for ident in set(re.findall(r"\[\[cite:([\w-]+)\]\]", text)):
        ref = known.get(ident)
        if not ref or ref["metadata"]["status"] not in ("verified", "declared") or not any(s["status"] == "supported" for s in ref["spans"]):
            issues.append({"code": "unsupported_citation", "severity": "blocking", "location": ident, "evidence": "metadata or located support missing", "resolution": "Verify source and support or remove assertion"})
    return {"role": "evidence_review", "origin": "deterministic", "issues": issues,
            "limits": "Checks registered assertions, not all natural-language entailment; final human reading required"}


def method_review(protocol, analysis, audit):
    issues = []
    approved = {m["id"]: m for m in protocol["models"]}
    for model in analysis["models"]:
        if model["id"] not in approved or model["family"] != approved[model["id"]]["family"]:
            issues.append({"code": "protocol_deviation", "severity": "blocking", "location": model["id"], "evidence": "model differs from frozen plan", "resolution": "Execute approved plan or seek material-change approval"})
        if model["diagnostics"]["condition_number"] > 1000:
            issues.append({"code": "ill_conditioned", "severity": "warning", "location": model["id"], "evidence": "high design condition number", "resolution": "Inspect scaling/collinearity and disclose"})
    issues += audit.get("issues", [])
    return {"role": "method_review", "origin": "deterministic", "issues": issues,
            "limits": "Recipe/diagnostic checks are not independent methodological certification"}


def validate_review(value, role):
    require(isinstance(value, dict) and isinstance(value.get("issues"), list), "Reviewer must return issues array")
    for issue in value["issues"]:
        require(issue.get("severity") in ("blocking", "warning", "info"), "Review severity invalid")
        require(all(isinstance(issue.get(k), str) and issue[k].strip() for k in ("code", "location", "evidence", "resolution")), "Every review issue needs location, evidence and resolution")
    return {"role": role, "origin": "model", "issues": value["issues"]}
