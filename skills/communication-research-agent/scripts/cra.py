#!/usr/bin/env python3
"""Communication Research Agent MVP. Python 3.9+, standard library only.

Offline checks establish consistency, never research truth or privacy clearance.
See docs/contracts.md for the intentionally narrow machine-readable contract.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

VERSION = "0.1.0"
STAGES = ("design", "measurement", "audit", "analysis", "writing", "submission")
PROFILES = ("apa7", "ica", "cssci", "custom")
EXTENSIONS = ("survey", "cross-national", "information-experiment", "llm-sample")
REQUIRED = {
    "design": ["protocol/design.md"],
    "measurement": ["protocol/measurement.md", "data/codebook.json"],
    "audit": ["protocol/data-audit.md", "data/input.csv"],
    "analysis": ["protocol/analysis.md", "artifacts/results.json", "artifacts/manifest.json"],
    "writing": ["manuscript/draft.md", "artifacts/claims.json", "references.json"],
    "submission": ["protocol/submission.md"],
}
HUMAN = {
    "design": "理论贡献、文献缺口、RQ/H、识别边界、伦理与预注册适用性",
    "measurement": "题项来源/授权、认知访谈、翻译、信效度及跨组测量等值性",
    "audit": "样本来源、同意与隐私、排除规则、权重/抽样、数据真实性",
    "analysis": "模型/标准误/缺失策略适切性、可复现性、稳健性、无选择性报告",
    "writing": "未标记数字/引用、图表解释、文献真实性、因果边界、语言准确性",
    "submission": "当期征稿、匿名/元数据、格式、作者贡献、AI披露、共享许可",
}


class CRAError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(root, rel):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise CRAError("项目文件路径必须是非空相对路径")
    path = root / rel
    if root not in path.resolve().parents or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise CRAError("拒绝越界路径或符号链接")
    return path


def write_text(path, value):
    """Atomic writes; callers decide whether replacement is allowed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".cra-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (ValueError, UnicodeError) as exc:
        raise CRAError("JSON 内容无效：" + path.name) from exc


