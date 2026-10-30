# v0.2 自主研究引擎使用说明

版本0.2.0a1为开发预览。当前没有使用真实调查数据或真实付费模型完成产品验收；请先在模拟材料上验证环境。工程测试中的TEST ONLY声明不代表真实研究者审核。

## 安装与两代入口

推荐Python3.12。使用独立虚拟环境安装`.[engine]`；测试再加`test`。运行`cra --version`或`python -m cra_engine --version`。未安装统计依赖仍可使用原版`python3 skills/communication-research-agent/scripts/cra.py`。原Skill、原脚本和45项原测试保留。

`cra init PROJECT`创建schema2的新目录，拒绝覆盖；`cra init PROJECT --schema 1`仍可创建旧项目。console入口遇到schema1项目时交给原脚本解析，保持旧参数和退出码。新命令用于schema2。所有路径须为真实规范路径，项目内不接受符号链接。

## 从模拟材料开始

```sh
python examples/run_engine_demo.py work/demo-v2
cra plan work/demo-v2
cra doctor work/demo-v2
cra approve work/demo-v2 --scope authorization --reviewer '实际核查人' --note '说明你实际检查了哪些授权与边界'
cra run work/demo-v2
cra approve work/demo-v2 --scope protocol --reviewer '实际核查人' --note '说明你实际检查了哪些方案与限制'
cra resume work/demo-v2
cra reproduce work/demo-v2
cra export work/demo-v2 --working
```

生成160条固定种子伪观测、模拟工程说明、方案和离线写作材料。不会调用模型或批准任何人工检查。首轮运行停在计划冻结；第二轮运行停在成果终审。确认没有阻断问题后由真实研究者执行`approve --scope final`。模拟成果始终标记为模拟，不可作为实证发现投稿。

## 真实项目输入

先`cra init PROJECT --name '研究名称'`，填写下列文件：

| 文件 | 内容 |
|---|---|
| `brief.json` | theme、objective、语言、数据路径、模型、预算、权限和目标规范 |
| `data/input.csv` | 脱敏后的分析副本；原始数据另行只读保留 |
| `data/codebook.json` | 列名/类型/量尺/类别/敏感标志，题项与构念说明 |
| `literature/references.json` | 文献题录、元数据核查声明与可定位支持片段 |
| `protocol/plan.json` | 离线时由研究者准备；模型获授权并通过契约测试时可自主提出 |
| `manuscript/narrative.json` | 离线写作材料；使用模型写作时无需此文件 |

CSV与代码本列严格对应。`number/category/id/text`均需`sensitive:false`；类别声明`allowed`，ID不得重复或缺失。数值为空表示缺失，不自动识别99/NA等特殊编码。`min/max`为有限数值；超量尺、非法类别与疑似敏感内容阻断，不静默清洗。

代码本可声明`scales:[{id,items,reverse}]`：按已声明锚点反向编码，完整题项均值合成，报告alpha和校正题项—其余题项相关。负相关会阻断，要求检查编码或构念结构。alpha不等于内容效度、单维度或跨国可比性。`descriptive_weight:{column,kind,justification}`支持survey/frequency/inverse_probability加权均值，但不生成复杂调查方差。`design.psu/strata`及无证据的跨国潜变量均值比较会阻断当前适配器。

## 文献与证据

```sh
cra literature PROJECT --import-file references.bib
cra literature PROJECT --import-file references.ris
cra literature PROJECT --query 'media trust survey' --rows 10
```

导入不会覆盖同ID文献，也不会将题录标为内容核验通过。联网检索需要项目授权、`literature_network:true`和`allowed_hosts`含`api.crossref.org`。没有本地文献时，运行中的corpus任务也可按theme检索Crossref，将题录缓存到`literature/search-results.json`；没有授权全文/证据时不能继续理论论断。

每项文献须含`id/title/authors/year/source/url`，可选doi。在线核对题名、可用出版年份与首作者姓；离线可登记`metadata_declaration:{reviewer,note}`，这是人工声明而非独立认证。DOI不存在不是自动错误，不补造。

证据例：

```json
{"id":"spanA","path":"literature/article.pdf","locator":{"page":3},"quote":"实际存在于该页的原文片段","claim":"该片段支持的有边界论断","status":"supported","reviewer":"真实核查人","note":"说明为什么原文支持该论断","permitted_for_model":true}
```

Markdown/TXT使用`locator.paragraph`（从1计，按空行分段）。引文必须实际出现在位置上；保存源文件哈希。status可为supported/pending/contradicted。模型上下文只包含获授权且supported的片段；定位不等于语义支持，最终仍需研究者检查。引用、文件和搜索结果中的指令不能赋予工具权限。

## 研究方案与统计契约

方案包含schema_version2、rq、inference=`association`、missing=`complete_case`、results_seen_before_freeze，以及theory的contribution/competing_explanation/boundary/evidence_ids。可有最多3个候选方向，不固定最终RQ数量。既有数据冻结不能称为事前预注册。

每个model含id、family、role、y、x列表、covariance。family为ols/wls/logit，role为primary/robustness/exploratory；类别预测变量明确reference。OLS支持classical/HC3/cluster；Logit支持classical/cluster；WLS仅支持有理由的inverse_variance权重，不能将调查权重偷换为方差权重。聚类少于30时当前自动适配器停止，交方法审阅或另一个已验证适配器；这是一项保守运行边界，不是通用统计定理。

