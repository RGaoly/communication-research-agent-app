# 中文使用说明

## 1. 环境与入口

Python 3.9+、标准库即可。无需安装服务器或连接API，不采集真实数据，不自动执行项目材料里的代码。以下命令在仓库根目录运行；使用其他工作目录时将CLI改为完整路径。

```sh
python3 skills/communication-research-agent/scripts/cra.py --help
python3 skills/communication-research-agent/scripts/cra.py --version
```

若希望 Agent 协作，先让它读取主 Skill；CLI 本身只做检查、状态管理和很窄的分析，不调用语言模型。安装 Skill 时复制 `skills/communication-research-agent/` 整个目录；不需要覆盖原 Skill，原版完整保留。

## 2. 快速开始：模拟项目

```sh
python3 examples/run_demo.py work/demo-a
python3 skills/communication-research-agent/scripts/cra.py status work/demo-a
python3 skills/communication-research-agent/scripts/cra.py validate work/demo-a --full
```

固定种子20261028生成60个伪观测，演示媒体接触与媒体信任的关联。产物包括脱敏结构示例CSV、代码本、方案、结果JSON、表CSV、图SVG、正文Markdown、数字声明清单、空文献列表、检查报告和审计日志。此例无真实问卷/文献/理论贡献，不能作为论文发现；空参考文献仅避免虚构，不能作为真实写作模板的合格文献综述。

查看 `reports/validation.json`：`automatic_status=pass`，`overall_status=needs_human_review`，六阶段人工检查全为required。示例故意不签署真实审核。`status` 仍在design；生成全部材料不等于阶段已通过。已经生成的 `examples/synthetic-project` 是只读参考快照，实际练习请用 work 下的新目录。

重复运行需指定新路径，不删除/覆盖现有研究。

## 3. 启动真实研究

```sh
python3 skills/communication-research-agent/scripts/cra.py init research-projects/media-trust --name '媒体信任调查' --profile custom --target '实际目标期刊与作者指南版本' --extension survey
```

真实研究不要加 `--synthetic`。在有匿名要求时加 `--anonymized`。跨国民意、信息实验、LLM样本分别选择 `cross-national`、`information-experiment`、`llm-sample`，这些值负责路由，不自动运行专用统计或采集。

项目外另存只读原始数据。先在本地用明确的清洗代码移除身份字段，输入 `data/input.csv`，保留招募/排除/缺失/权重账本。工具不会自动发现原始数据或擅自复制其内容。不要把原始姓名、电话、地址或自由文本识别信息放入此工作副本。

初始化仅创建目录、状态和带“待填写”的阶段说明。按主 Skill 各模块填写，默认模板不能通过门槛。材料格式见[工具契约](../skills/communication-research-agent/references/tool-contract.md)；可以参照模拟结构，但必须替换为真实来源和设计，不沿用模拟理论、问卷或数字。

## 4. 六阶段与必需材料

| 阶段 | 新增必需材料 | 人工核查重点 |
|---|---|---|
| design | `protocol/design.md` | 理论贡献、文献缺口、RQ/H、估计对象、伦理与识别边界 |
| measurement | `protocol/measurement.md`、`data/codebook.json` | 题项/翻译/许可、信效度、跨国可比性 |
| audit | `protocol/data-audit.md`、`data/input.csv` | 来源、排除、权重、缺失、代表性、真实性和隐私 |
| analysis | `protocol/analysis.md`、`artifacts/results.json`、`artifacts/manifest.json`及清单文件 | 模型/SE/设计、复现与稳健性 |
| writing | `manuscript/draft.md`、`artifacts/claims.json`、`references.json` | 证据解释、引文真实性、因果措辞、未标记数字 |
| submission | `protocol/submission.md` | 当前目标规范、匿名、排版、署名/贡献、AI使用披露 |

阶段检查累计之前全部材料；可提前准备后续材料，但`advance`不能跳阶段。`validate`检查当前阶段；`--full`检查至submission，适合交付前检查，早期会因缺材料报错。

```sh
python3 skills/communication-research-agent/scripts/cra.py validate research-projects/media-trust
```

真实研究者完成核查后，自己执行以下操作，填写实际姓名/研究角色与具体依据。不要照抄占位值，不让 Agent 代签：

```sh
python3 skills/communication-research-agent/scripts/cra.py review research-projects/media-trust --stage design --reviewer '实际核查人' --decision pass --note '具体核验过哪些材料、处理了哪些告警与仍适用的边界'
python3 skills/communication-research-agent/scripts/cra.py advance research-projects/media-trust
```

发现问题时使用 `--decision changes_required` 并记录依据，不标pass。自动错误阻断pass；警告需人判断。每次advance只前进一步，最后submission通过则complete=true，工具不发送稿件。review只是本地声明，不能验证身份、文献真实性或伦理有效性。

