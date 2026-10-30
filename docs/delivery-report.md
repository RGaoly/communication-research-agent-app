# MVP交付与验证记录

日期：2026-10-28（用户时区Asia/Shanghai）。版本0.1.0。本地分支 `feat/communication-research-agent`，基线 `ff5d430d726063a574ce6f242eb852f2dbe4c361`。未推送远端、未创建PR、未安装全局Skill、未处理真实参与者数据。

以上为初次本地交付时的状态。用户随后明确授权“新建一个github project然后提交”，因此新增独立私有仓库 [RGaoly/communication-research-agent](https://github.com/RGaoly/communication-research-agent)，发布目标分支为 `main`。新远端名为 `publish`，原 `origin` 及原仓库不修改；项目运行工具本身仍不包含推送或投稿动作。

## 实际改动

| 路径 | 交付内容 |
|---|---|
| `skills/communication-research-agent/SKILL.md` | 主协调入口；理论、测量、数据质量、因果边界与人工核查原则 |
| `skills/communication-research-agent/references/` | 七类研究模块，加工具契约和四类扩展契约 |
| `skills/communication-research-agent/scripts/cra.py` | Python标准库CLI；初始化、状态、验证、OLS示例、核查登记、阶段推进、规范切换 |
| `examples/run_demo.py` | 固定种子、60条模拟媒体调查观测、全链路产物生成；不签署人工审核 |
| `examples/synthetic-project/` | 实际运行得到的数据/代码本/方案/表图/正文/数字清单/结果/日志/报告 |
| `tests/test_cra.py` | 45项隔离测试；测试签名明确为TEST ONLY，不是研究审核 |
| `README.md`、`docs/usage.zh-CN.md` | 中文快速开始、操作、参数、阶段、恢复与限制 |
| `docs/implementation-plan.md` | 检查基线、分期计划、实现取舍与后续优先级 |
| `pyproject.toml`、`.gitignore` | Python版本/零运行依赖声明，排除临时项目与缓存 |

原 `skills/empirical-paper-writing/SKILL.md` 与基线字节一致。旧能力继续可用，新入口将固定三个RQ、全局黑白、统一中文文献排序改为依研究/目标而定，不删减理论和数据质量要求。

## 测试结果

| 检查 | 实际执行 | 结果 |
|---|---|---|
| 系统Python | Python3.9.6，`python3 -m unittest discover -s tests -v` | 45/45通过 |
| 预置Python | Python3.12.14，同一unittest测试集 | 45/45通过 |
| 官方Skill校验器 | `skill-creator/scripts/quick_validate.py` | `Skill is valid!` |
| 端到端生成 | `python3 examples/run_demo.py examples/synthetic-project` | 成功，N=60，模拟标记保留 |
| CLI完整核查 | `cra.py validate examples/synthetic-project --full` | automatic_status=pass，findings=[] |
| 续跑状态 | `cra.py status examples/synthetic-project` | stage=design，complete=false，无伪造人工核查 |
| 差异卫生 | `git diff --check` | 通过 |

官方格式校验器需要PyYAML；已只在忽略的`work/qa-deps`安装PyYAML6.0.3供该项QA使用。应用、示例和45项测试均无需第三方运行依赖。未验证所有Python版本、操作系统或外部科研软件。

模拟结果：工作样本/模型完整案例N=60，b约0.384257，经典SE约0.065979，R²约0.369006。它们来自固定种子的伪观测，只证明工具链执行一致，不能当作学术发现；不报告p值或CI。

损坏输入覆盖：样本/模型N不符，输入哈希过期，b/se/t代数不符，内部一致但与CSV重算不符的系数，非有限JSON/SVG数字，表格漏映射/改数，SVG点数/坐标变化，未知或缺失的图表/数字/文献引用，DOI无效/重复，代码本版本/类别/量尺/重复ID，敏感声明/模式，匿名字段，阶段跳跃/伪提前审核，自动错误下登记pass，变更后审核失效，初始化/分析覆盖，符号链接/越界路径，锁冲突和日志修改/截断。

## 自动与人工结论

自动通过仅表示契约覆盖范围内的一致性。报告保留六项人工核查required，overall_status=needs_human_review。没有将程序检查偷换为研究质量认证。

仍需人核查：理论与文献缺口、题项/翻译和测量等值、样本真实性与研究伦理、自由文本隐私和重识别、模型/标准误/稳健性、所有未标记数字/引文与图形语义、来源是否确实支持论点、最新投稿指南与Word/PDF匿名/排版、作者贡献和AI使用披露。

## 剩余事项与非目标

1. 尚无真实授权研究的现场验收。应先以脱敏真实项目验证理论—测量—数据—写作衔接，不能将模拟测试视为研究效度证据。
2. 复杂抽样/加权/聚类、多层/SEM、跨国等值、信息实验和LLM样本只有接入边界与参考要求，没有专用分析实现；外部模型不会自动重算。
3. DOI/文献真实性无联网核验；完整APA7、中文期刊规范、ICA当期要求及Word/PDF导出/匿名元数据仍需人处理。SSCI/CSSCI不是统一格式。
4. 所有源文件共用快照导致重审较保守。未来可增加阶段依赖图、模式迁移及崩溃事务恢复。当前日志哈希链不抗整体恶意重写，review不验证身份。
5. 没有自主多智能体研究、远端推送或自动投稿。此次交付为主Skill和本地工具MVP，不宣称这些能力已存在。

初次交付可在本地审阅并运行，补丁另交付，未尝试远端写入。后续向上述新私有仓库的发布依照用户追加授权执行；未向原仓库推送。