exclusions逐条说明column、op(eq/ne/gt/lt)、value和reason，保留每步计数；缺失策略明确，模型N逐一报告。完全分离、不收敛、奇异设计、无变异和非有限结果停止，不做显著性搜索。所有规格尝试（包括失败）保存在本地数据库与导出的规格账本。调整后R²、普通R²和McFadden伪R²分别登记。

## 连接用户模型

在brief中显式启用`permissions.model`并列出模型主机。model填写`base_url/model/key_env/input_per_million/output_per_million/max_input_bytes/max_output_tokens/timeout`。只保存环境变量名，不保存密钥。HTTPS为默认要求，仅本机localhost/127.0.0.1可使用HTTP进行测试。输入/输出单价必须为正，预算货币由用户统一；不硬编码供应商价格。当前language支持zh/zh-CN与en/en-US/en-GB，数值段落和结构相应切换。

```sh
export CRA_API_KEY='你的实际密钥'
cra plan PROJECT
cra approve PROJECT --scope authorization --reviewer '实际核查人' --note '说明授权的模型主机、摘要外传与费用上限'
cra model-test PROJECT
cra run PROJECT
```

model-test实际执行受限echo工具往返和JSON输出检查，会占预算。通过前不能自主使用该模型。模型身份/配置变化需要重新授权和测试；同协议不代表同能力。密钥不会进入worker环境或成果包。

规划、写作、方法审阅和证据审阅分开上下文执行；只开放受控JSON任务，不给模型shell或批准工具。模型稿件必须使用`{{claim:ID}}`引用计算数字，不能自己打数字；引文用`[[cite:ID]]`，只可引用支持证据。规则检查不理解全部自然语言，审阅模型与最终人工通读均保留。

## 目标规范规则

`profile.sources`按official/editorial/observed/suggestion分类，记录url与accessed_at。每项可声明`requirements`，如`{"code":"required_sections","value":["摘要","方法"]}`、`{"code":"anonymous","value":true}`、`{"code":"max_words","value":8000}`或max_nonspace_characters。只有official规则失败会作为格式阻断；其他来源只作建议。默认scope=all，以当前内部稿全文计数，不自动模拟期刊排除参考文献等特殊口径。max_pages等未支持规则与其他scope明确留为人工核对，不假装已验证。

## 状态、权限、预算与恢复

```sh
cra status PROJECT --json
cra evidence PROJECT
cra evidence PROJECT --id analysis
cra budget PROJECT
cra pause PROJECT
cra resume PROJECT
```

`approve`需要真实交互终端并输入当前证据短语，没有`--yes`；不会认证身份。authorization绑定brief，protocol绑定数据/代码本/文献/方案，final绑定分析/稿件/评审。文字修改不使既有分析过期；相关上游变化会按依赖使下游失效。

默认单项目一个调度进程，顺序执行任务（不超过授权的2个并发上限）。单次运行7200秒，模型调用和统计任务受剩余时间限制。相同错误两次停止；文字实质修订最多两轮；临时文献网络故障最多重试两次。暂停在安全点生效，HTTP在已授权超时内结束；统计子进程可被终止。执行中不要同时修改文件。

SQLite事务保存对象版本、事件、任务、租约、预算和人工声明。崩溃遗留的running任务可恢复，尚未确定结果的付费请求转为uncertain；不会盲目重发。人核对账单后运行`cra budget PROJECT --resolve CALL_ID --actual 金额`并在终端确认。事件哈希链检测一般修改/截断，不对抗同时重写整个数据库的攻击。

`run/resume`成功返回0也可能在等人；自动化调用必须读JSON中的readiness/tasks/approvals，不能仅凭退出码判断研究完成。退出码1用于验证/重建/发布检查失败，2用于输入/权限/执行条件错误。受控任务被阻断时返回项目状态，详细原因在last_problem；原schema1退出码不变。

## 复现、导出、迁移与发布

```sh
cra reproduce PROJECT
cra export PROJECT --working
cra export PROJECT --include-data
cra migrate OLD_PROJECT --dry-run
cra migrate OLD_PROJECT
cra release-check PROJECT --pilot-registry pilots.json --software-report docs/v0.2/validation.json
```

成果包版本化写入exports，不覆盖源数据。默认不包含数据；`--include-data`仅在你有共享授权时使用。包括Markdown/DOCX、CSV/SVG、结果/方案/证据、规格账本、依赖版本、recipe源码、reproduce.py和哈希清单。不包含密钥、环境变量或控制数据库。复现包须提供同哈希授权输入，运行`python reproduce.py /授权输入.csv`。不要在不安全环境盲目执行来源不明研究包。

DOCX是带内部引文键的可编辑稿；未实现完整APA7/GB/T、自动引文样式和图内排版。PDF不属于默认输出；版式、匿名元数据和当期目标规范须人审。中文渲染需系统CJK字体，macOS默认Hiragino Sans GB，其他系统默认Noto Serif CJK SC。模型文本和多模型意见不保证逐字复现；统计按相对1e-7/绝对1e-9容差比较。

迁移先只读检查，再完整备份旧目录。旧核查只保留为历史声明，新批准从零开始；旧结果不变成已验证新结果。迁移后填写brief和研究材料。迁移不自动启用模型或网络。

发布检查需要与当前源码哈希/版本绑定、无失败或跳过的软件报告，以及至少3个非模拟、获授权项目，分别有研究负责人与方法审阅者声明、证据包哈希、独立复现和专家证据检查。没有这些材料就返回release_eligible=false；报告和登记表本身也只是声明。方法/性能指标、真实模型效果、Linux隔离与人工科研质量验收仍需单独证据，不用测试分数替代。
