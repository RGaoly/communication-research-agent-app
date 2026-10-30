# 实施计划与基线

## 任务与保护边界

将通用实证写作Skill工程化为Communication Research Agent，先交付可运行、可测试的MVP；不替研究者判断理论、测量与真实性。保留理论贡献、问卷和跨国比较、测量效度、数据质量优先；不限定国家形象题目，不默认因果，不自动推送/上传/投稿，不覆盖用户工作。

仓库来源：https://github.com/RGaoly/empirical-paper-writing-skill

检出基线：`ff5d430d726063a574ce6f242eb852f2dbe4c361`（Add empirical journalism paper writing Cursor skill.）。原仓库只有README和`skills/empirical-paper-writing/SKILL.md`，没有脚本/测试/包配置。原Skill未改动，新增独立入口；本地工作分支 `feat/communication-research-agent`。

前文缓存未保留完整设计回复，实施依据为本次用户明确列出的五阶段要求，没有推断缺失的历史设计。

## 分期实施与验收

| 分期 | 实现路径 | 验收与当前结果 |
|---|---|---|
| 1 主协调与模块 | `skills/communication-research-agent/SKILL.md`、`references/` | 七类研究模块齐全，附工具与扩展契约；原Skill原文保留 |
| 2 可执行验证 | `scripts/cra.py` | 标准库CLI；样本/回归/图表/文稿/文献基础检查、敏感模式与日志；自动与人工分开 |
| 3 项目状态 | 同一CLI的init/status/review/advance/configure | 六阶段，累计证据门槛、快照失效、续跑、锁和审计链；不代签 |
| 4 测试/示例/说明 | `tests/test_cra.py`、`examples/`、中文docs | 模拟链路与损坏输入测试；文档说明安装、参数、退出码、边界和恢复 |
| 5 未来接口 | `references/extensions.md`、extension与外部recipe字段 | 四类声明式路由；保留版本契约，不伪装为专用分析已完成 |

## 关键取舍

- 主Skill协调研究决策，CLI只做可确定的一致性检查。零运行依赖，支持Python3.9+；采用标准库一元OLS演示，不引入未经验证的复杂统计。
- 内部Markdown显式登记数字/图表/引用，降低自然语言误提取；未标记内容明确留给人，不宣布全稿数字核查完成。
- 内置OLS可重算并检查表和散点坐标；外部模型/图形只做结构、哈希与一致性，并强制显示局限。
- 采用共同快照保守失效审核，简单可靠但重审范围较大；未来按阶段依赖图优化。
- 没有网络核验、Word/PDF排版、外部API或投稿动作。ICA/期刊当前规则由研究者查官方来源；profile用于路由。
- 哈希链检测普通篡改/截断，不能对抗同时改写状态的攻击；单进程锁防止CLI并发，不能代替数据库事务或权限控制。

## 后续优先级

1. 以一项经授权脱敏的真实研究做人工验收：理论/问卷、跨国量表和复杂抽样分析，检查工作流是否适配；不把模拟链路当作科研质量验证。
2. 扩展R/Python/Stata的分析adapter、环境锁定、样本流转账本、加权/聚类/多层模型；每个自动检查均补可失败测试。
3. 细分阶段依赖/复审范围和崩溃恢复，增加版本迁移，而非跳过现有阶段门。
4. 经授权加入DOI/来源核验、引用解析、Word/PDF排版与匿名检查；网络读取和数据上传分开设计，不自动外传研究数据。