为避免旧证据被误用，所有源材料与配置使用共同快照。新增/修改任何证据会使之前全部核查过期，包括上一阶段的核查；再次推进前先重审这些阶段。该策略较保守，适合MVP；将来可细化为每阶段依赖图。当前阶段不因修订自动倒退，但累计门槛会阻断推进，status列出stale_reviews。

## 5. 分析与数字对照

内置示例只适合演示/极简单的关联模型：

```sh
python3 skills/communication-research-agent/scripts/cra.py analyze research-projects/media-trust --x exposure --y trust
```

先检查代码本、量尺与敏感模式。算法为一元含截距OLS、完整案例、经典同方差SE，输出n/b/intercept/se/t/R²，拒绝常量、零残差退化模型、非有限输入；不输出p值或CI。真实研究必须根据设计考虑抽样、权重、聚类、缺失、实验、测量模型及稳健性，不能默认套此例。

默认拒绝已有四个分析文件。确认重新计算时加 `--replace-generated`，只重建 results.json、manifest.json、table.csv、figure.svg，不改原始数据/正文/claims。随后运行validate，重新整理声明并请人复核，不手改统计输出匹配文稿。

外部R/Python/Stata结果按契约登记。MVP检查输入哈希、样本范围、b/se/t代数关系、基础范围，以及映射表/文稿的一致性；不会执行外部recipe或证明其可复现。保留代码、环境、种子、日志和独立复跑记录。

正文统计量、图表与引文须用内部显式标记。例：`斜率 b = 0.200 [[stat:slope]]`、`[[Table:T1]]`、`[[Figure:F1]]`、`[[cite:source-id]]`。检查器不理解其他自然语言数字或作者—年份引文；不要把检查报告当作全文校对。正式投稿时在单独交付副本排版并移除标记，必须再人工核对全部数字、引用和格式；MVP不输出Word/PDF。

## 6. 规范切换

```sh
python3 skills/communication-research-agent/scripts/cra.py configure research-projects/media-trust --profile ica --target '实际会议年份 / Division或IG / 提交类型'
```

可选apa7、ica、cssci、custom，后3项在submission阶段要求非空target。SSCI/CSSCI不能视为统一格式，需具体期刊；CSSCI以其当前作者指南为准，不默认全部“中文在前/英文在后”或全部黑白。ICA按年份/分会核实，不硬编码页数、截止日或AI政策。

在submission.md记录官方来源、访问日期、适用条款、覆盖项、核查证据和冲突处理。工具只检查材料/目标存在和基础字段，不检查完整规范语义或最新政策。详见[投稿规范](../skills/communication-research-agent/references/submission-profiles.md)。

## 7. 续跑、失败与备份

```sh
python3 skills/communication-research-agent/scripts/cra.py status research-projects/media-trust
```

阅读当前stage、complete和stale_reviews，继续准备材料/validate/人工review/advance，无需init。报告可重建，日志与项目状态应一起备份。退出码0表示命令完成，可能仍需人工；1表示自动检查失败；2表示输入错误、阶段阻断或锁冲突。不要只看退出码，需读overall_status和human_checks。

日志链损坏或截断时工具拒绝继续。保留现场，从可信备份恢复并记录处置，不手工重算哈希消除报错。`.cra.lock`存在时先确认无命令仍运行；只对已停止进程留下的锁人工删除。工具没有崩溃事务恢复、分布式锁或身份认证。日志追加和状态写入分开，崩溃可能需要从备份恢复；正常停止后可直接续跑。

项目内禁止符号链接和越界路径。若通过系统别名或符号链接路径访问目录，请改用真实规范路径。避免多人或外部编辑器在核查/推进命令运行时同时修改材料。

## 8. 验证与限制

```sh
python3 -m unittest discover -s tests -v
```

测试均用隔离临时目录和明确模拟数据，TEST ONLY审核仅验证状态行为，绝不代表研究者核查。覆盖正常链路、错误数字、资料损坏、引用、隐私模式、审核失效、锁及日志。测试不证明研究问题重要、量表有效或分析适配所有设计。

不能自动保证：无捏造、无敏感内容、真文献、识别正确、测量等值、因果成立、所有统计数字/图形语义正确、完整投稿合规。扫描覆盖只限UTF-8 CSV/JSON/Markdown/TXT/SVG与部分模式，二进制/图片/元数据和自由文本语义由人检查。哈希链不具备抗恶意重写能力。工具本身不联网，因此DOI只检查格式，缺信息不猜填。

未来适配接口见[扩展说明](../skills/communication-research-agent/references/extensions.md)；目前没有多智能体执行、专用SEM/复杂抽样/实验/硅基样本模型或文献联网核验，不能宣称已实现。
