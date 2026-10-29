#!/usr/bin/env python3
"""Build an explicitly synthetic, offline project. Never signs human reviews."""
import argparse
import csv
import importlib.util
import io
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "skills/communication-research-agent/scripts/cra.py"
spec = importlib.util.spec_from_file_location("cra", CLI)
cra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cra)


def build(project):
    project = project.absolute()
    args = cra.parser().parse_args(["init", str(project), "--synthetic", "--name", "模拟媒体接触与信任调查", "--extension", "survey"])
    cra.initialize(project, args)
    rng = random.Random(20261028)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["study_id", "exposure", "trust", "group"])
    for i in range(60):
        x = (i % 10) / 3
        y = 2.0 + 0.4 * x + rng.uniform(-0.8, 0.8)
        writer.writerow(["S%03d" % i, "%.6f" % x, "%.6f" % y, "A" if i % 2 else "B"])
    cra.write_text(project / "data/input.csv", stream.getvalue())
    cra.write_json(project / "data/codebook.json", {"schema_version": 1, "columns": {
        "study_id": {"type": "id", "sensitive": False, "question": "模拟研究编号，非真实身份"},
        "exposure": {"type": "number", "sensitive": False, "min": 0, "max": 4, "question": "模拟媒体接触指标"},
        "trust": {"type": "number", "sensitive": False, "min": 1, "max": 5, "question": "模拟媒体信任指标"},
        "group": {"type": "category", "sensitive": False, "allowed": ["A", "B"], "question": "模拟组别，不代表国家或处理"}}})
    evidence = {
        "design": "# 模拟设计\n\n工程演示，不构成真实理论贡献。RQ：模拟接触与模拟信任如何关联？不作因果推断。60个伪观测，固定种子20261028，无真实参与者。将来真实研究需先核验文献缺口、伦理与精度依据。\n",
        "measurement": "# 模拟测量\n\n人为生成两个连续指标和组别。没有真实问卷来源或量表效度证据，不能称为有效量表；不作跨国比较。代码本列明量尺和编码。\n",
        "data-audit": "# 模拟审计\n\n生成60行，保留60行，排除0行，缺失0，无权重。A/B各30行，不是随机实验或人口组别，无真实招募或识别字段。\n",
        "analysis": "# 演示分析\n\nRQ使用含截距的一元OLS，x=exposure，y=trust，完整案例，经典同方差SE，无权重/聚类，无p值/CI。只演示数字对照，不作因果或实质推断。复现：python3 skills/communication-research-agent/scripts/cra.py analyze PROJECT --x exposure --y trust。未实施研究级稳健性检验。\n",
        "submission": "# 模拟提交清单\n\nprofile=apa7。仅工程演示，不可作为实证论文投稿。官方入口：https://apastyle.apa.org/style-grammar-guidelines 。示例日期2026-10-28，不声称已逐条人工核查排版、文献或目标要求。无作者署名、基金、伦理编号和外部提交。\n",
    }
    for name, content in evidence.items():
        cra.write_text(project / ("protocol/" + name + ".md"), content)
    state = cra.load_state(project)
    args = cra.parser().parse_args(["analyze", str(project), "--x", "exposure", "--y", "trust"])
    cra.analyze(project, state, args)
    cra.record(project, state, "demo_generate", "synthetic_only")
    results = cra.read_json(project / "artifacts/results.json")
    claims, sentences = [], []
    for ident, source, label, decimals in (
        ("sample", "sample_n", "工作数据样本 N", 0),
        ("modelN", "models.m1.n", "完整案例模型 N", 0),
        ("slope", "models.m1.b", "斜率 b", 3),
        ("stderr", "models.m1.se", "经典标准误 SE", 3),
        ("rsquare", "models.m1.r2", "模型 R²", 3)):
        value = round(cra.lookup(results, source), decimals)
        text = label + " = " + format(value, ".%df" % decimals)
        claims.append({"id": ident, "source": source, "value": value, "decimals": decimals, "text": text})
        sentences.append(text + " [[stat:" + ident + "]]")
    cra.write_json(project / "artifacts/claims.json", claims)
    # Empty bibliography deliberately avoids inventing academic literature in a toy example.
    cra.write_json(project / "references.json", [])
    manuscript = ("# 模拟数据：媒体接触与信任的工具链演示\n\n"
                  "这是固定种子生成的模拟数据，没有真实受访者、有效量表或理论检验；不能作为实证发现。\n\n"
                  "方法：含截距的一元OLS，完整案例，经典同方差SE，无p值或CI。\n\n"
                  "表1展示模型数字 [[Table:T1]]；图1展示模拟点的分布 [[Figure:F1]]。\n\n" +
                  "。\n\n".join(sentences) + "。\n\n"
                  "图1：x轴为模拟接触指标（0–4），y轴为模拟信任指标（1–5）；点为模拟观测，来源为固定种子生成代码。表1：经典同方差标准误，N为完整案例，不含显著性星号。\n\n"
                  "结论：程序按预设关联生成结果，只验证工程一致性。没有文献综述或参考文献，不作科学贡献、因果、跨国或总体代表性推断。\n")
    cra.write_text(project / "manuscript/draft.md", manuscript)
    report = cra.validate(project, state, "submission")
    cra.record(project, state, "demo_validate", report["automatic_status"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="新的独立输出目录")
    args = parser.parse_args()
    try:
        report = build(args.project)
    except (cra.CRAError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"automatic_status": report["automatic_status"], "overall_status": report["overall_status"],
                      "project": str(args.project.absolute()), "human_reviews": "未签署；由真实研究者核查"}, ensure_ascii=False, indent=2))
    return 0 if report["automatic_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
