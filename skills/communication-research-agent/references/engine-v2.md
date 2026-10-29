# v0.2 研究执行与恢复

先读项目版本。schema2用安装后的`cra`或`python -m cra_engine`；schema1用Skill内旧脚本。迁移需`cra migrate PROJECT --dry-run`后显式执行，旧审核仅保存历史，不能转换为新批准。引擎是开发预览，软件测试不能替代真实项目和方法专家验收。

## 启动

新项目运行`cra init NEW_PROJECT`，原始数据另外只读存储。填写brief.json的主题/目标/语言/数据路径/模型与网络授权/预算/目标规范，data/input.csv与data/codebook.json提供脱敏副本和代码本。模型密钥只通过环境变量提供，不写文件。`cra plan PROJECT`产生带依赖、产物、验收与资源上限的任务图，不执行付费研究。

代码本每列声明type(number/category/id/text)与sensitive布尔值；CSV列与之对应，ID唯一。scales声明题项和反向编码，descriptive_weight须有含义与理由。质量检查优先，禁止根据显著性删样本。复杂抽样/跨国潜变量比较未具备前提时停止，不冒充适配器已经支持。

## 三个确认点

1. 研究者在实际终端执行`cra approve PROJECT --scope authorization --reviewer ... --note ...`，确认主机、数据摘要外传、资源与目标。Agent不代签、不模拟终端绕过，不使用TEST身份处理真实项目。
2. `cra run PROJECT`执行审计、文献与方案，等待研究者`approve --scope protocol`冻结当前版本。既有数据的方案冻结如实披露先前结果接触，不称为预注册。
3. `cra resume PROJECT`执行分析、数字声明、写作、方法与证据复核，等研究者`approve --scope final`终审。未终审只能`export --working`。终审不授权投稿或推送。

有模型权限时，先`cra model-test PROJECT`实际测试受限echo工具与JSON往返；消耗已授权预算。通过后才生成候选问题、写作与审阅。模型只提JSON计划、文本和问题，不执行任意代码、不扩大权限。相同模型多个角色不能称为独立同行评审。

## 文献、方案与写作

literature/references.json记录id/题名/作者/年份/来源/核验URL，可有DOI。元数据核验与支持论断分开；本地支持片段注明PDF page或文本paragraph、原文quote、具体claim、status、reviewer/note、permitted_for_model。精确定位不是语义支持证明。只有题录或摘要时，不推断未读全文结论。Crossref、BibTeX/RIS导入只是发现与题录，不自动生成真实引用支持。

protocol/plan.json包含RQ、inference=association、missing=complete_case、results_seen_before_freeze、理论贡献/竞争解释/边界与evidence_ids、models与exclusions。family为ols/wls/logit，role为primary/robustness/exploratory，声明y/x/covariance及类别参照组。WLS仅逆方差权重；调查权重只做描述均值；HC3仅非加权OLS。方法不适用时停下，不能静默替代。

模型写作返回introduction/theory/discussion/limitations字符串；数值必须用`{{claim:ID}}`，引文用`[[cite:ID]]`，禁止自填数字。离线时由研究者提供manuscript/narrative.json，不能声称由模型自主生成。正文、表图与结果同源；自然语言语义、理论贡献和投稿格式仍需终审。

## 续跑与停止

`cra status PROJECT --json`读取任务、预算、批准和last_problem；`cra evidence PROJECT`查询证据关系。改文字只使稿件与相关审阅过期；改数据/模型/测量/权限等实质内容重新冻结或授权。不能改日志消除报错，不能自动抬高预算或重试上限。

系统隔离自检`cra doctor PROJECT`必须通过。失败时不无隔离执行。统计worker无网络、输入只读、不读取控制数据库或模型密钥；模型不读取行级数据、原始错误日志。阈值抑制与模式扫描不保证完全匿名。

默认顺序调度，授权并发上限不超过2；运行7200秒、相同错误两次、文字修订两轮。未知付费结果保留预留且禁止自动重发，由研究者核对账单后解决。`pause`在安全点停，`resume`恢复；中断任务与已完成任务分开。

`cra reproduce PROJECT`重建主分析，`cra export PROJECT`生成版本化包，数据默认不打包。DOCX含内部引文键，不能称完整APA/GB/T成稿。`cra release-check PROJECT`必须保留真实试点、专家审查和独立复现未完成项，不用模拟研究或模型自评填补。