def require(condition, message):
    if not condition:
        raise CRAError(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def integer(value):
    return type(value) is int and value >= 0


@contextmanager
def locked(root):
    path = root / ".cra.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise CRAError("项目被锁定；确认没有进程运行后再删除 .cra.lock") from exc
    try:
        os.close(fd)
        yield
    finally:
        path.unlink()


def check_paths(root):
    for path in root.rglob("*"):
        require(not path.is_symlink(), "项目内不接受符号链接")


def load_state(root):
    check_paths(root)
    state = read_json(root / "project.json")
    require(isinstance(state, dict) and state.get("schema_version") == 1, "不支持的项目版本")
    require(state.get("stage") in STAGES and state.get("profile") in PROFILES, "项目阶段/规范无效")
    require(isinstance(state.get("reviews"), dict) and type(state.get("complete")) is bool, "项目状态字段无效")
    require(state.get("extension") in EXTENSIONS, "扩展接口无效")
    require(type(state.get("synthetic")) is bool and type(state.get("anonymized")) is bool, "项目声明无效")
    require(isinstance(state.get("target"), str), "投稿目标字段无效")
    return state


def fingerprint(root, state):
    files = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and rel != "project.json" and rel != ".cra.lock" and not rel.startswith(("logs/", "reports/")):
            files[rel] = file_hash(path)
    config = {k: state[k] for k in ("schema_version", "profile", "extension", "synthetic", "anonymized", "target")}
    return digest({"config": config, "files": files})


def check_log(root, state):
    path = root / "logs/audit.jsonl"
    previous = None
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                signature = event.pop("hash")
                require(event["previous"] == previous and signature == digest(event), "审计日志哈希链损坏")
                previous = signature
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise CRAError("审计日志无法读取") from exc
    require(previous == state.get("audit_head"), "审计日志与项目头不匹配（可能截断）")


def record(root, state, action, outcome):
    event = {"at": now(), "action": action, "outcome": outcome,
             "snapshot": fingerprint(root, state), "previous": state.get("audit_head")}
    event["hash"] = digest(event)
    with (root / "logs/audit.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
    state["audit_head"] = event["hash"]
    write_json(root / "project.json", state)


def initialize(root, args):
    require(not root.exists(), "初始化拒绝覆盖已有目录；请使用新的项目路径")
    root.mkdir(parents=True)
    for directory in ("protocol", "data", "artifacts", "manuscript", "logs", "reports"):
        (root / directory).mkdir()
    state = {"schema_version": 1, "tool_version": VERSION, "created_at": now(),
             "name": args.name, "profile": args.profile, "target": args.target,
             "extension": args.extension, "synthetic": args.synthetic,
             "anonymized": args.anonymized, "stage": STAGES[0], "complete": False,
             "reviews": {}, "audit_head": None}
    for stage in STAGES:
        path = REQUIRED[stage][0]
        if path.endswith(".md"):
            write_text(root / path, "# " + stage + "\n\n待填写：" + HUMAN[stage] + "。\n")
    write_text(root / "manuscript/draft.md", "# 论文草稿\n\n待填写：结果必须有可追溯证据。\n")
    write_json(root / "project.json", state)
    record(root, state, "init", "created")
    return {"project": str(root), "stage": state["stage"]}


def read_data(root):
    path = resolve(root, "data/input.csv")
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames
            require(fields and len(fields) == len(set(fields)) and all(fields), "CSV 列名为空或重复")
            rows = list(reader)
            require(rows and all(None not in row and all(v is not None for v in row.values()) for row in rows), "CSV 为空或行列数不一致")
    except (csv.Error, UnicodeError) as exc:
        raise CRAError("CSV 格式无效") from exc
    book = read_json(root / "data/codebook.json")
    require(isinstance(book, dict) and book.get("schema_version") == 1 and isinstance(book.get("columns"), dict), "代码本须为 schema_version=1 且含 columns 对象")
    require(set(book["columns"]) == set(fields), "代码本与 CSV 列名不一致")
    return fields, rows, book


def data_checks(root, add):
    fields, rows, book = read_data(root)
    missing = {}
    for field in fields:
        spec = book["columns"][field]
        require(isinstance(spec, dict) and spec.get("type") in ("number", "category", "id", "text"), "代码本变量类型无效")
        require(type(spec.get("sensitive")) is bool, "每个变量必须显式声明 sensitive 布尔值")
        if spec["sensitive"]:
            add("sensitive_column", "error", "存在标记为敏感的变量；请先本地脱敏再纳入工作副本")
        miss = 0
        seen = set()
        for row in rows:
            value = row[field].strip()
            if not value:
                miss += 1
                continue
            if spec["type"] == "number":
                try:
                    numeric = float(value)
                    valid = math.isfinite(numeric)
                    if "min" in spec:
                        require(number(spec["min"]), "min 必须是有限数值")
                        valid = valid and numeric >= spec["min"]
                    if "max" in spec:
                        require(number(spec["max"]), "max 必须是有限数值")
                        valid = valid and numeric <= spec["max"]
                except ValueError:
                    valid = False
                if not valid:
                    add("invalid_value", "error", "数值非有限、无法解析或超出代码本量尺；不回显原值")
            if spec["type"] == "category":
                require(isinstance(spec.get("allowed"), list) and spec["allowed"], "类别变量需声明非空 allowed")
                if value not in spec["allowed"]:
                    add("invalid_category", "error", "类别值不在代码本枚举内")
            if spec["type"] == "id" and value in seen:
                add("duplicate_id", "error", "ID 重复；需核实重复填答或改用复合 ID")
            seen.add(value)
        missing[field] = miss
        if miss:
            add("missing_values", "warning", "有缺失值；模型需申明分析样本与缺失策略")
        if miss and spec["type"] == "id":
            add("missing_id", "error", "ID 不得为空")
    return {"n_rows": len(rows), "n_columns": len(fields), "missing_counts": missing}


def privacy_scan(root, state, add):
    # Heuristic only: no values or matching snippets enter output/logs.
    # Decimal coefficients can have 18 fractional digits. Do not misclassify a
    # fractional suffix as an ID/phone; a period after prose still counts.
    # This remains a heuristic, never a statement of complete anonymization.
    patterns = [r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", r"(?<![A-Za-z0-9])(?<!\d\.)1[3-9]\d{9}(?![A-Za-z0-9])(?!\.\d)",
                r"(?<![A-Za-z0-9])(?<!\d\.)\d{17}[\dXx](?![A-Za-z0-9])(?!\.\d)", r"(?:sk-|AKIA)[A-Za-z0-9_-]{16,}"]
    count = 0
    anonymous_hits = 0
    for directory in ("data", "manuscript", "protocol", "artifacts"):
        for path in (root / directory).rglob("*"):
            if path.is_file() and path.suffix.lower() in (".csv", ".json", ".md", ".txt", ".svg"):
                content = path.read_text(encoding="utf-8-sig")
                count += sum(len(re.findall(pattern, content)) for pattern in patterns)
                if state["anonymized"] and directory == "manuscript":
                    anonymous_hits += len(re.findall(r"(?im)^(?:作者|author|affiliation|单位)\s*[:：]", content))
    if count:
        add("possible_sensitive_content", "error", "发现疑似联系方式、证件或密钥；请本地人工核查（不回显）")
    if anonymous_hits:
        add("anonymous_identity", "error", "匿名稿含疑似作者/单位字段")
    return {"heuristic_hits": count, "coverage": "UTF-8 CSV/JSON/MD/TXT/SVG；不含二进制文件、自由文本语义或图像元数据"}


def ols(rows, x, y):
    pairs = []
    for row in rows:
        if not row[x].strip() or not row[y].strip():
            continue
        try:
            pair = (float(row[x]), float(row[y]))
        except ValueError as exc:
            raise CRAError("OLS 输入必须为数值") from exc
        require(all(math.isfinite(v) for v in pair), "OLS 输入包含非有限数")
        pairs.append(pair)
    n = len(pairs)
    require(n > 2, "OLS 至少需要三个完整观测")
    xs, ys = zip(*pairs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((v - mx) ** 2 for v in xs)
    syy = sum((v - my) ** 2 for v in ys)
    require(sxx > 0 and syy > 0, "OLS 自变量或因变量没有变异")
    b = sum((a - mx) * (b - my) for a, b in pairs) / sxx
    intercept = my - b * mx
    sse = sum((bval - intercept - b * aval) ** 2 for aval, bval in pairs)
    require(sse > 1e-20, "零残差退化模型不在演示分析支持范围内")
    se = math.sqrt(sse / (n - 2) / sxx)
    return {"n": n, "b": b, "intercept": intercept, "se": se, "t": b / se,
            "r2": max(0.0, min(1.0, 1 - sse / syy))}, pairs


def analyze(root, state, args):
    findings = []
    data_checks(root, lambda *v: findings.append(v))
    privacy_scan(root, state, lambda *v: findings.append(v))
    require(not any(v[1] == "error" for v in findings), "数据/隐私预检未通过，请先运行 validate 查看不含原值的诊断")
    fields, rows, book = read_data(root)
    require(args.x != args.y and args.x in fields and args.y in fields, "请指定两个不同的有效列")
    require(all(book["columns"][v]["type"] == "number" for v in (args.x, args.y)), "OLS 列须在代码本中声明为 number")
    paths = ["artifacts/" + name for name in ("results.json", "manifest.json", "table.csv", "figure.svg")]
    require(args.replace_generated or not any((root / p).exists() for p in paths), "分析产物已存在；显式使用 --replace-generated 才会重建这四个生成文件")
    model, pairs = ols(rows, args.x, args.y)
    results = {"schema_version": 1, "synthetic": state["synthetic"], "data_sha256": file_hash(root / "data/input.csv"),
               "recipe": {"id": "simple-ols-v1", "x": args.x, "y": args.y,
                          "missing": "complete_case", "se_type": "classical_homoskedastic"},
               "sample_n": len(rows), "models": {"m1": model}}
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["statistic", "value"])
    cells = []
    for key, value in model.items():
        writer.writerow([key, format(value, ".12g")])
        cells.append({"key": key, "source": "models.m1." + key, "decimals": 10})
    write_text(root / "artifacts/table.csv", buffer.getvalue())
    xs, ys = zip(*pairs)
    def scale(v, values):
        return 30 + 240 * (v - min(values)) / (max(values) - min(values))
    points = "".join('<circle cx="%.6f" cy="%.6f" r="2"/>' % (scale(x, xs), 300 - scale(y, ys)) for x, y in pairs)
    # Figure data are attached structurally so verification checks the plotted points.
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320" viewBox="0 0 320 320">'
           '<desc>Scatterplot of x and y; see manifest for variables and synthetic flag.</desc>'
           '<path d="M30 20 V280 H300" fill="none" stroke="black"/>' + points + '</svg>\n')
    write_text(root / "artifacts/figure.svg", svg)
    manifest = {"schema_version": 1, "items": [
        {"id": "T1", "kind": "table", "path": "artifacts/table.csv", "sha256": file_hash(root / "artifacts/table.csv"), "cells": cells},
        {"id": "F1", "kind": "figure", "path": "artifacts/figure.svg", "sha256": file_hash(root / "artifacts/figure.svg"),
         "recipe": "simple-ols-scatter-v1", "model": "m1"}]}
    write_json(root / "artifacts/results.json", results)
    write_json(root / "artifacts/manifest.json", manifest)
    return {"recipe": "simple-ols-v1", "n": model["n"], "synthetic": state["synthetic"]}


def lookup(results, key):
    require(isinstance(key, str) and key, "统计量 source 必须为非空字符串")
    value = results
    try:
        for part in key.split("."):
            value = value[part]
    except (KeyError, TypeError) as exc:
        raise CRAError("统计量 source 不存在") from exc
    require(number(value), "统计量必须为有限数值")
    return value


def tolerance(decimals):
    require(type(decimals) is int and 0 <= decimals <= 10, "decimals 必须是 0 到 10 的整数")
    return 0.5 * 10 ** (-decimals) + 1e-12


def result_checks(root, state, add):
    results = read_json(root / "artifacts/results.json")
    require(isinstance(results, dict) and results.get("schema_version") == 1, "结果 schema_version 无效")
    require(type(results.get("synthetic")) is bool and results["synthetic"] == state["synthetic"], "模拟/实证数据标记不一致")
    if results.get("data_sha256") != file_hash(root / "data/input.csv"):
        add("stale_data", "error", "结果对应的数据哈希已过期")
    _, rows, _ = read_data(root)
    require(integer(results.get("sample_n")), "sample_n 必须为非负整数")
    if results["sample_n"] != len(rows):
        add("sample_n", "error", "sample_n 与工作数据行数不一致")
    models = results.get("models")
    require(isinstance(models, dict) and models, "models 必须为非空对象")
    for model in models.values():
        require(isinstance(model, dict) and integer(model.get("n")) and 0 < model["n"] <= results["sample_n"], "模型 n 超出样本范围")
        require(all(number(v) for v in model.values()), "模型统计量必须为有限数值")
        if "se" in model:
            require(model["se"] > 0, "标准误须为正")
        if "r2" in model:
            require(0 <= model["r2"] <= 1, "本契约中 r2 须为普通 OLS R²，范围 0–1；其他模型另行扩展")
        if "p" in model:
            require(0 <= model["p"] <= 1, "p 值超出范围")
        if all(k in model for k in ("b", "se", "t")):
            if not math.isclose(model["b"] / model["se"], model["t"], rel_tol=1e-5, abs_tol=1e-7):
                add("regression_identity", "error", "b / se 与 t 不一致")
    recipe = results.get("recipe", {})
    require(isinstance(recipe, dict), "recipe 必须是对象")
    if recipe.get("id") == "simple-ols-v1":
        require(recipe.get("missing") == "complete_case" and recipe.get("se_type") == "classical_homoskedastic", "OLS recipe 声明无效")
        require(set(models) == {"m1"}, "内置 recipe 仅支持 m1")
        fields, rows, _ = read_data(root)
        require(recipe.get("x") in fields and recipe.get("y") in fields and recipe["x"] != recipe["y"], "recipe 列无效")
        expected, _ = ols(rows, recipe["x"], recipe["y"])
        require(set(models["m1"]) == set(expected), "内置 OLS 统计量字段不完整")
        for key, value in expected.items():
            if not math.isclose(value, models["m1"][key], abs_tol=1e-9, rel_tol=1e-9):
                add("recompute_mismatch", "error", "OLS 独立重算与结果不一致")
    else:
        add("external_model", "warning", "外部模型仅检查结构/代数/数字一致性；需人工重跑分析代码")
    return results


def artifact_checks(root, results, manuscript, add):
    manifest = read_json(root / "artifacts/manifest.json")
    require(isinstance(manifest, dict) and manifest.get("schema_version") == 1 and isinstance(manifest.get("items"), list) and manifest["items"], "manifest 结构无效")
    ids = set()
    for item in manifest["items"]:
        require(isinstance(item, dict) and item.get("kind") in ("table", "figure"), "产物类型无效")
        ident = item.get("id")
        require(isinstance(ident, str) and re.fullmatch(r"[TF][1-9]\d*", ident) and ident not in ids, "图表 ID 无效或重复")
        require(ident.startswith("T" if item["kind"] == "table" else "F"), "图表 ID 前缀与类型不一致")
        ids.add(ident)
        path = resolve(root, item.get("path"))
        require(path.is_file(), "清单中的图表文件不存在")
        if item.get("sha256") != file_hash(path):
            add("artifact_hash", "error", "图表文件哈希与清单不一致")
        token = "[[%s:%s]]" % ("Table" if item["kind"] == "table" else "Figure", ident)
        if manuscript is not None and token not in manuscript:
            add("uncited_artifact", "error", "清单图表未在正文中使用显式标记引用")
        if item["kind"] == "table":
            require(path.suffix == ".csv", "MVP 数字表核查只支持 statistic,value CSV")
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                require(reader.fieldnames == ["statistic", "value"], "结果表须为 statistic,value 两列")
                table_rows = list(reader)
            require(all(set(row) == {"statistic", "value"} and all(v is not None for v in row.values()) for row in table_rows), "结果表行列数不一致")
            table = {row["statistic"]: row["value"] for row in table_rows}
            cells = item.get("cells")
            require(isinstance(cells, list) and cells and all(isinstance(c, dict) and isinstance(c.get("key"), str) for c in cells), "每张表需提供 cells 映射")
            require(len(table) == len(table_rows) == len(cells) and set(table) == {cell["key"] for cell in cells}, "表格存在重复/未映射数字")
            for cell in cells:
                try:
                    actual = float(table[cell["key"]])
                except (KeyError, ValueError) as exc:
                    raise CRAError("表格数值无效") from exc
                if not math.isfinite(actual) or abs(actual - lookup(results, cell.get("source"))) > tolerance(cell.get("decimals", 3)):
                    add("table_number", "error", "表格数字与结果源不一致")
        elif item.get("recipe") == "simple-ols-scatter-v1":
            require(results.get("recipe", {}).get("id") == "simple-ols-v1" and item.get("model") == "m1", "内置图形 recipe 不匹配")
            _, rows, _ = read_data(root)
            recipe = results["recipe"]
            _, pairs = ols(rows, recipe["x"], recipe["y"])
            try:
                circles = ET.fromstring(path.read_text(encoding="utf-8")).findall("{http://www.w3.org/2000/svg}circle")
                require(len(circles) == len(pairs), "散点图点数与模型 N 不一致")
                xs, ys = zip(*pairs)
                for circle, (x, y) in zip(circles, pairs):
                    cx = 30 + 240 * (x - min(xs)) / (max(xs) - min(xs))
                    cy = 270 - 240 * (y - min(ys)) / (max(ys) - min(ys))
                    actual_x, actual_y = float(circle.attrib["cx"]), float(circle.attrib["cy"])
                    if not all(math.isfinite(v) for v in (actual_x, actual_y)) or abs(actual_x - cx) > 1e-5 or abs(actual_y - cy) > 1e-5:
                        add("figure_number", "error", "散点图坐标与数据不一致")
            except (ET.ParseError, KeyError, ValueError) as exc:
                raise CRAError("内置 SVG 图形结构无效") from exc
        else:
            add("external_figure", "warning", "外部图形仅检查存在/哈希/引用；图中数字和视觉语义需人工核查")
    if manuscript is not None:
        for kind, ident in re.findall(r"\[\[(Table|Figure):([^\]]+)\]\]", manuscript):
            found = next((i for i in manifest["items"] if i["id"] == ident), None)
            if found is None or found["kind"] != {"Table": "table", "Figure": "figure"}[kind]:
                add("unknown_artifact", "error", "正文引用了未知或类型不匹配的图表")


def writing_checks(root, state, results, add):
    manuscript = (root / "manuscript/draft.md").read_text(encoding="utf-8")
    claims = read_json(root / "artifacts/claims.json")
    require(isinstance(claims, list) and claims, "claims 必须为非空数组")
    ids = set()
    for claim in claims:
        require(isinstance(claim, dict), "claim 须为对象")
        ident = claim.get("id")
        require(isinstance(ident, str) and re.fullmatch(r"[A-Za-z][\w-]*", ident) and ident not in ids, "claim ID 无效或重复")
        ids.add(ident)
        require(number(claim.get("value")), "claim value 必须为有限数值")
        if abs(claim["value"] - lookup(results, claim.get("source"))) > tolerance(claim.get("decimals", 3)):
            add("claim_number", "error", "正文声明数字与结果源不一致")
        decimals = claim.get("decimals", 3)
        text = claim.get("text")
        expected = format(claim["value"], ".%df" % decimals)
        require(isinstance(text, str) and text and re.search(r"(?<![\d.])" + re.escape(expected) + r"(?![\d.])", text), "claim text 须含按 decimals 格式化的数字")
        if manuscript.count(text + " [[stat:" + ident + "]]") != 1:
            add("claim_anchor", "error", "正文须唯一出现 claim text 后紧跟 [[stat:ID]]")
    for ident in re.findall(r"\[\[stat:([^\]]+)\]\]", manuscript):
        if ident not in ids:
            add("unknown_claim", "error", "正文引用了未知统计声明")
    references = read_json(root / "references.json")
    require(isinstance(references, list), "references 须为数组")
    ref_ids, dois = set(), set()
    for ref in references:
        require(isinstance(ref, dict), "reference 须为对象")
        ident = ref.get("id")
        require(isinstance(ident, str) and re.fullmatch(r"[\w-]+", ident) and ident not in ref_ids, "文献 ID 无效或重复")
        ref_ids.add(ident)
        require(isinstance(ref.get("authors"), list) and ref["authors"] and all(isinstance(a, str) and a.strip() for a in ref["authors"]), "文献缺少作者")
        require(isinstance(ref.get("year"), str) and re.fullmatch(r"(?:\d{4}[a-z]?|n\.d\.)", ref["year"]), "文献年份基础格式无效")
        require(all(isinstance(ref.get(k), str) and ref[k].strip() for k in ("title", "source", "url")), "文献缺少题名/来源/核验 URL")
        require(re.fullmatch(r"https?://\S+", ref["url"]), "文献 URL 基础格式无效")
        doi = ref.get("doi")
        if doi:
            if not isinstance(doi, str) or not re.fullmatch(r"https://doi\.org/10\.\d{4,9}/\S+", doi):
                add("doi_format", "error", "DOI 应为 https://doi.org/10.xxxx/后缀；仅核查格式")
            elif doi.lower() in dois:
                add("duplicate_doi", "error", "DOI 重复；检查重复条目")
            else:
                dois.add(doi.lower())
        if ref.get("verified") is not True or not isinstance(ref.get("verification_note"), str) or not ref["verification_note"].strip():
            add("reference_unverified", "warning", "文献缺少人工核验声明/记录；不允许猜填")
    citations = set(re.findall(r"\[\[cite:([^\]]+)\]\]", manuscript))
    if citations - ref_ids:
        add("missing_reference", "error", "正文引文缺少文末条目")
    if ref_ids - citations:
        add("uncited_reference", "error", "文末条目未在正文引用")
    if re.search(r"证明了|导致|因果效应|causes?\b|causal effect|proves?\b", manuscript, re.I):
        add("causal_language", "warning", "检测到可能的因果措辞；需人工逐句检查识别设计，不自动改写")
    if state["synthetic"] and "模拟数据" not in manuscript and "synthetic" not in manuscript.lower():
        add("synthetic_label", "error", "模拟项目正文必须显式标注模拟数据")
    return manuscript


def validate(root, state, stage):
    findings = []
    def add(code, severity, message):
        item = {"code": code, "severity": severity, "message": message}
        if item not in findings:
            findings.append(item)
    index = STAGES.index(stage)
    metrics = {}
    for past in STAGES[:index + 1]:
        for rel in REQUIRED[past]:
            path = resolve(root, rel)
            if not path.is_file() or path.stat().st_size == 0:
                add("missing_evidence", "error", "缺少阶段材料：" + rel)
            elif path.suffix == ".md" and re.search(r"待填写|\bTODO\b|\bTBD\b", path.read_text(encoding="utf-8"), re.I):
                add("unfinished_evidence", "error", "阶段材料尚有占位项：" + rel)
    def checked(fn):
        try:
            return fn()
        except (CRAError, OSError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
            # No raw parser content: diagnostics must not leak respondent values.
            add("invalid_input", "error", str(exc) if isinstance(exc, CRAError) else "材料无法解析；请本地检查结构、编码及文件完整性")
    metrics["privacy"] = checked(lambda: privacy_scan(root, state, add))
    if index >= 2:
        metrics["data"] = checked(lambda: data_checks(root, add))
    if index >= 3:
        results = checked(lambda: result_checks(root, state, add))
        if results is not None:
            manuscript = None
            if index >= 4:
                manuscript = checked(lambda: writing_checks(root, state, results, add))
            checked(lambda: artifact_checks(root, results, manuscript, add))
    if index >= 5:
        if state["profile"] in ("ica", "cssci", "custom") and not state["target"].strip():
            add("submission_target", "error", "所选规范需要具体年份/分会或期刊投稿目标")
    snapshot = fingerprint(root, state)
    human = []
    for past in STAGES[:index + 1]:
        review = state["reviews"].get(past, {})
        fresh = review.get("snapshot") == snapshot and review.get("decision") == "pass"
        human.append({"stage": past, "check": HUMAN[past], "status": "recorded" if fresh else "required"})
    errors = sum(f["severity"] == "error" for f in findings)
    report = {"schema_version": 1, "tool_version": VERSION, "at": now(), "scope": stage,
              "snapshot": snapshot, "automatic_status": "fail" if errors else "pass",
              "overall_status": "blocked" if errors else ("needs_human_review" if any(h["status"] == "required" for h in human) else "review_recorded"),
              "findings": findings, "metrics": metrics, "human_checks": human,
              "limits": "通过仅表示已登记范围的一致性；不证明数据/文献真实、完全匿名或方法正确。未标记的自然语言数字/引用需人工检查。"}
    write_json(root / "reports/validation.json", report)
    return report


def review(root, state, args):
    require(len(args.reviewer.strip()) >= 2 and len(args.note.strip()) >= 8, "核查人及依据说明过短")
    require(args.stage in STAGES[:STAGES.index(state["stage"]) + 1], "不能预先审核未来阶段")
    report = validate(root, state, args.stage)
    require(args.decision != "pass" or report["automatic_status"] == "pass", "自动检查未通过，不能登记 pass")
    state["reviews"][args.stage] = {"reviewer": args.reviewer, "note": args.note,
                                    "decision": args.decision, "at": now(), "snapshot": fingerprint(root, state)}
    state["complete"] = False
    return {"stage": args.stage, "decision": args.decision, "declaration_only": True}


def advance(root, state):
    report = validate(root, state, state["stage"])
    require(report["automatic_status"] == "pass", "阶段门阻断：自动检查失败，查看 reports/validation.json")
    require(all(h["status"] == "recorded" for h in report["human_checks"]), "阶段门阻断：所需人工核查缺失或证据已变更，请重审；不能由 Agent 代签")
    if state["stage"] == STAGES[-1]:
        state["complete"] = True
    else:
        state["stage"] = STAGES[STAGES.index(state["stage"]) + 1]
    return {"stage": state["stage"], "complete": state["complete"]}


def status(root, state):
    snapshot = fingerprint(root, state)
    stale = [stage for stage, review in state["reviews"].items() if review.get("snapshot") != snapshot or review.get("decision") != "pass"]
    if stale:
        state["complete"] = False
    return {"name": state["name"], "stage": state["stage"], "complete": state["complete"],
            "stale_reviews": stale, "next": "检查当前阶段材料 → validate → 人工 review → advance",
            "snapshot": snapshot}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="在新目录初始化，不覆盖已有工作")
    init.add_argument("project", type=Path)
    init.add_argument("--name", default="Communication research")
    init.add_argument("--profile", choices=PROFILES, default="apa7")
    init.add_argument("--target", default="")
    init.add_argument("--extension", choices=EXTENSIONS, default="survey")
    init.add_argument("--synthetic", action="store_true")
    init.add_argument("--anonymized", action="store_true")
    for name in ("status", "validate", "review", "advance", "analyze", "configure"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
        if name == "validate":
            command.add_argument("--full", action="store_true", help="检查至 submission 的全部材料")
        if name == "review":
            command.add_argument("--stage", choices=STAGES, required=True)
            command.add_argument("--reviewer", required=True)
            command.add_argument("--note", required=True)
            command.add_argument("--decision", choices=("pass", "changes_required"), required=True)
        if name == "analyze":
            command.add_argument("--x", required=True)
            command.add_argument("--y", required=True)
            command.add_argument("--replace-generated", action="store_true")
        if name == "configure":
            command.add_argument("--profile", choices=PROFILES, required=True)
            command.add_argument("--target", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    root = args.project.absolute()
    try:
        require(not root.is_symlink(), "项目根不能是符号链接")
        require(root == root.resolve(), "项目路径不得包含符号链接或 ..")
        if args.command == "init":
            output = initialize(root, args)
        else:
            require(root.is_dir(), "项目目录不存在")
            with locked(root):
                state = load_state(root)
                check_log(root, state)
                # Any source change invalidates recorded completion immediately.
                if any(v.get("snapshot") != fingerprint(root, state) for v in state["reviews"].values()):
                    state["complete"] = False
                try:
                    if args.command == "status":
                        output = status(root, state)
                    elif args.command == "validate":
                        output = validate(root, state, STAGES[-1] if args.full else state["stage"])
                    elif args.command == "analyze":
                        output = analyze(root, state, args)
                    elif args.command == "review":
                        output = review(root, state, args)
                    elif args.command == "advance":
                        output = advance(root, state)
                    else:
                        state.update(profile=args.profile, target=args.target, complete=False)
                        output = {"profile": args.profile, "target": args.target, "reviews_invalidated": True}
                except CRAError:
                    record(root, state, args.command, "blocked")
                    raise
                record(root, state, args.command, output.get("automatic_status", "ok"))
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 1 if output.get("automatic_status") == "fail" else 0
    except (CRAError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        message = str(exc) if isinstance(exc, CRAError) else "文件/输入处理失败；请本地检查结构、权限和编码（不回显原始内容）"
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
