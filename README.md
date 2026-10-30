# Communication Research Agent

**v0.2.0a5.dev5 自主研究引擎正在准备开发预览更新。** 它能保存任务、证据和预算，在研究者授权及计划冻结后执行调查分析、生成稿件、组织方法与证据复核，并输出带复现入口的研究包。此次候选增加独立统计服务器适配；远程任务只有在服务器隔离自检通过、研究者明确授权分析副本传输后才会运行。原 v0.1 标准库工具继续可独立使用。

当前版本是开发预览：模拟数据、数值测试和本机模型协议测试不能替代真实研究验收。尚未完成三个获授权真实项目的专家试点，不应宣称已达到正式发布门槛。

[下载 v0.2.0a4 Alpha 安装包](https://github.com/RGaoly/communication-research-agent/releases/tag/v0.2.0a4) · [本版修复、验证范围与未完成项](docs/acceptance/preview-a4.md)

开发分支正在准备 `0.2.0a5.dev4` 独立统计执行候选：保留研究工作台，增加按项目明确授权的分析副本传输、隔离统计服务、持久任务编号、取消、未知任务恢复及结果核对。尚未取得目标服务器配置，未切换公开部署，不能把本机测试描述为完整云端验收。[部署与验收](docs/REMOTE_STATISTICS_ZH.md)。[dev1 同包两端 191 项验证](docs/acceptance/readiness-a5-dev1.md)与[dev0 历史记录](docs/acceptance/readiness-a5.md)分别保存；历史证据不能用于宣称当前候选已通过相同验证。

## 浏览器研究工作台 / Streamlit Community Cloud

云端预览已上线：https://communication-research-agent-rgaoly.streamlit.app/ 。当前Community Cloud实例真实隔离自检失败，自动统计保持禁用；不能把页面上线表述为云端研究闭环已经通过。本机版可双击 `启动研究工作台.command`，使用持久研究库；密钥仍在页面填写。

在Python 3.12环境显式安装 `pip install '.[engine,ui]'`，本机执行 `CRA_DEPLOYMENT=local python -m streamlit run streamlit_app.py`。云端入口也是 `streamlit_app.py`，默认标记云端处理，先获得用户明确同意再展示材料上传控件。密钥按浏览器会话与项目配置隔离，不采用共享服务器密钥，不写入项目或恢复文件。

所有展示的N、系数、任务与费用来自后台记录；未生成和过期结果明确区分。云端隔离能力必须部署后实际自检，失败则停止统计；不保证Community Cloud内核允许运行。临时空间不能代替持久存储，请下载私有恢复备份。[完整使用、部署及边界说明](docs/STREAMLIT_WORKSPACE_ZH.md)。

## 图形界面填写模型密钥

macOS 双击仓库内的 **启动模型配置.command**。其他已安装环境运行 `cra-gui`，浏览器会自动打开本机页面。填写密钥、保存配置，随后测试连接并执行小任务，无需配置密钥环境变量。仅本机服务接收请求，API Key 不写入浏览器存储、项目配置或费用日志；费用账本保留以防刷新后重复计费。

当前试用授权上限为 **2 次真实生成调用、5 美元**。页面显示用量、预留、费用待核对状态；未知请求不自动重发。这个界面是模型连接与小任务入口，研究项目仍须依次授权、冻结计划和终审；它不能代签这些批准。见 [图形界面使用说明](docs/acceptance/gui.zh-CN.md)。

## 验收工具

`cra-accept` 提供候选安装包绑定、30 组独立数值对账、100 次实际进程故障注入、边界和错误植入检查；`cra release-check` 读取实际证据包及外部可信评审签名。纯“通过”声明或合成试点不能正式放行。详见 [验收执行手册](docs/acceptance/README.zh-CN.md)。

## v0.2 安装与快速开始

建议使用 Python 3.12，在独立环境显式安装；引擎不会自行安装或升级依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[engine,test]'
.venv/bin/python examples/run_engine_demo.py work/demo-v2
.venv/bin/cra plan work/demo-v2
.venv/bin/cra doctor work/demo-v2
```

模拟生成器只准备材料，不创建人工批准、不调用付费模型。检查材料后在真实终端依次完成：

```sh
.venv/bin/cra approve work/demo-v2 --scope authorization --reviewer '实际核查人' --note '实际核查依据与授权范围'
.venv/bin/cra run work/demo-v2
.venv/bin/cra approve work/demo-v2 --scope protocol --reviewer '实际核查人' --note '已检查当前方案与研究边界'
.venv/bin/cra resume work/demo-v2
.venv/bin/cra status work/demo-v2 --json
.venv/bin/cra export work/demo-v2 --working
```

每次批准都要求交互输入绑定当前证据的确认短语；没有 `--yes`。成果终审使用 `--scope final`，通过后才能导出终审版；这仍不执行投稿。`--working` 导出明确标注的工作稿。

支持 macOS Seatbelt 与 Linux bubblewrap 隔离后端。运行时自检必须确认宿主网络、控制数据库读取和越界写入均被拒绝；隔离不可用则停止自动统计，不退回无限制运行。已发布 Alpha 的范围以其固定验证记录为准；开发候选的 Linux 工程集成另行保存，CI 不能代替独立真人验收。

## v0.2 新能力

- SQLite事务状态、任务DAG、证据依赖、历史版本、进程中断恢复与未知费用暂停。
- 项目授权、计划冻结、成果终审三个确认点；文字变化只使受影响的稿件和评审过期。
- CSV审计、量表反向编码与一致性诊断、加权描述、OLS/WLS/Logit、HC3与单维聚类标准误。
- Crossref检索与题名/年份/首作者核对，BibTeX/RIS导入，PDF页码或文本段落证据定位。
- 用户自带密钥的兼容模型适配器、工具与JSON能力测试、按调用预算预留、独立角色审阅和有限修订。
- 规范结果生成数字声明、CSV表和SVG系数区间图；模型不能自行填入统计数字。
- Markdown/DOCX、证据索引、全部规格尝试、环境与可携带复现代码；默认不打包数据。
- 旧项目迁移预览/备份和显式发布门槛检查。

文献缺少可定位支持时会停止理论写作，不能以题录代替全文；题录自动发现后仍需授权全文与证据。DOCX保留内部引文键，完整APA7、目标排版与语义审查仍由研究者处理。不同模型或角色的意见不等于科学证据。

- [详细使用与数据契约](docs/v0.2/usage.zh-CN.md)
- [产品需求与实现追踪](docs/v0.2/requirements.md)
- [架构、隔离与恢复](docs/v0.2/architecture.md)
- [验证记录与发布剩余事项](docs/v0.2/acceptance.md)

## v0.1 独立核查工具

从“从0到1高标准论文写作 Skill”升级的传播学实证研究工作流：主协调 Skill + 按需参考模块 + 本地 Python 验证工具 + 阶段状态与审计记录。先保证研究问题、理论贡献、测量效度和数据质量，再分析与写作；禁止捏造，不把关联默认写成因果。

原版 [`skills/empirical-paper-writing/SKILL.md`](skills/empirical-paper-writing/SKILL.md) 保持原文，可继续独立使用。新入口为 [`skills/communication-research-agent/SKILL.md`](skills/communication-research-agent/SKILL.md)，研究范围不限于国家形象或元知觉。

## 三分钟跑通

在本仓库目录执行，需要 Python 3.9+；工具与测试仅使用标准库，不需要 pip install：

```sh
python3 examples/run_demo.py work/my-first-demo
python3 skills/communication-research-agent/scripts/cra.py status work/my-first-demo
python3 skills/communication-research-agent/scripts/cra.py validate work/my-first-demo --full
python3 -m unittest discover -s tests -v
```

第一个命令生成60条固定种子的**模拟数据**、OLS结果、CSV表、SVG图、正文声明与验证报告。正确结果为 `automatic_status: pass`、`overall_status: needs_human_review`；这表示程序检查通过，人工事项仍未核查。示例不会自动签署审核或投稿，已有目录会被拒绝覆盖。可直接查看[已生成的示例](examples/synthetic-project/)和[检查报告](examples/synthetic-project/reports/validation.json)。

## 能做什么

| 能力 | 当前实现 |
|---|---|
| 研究协调 | 研究设计、测量与问卷、数据分析、解释写作、语言质量、投稿规范、诚信复现七类参考模块 |
| 规范切换 | `apa7` / `ica` / `cssci` / `custom`；SSCI/CSSCI具体目标以期刊作者指南为准 |
| 项目状态 | 六个阶段、必需产物、证据快照、人工核查声明、变更后失效、断点续跑 |
| 数据预检 | 代码本列对应、N、缺失、重复ID、有限数值/量尺/类别、声明敏感变量和部分敏感模式 |
| 数字检查 | 样本/模型N、b/se/t、p/R²范围、内置一元OLS重算、结果与表格/正文声明/散点坐标对照 |
| 引用检查 | 显式图表/统计声明/文献标记双向覆盖、基础文献字段、DOI格式与重复 |
| 审计 | 输入与产物哈希、串联日志、项目日志头、单写进程锁、阻断记录 |
| 扩展 | survey / cross-national / information-experiment / llm-sample 的声明式接口和外部模型契约 |

## 在 Codex / Cursor 中使用

直接要求 Agent 读取新 Skill 的完整路径，并对独立研究项目执行当前阶段工作。也可将新 Skill 文件夹复制到你使用工具的 skills 目录；其中参考模块与CLI均自包含。不要同时启用新旧入口处理同一项目，以免固定结构与新路由冲突。此升级不会自动安装到用户全局环境。

示例请求：

> 请读取 skills/communication-research-agent/SKILL.md，接手我的媒体信任调查。先盘点材料和理论缺口，在 research-projects/media-trust 创建独立项目，采用具体目标期刊的规范；先检查问卷与数据质量，不能编造文献或把相关解释为因果，人工核查由我完成。

## 使用边界

这是 Agent 研究指导与离线一致性工具的最小版本，不是自主科研系统。内置统计仅为一元OLS（经典同方差SE、完整案例，无p值/CI），高级分析需外部软件与人工重跑。正文检查依赖显式标记，不解析Word/PDF或识别全部自然语言引文。敏感内容扫描会误报/漏报；自动检查不证明数据/文献真实、因果识别有效或完全匿名。`review` 是本地研究者声明，不能认证其身份。投稿profile不等于完整APA7/中文期刊排版。

完整说明与交付记录：

- [中文使用说明与阶段操作](docs/usage.zh-CN.md)
- [机器可读契约与自动/人工边界](skills/communication-research-agent/references/tool-contract.md)
- [实施计划、基线与实际改动](docs/implementation-plan.md)
- [测试与交付结果](docs/delivery-report.md)
- [未来研究类型扩展](skills/communication-research-agent/references/extensions.md)

本地运行不会上传数据、推送Git或自动投稿；初始化与分析默认拒绝覆盖现有工作。
