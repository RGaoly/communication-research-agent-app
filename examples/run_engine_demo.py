#!/usr/bin/env python3
"""Prepare synthetic v2 materials. Never creates human approvals or calls a model."""
import argparse
import csv
import random
from pathlib import Path

from cra_engine.common import atomic, load, save
from cra_engine.store import initialize


def protocol():
    return {"schema_version": 2, "rq": "模拟媒体接触与信任的关联如何呈现", "inference": "association", "missing": "complete_case",
            "results_seen_before_freeze": "工程模拟，已知数据生成机制；不构成事前预注册或实证发现",
            "theory": {"contribution": "仅验证研究流程，不宣称理论贡献", "competing_explanation": "预设生成机制及模拟随机扰动",
                       "boundary": "模拟数据不能代表真实受访者", "evidence_ids": ["span_note"]},
            "candidates": [{"rq": "模拟接触与信任的关联", "theory_tension": "仅为工程验证，不是文献缺口", "measurement": "人为生成连续指标", "boundary": "非真实调查"}],
            "models": [{"id": "main", "family": "ols", "role": "primary", "y": "trust", "x": ["exposure"], "covariance": "HC3"}], "exclusions": []}


def narrative():
    return {"introduction": "这是用于检验工具链的模拟研究，文献材料也只是一份工程说明。[[cite:method_note]]",
            "theory": "模拟设计帮助测试证据映射，不提供新的传播理论证据。[[cite:method_note]]",
            "discussion": "观察到的关联来自预设生成方式。{{claim:main_b1}} 不能据此推断真实社会机制，零结果也必须保留。",
            "limitations": "未使用真实受访者，没有经过量表效度、抽样代表性或跨国等值性验证；不能作为实证论文提交。"}


def prepare(root, model_url=None):
    root = Path(root).absolute()
    initialize(root, "模拟传播调查引擎演示", synthetic=True)
    rng = random.Random(20261028)
    with (root / "data/input.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["study_id", "exposure", "trust", "binary", "group", "cluster", "weight"])
        for index in range(160):
            x = rng.uniform(0, 4)
            y = 2 + 0.3 * x + rng.gauss(0, 0.5)
            binary = int(rng.random() < 1 / (1 + __import__("math").exp(-(-0.5 + 0.4 * x))))
            writer.writerow(["S%03d" % index, "%.6f" % x, "%.6f" % y, binary, "A" if index % 2 else "B", "C%02d" % (index % 40), "%.6f" % (1 + rng.random())])
    columns = {"study_id": {"type": "id", "sensitive": False}, "exposure": {"type": "number", "sensitive": False, "min": 0, "max": 4, "question": "模拟接触量"},
               "trust": {"type": "number", "sensitive": False, "min": -2, "max": 8, "question": "模拟信任值"}, "binary": {"type": "number", "sensitive": False, "min": 0, "max": 1},
               "group": {"type": "category", "sensitive": False, "allowed": ["A", "B"]}, "cluster": {"type": "id", "sensitive": False}, "weight": {"type": "number", "sensitive": False, "min": 1, "max": 2}}
    # Cluster IDs repeat by design, so they are categories, not respondent identifiers.
    columns["cluster"] = {"type": "category", "sensitive": False, "allowed": ["C%02d" % i for i in range(40)]}
    save(root / "data/codebook.json", {"schema_version": 2, "columns": columns})
    brief = load(root / "brief.json")
    brief.update(theme="媒体接触与信任的模拟工具链", objective="验证研究执行、证据映射和停止机制")
    brief["profile"]["sources"] = [{"kind": "official", "url": "https://apastyle.apa.org/style-grammar-guidelines", "accessed_at": "2026-10-28", "note": "工程示例定位入口，不构成完整排版审核"}]
    brief["data"]["recruited_n"] = None
    if model_url:
        from urllib.parse import urlsplit
        brief["permissions"].update(model=True, allowed_hosts=[urlsplit(model_url).hostname])
        brief["model"].update(base_url=model_url, model="fixture-model", input_per_million=1, output_per_million=2)
        brief["limits"]["max_cost"] = 1
    save(root / "brief.json", brief)
    quote = "本文件是工程测试说明，只能用于验证模拟数据的流程，不能作为真实学术文献或理论贡献证据。"
    atomic(root / "literature/method-note.md", quote + "\n")
    save(root / "literature/references.json", [{"id": "method_note", "title": "模拟工具链工程说明", "authors": ["Synthetic fixture author"], "year": "2026", "source": "Local synthetic engineering fixture", "url": "https://example.invalid/synthetic-fixture",
        "metadata_declaration": {"reviewer": "TEST FIXTURE ONLY", "note": "工程模拟说明，非真实研究文献，无学术核验效力"},
        "spans": [{"id": "span_note", "path": "literature/method-note.md", "locator": {"paragraph": 1}, "quote": quote,
                   "claim": "该材料只是一份工程说明", "status": "supported", "reviewer": "TEST FIXTURE ONLY", "note": "仅核对本地模拟文件内容，不代表真实学术核查", "permitted_for_model": True}]}])
    if not model_url:
        save(root / "protocol/plan.json", protocol())
        save(root / "manuscript/narrative.json", narrative())
    return root


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    root = prepare(args.project)
    print("Prepared explicitly synthetic materials:", root)
    print("Next: cra plan PROJECT; inspect and approve authorization; cra run PROJECT")
