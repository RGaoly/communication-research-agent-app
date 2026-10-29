# 工具契约 v1（离线、自包含）

Python 3.9+ 标准库，无需安装依赖。示例中的 `CRA` 指本 Skill 下的 `scripts/cra.py`，`PROJECT` 为独立的新项目路径。

```sh
python3 CRA init PROJECT --profile apa7 --extension survey
python3 CRA status PROJECT
python3 CRA validate PROJECT
python3 CRA validate PROJECT --full
python3 CRA analyze PROJECT --x exposure --y trust
python3 CRA review PROJECT --stage design --reviewer '实际核查人' --decision pass --note '实际核查依据与已解决的问题，不能照抄示例'
python3 CRA advance PROJECT
python3 CRA configure PROJECT --profile ica --target '实际年份/分会/提交类型'
```

`init` 拒绝现有目录；模拟项目加 `--synthetic`。`analyze` 拒绝覆盖既有四个分析文件，确认重建时加 `--replace-generated`；不会改原始 CSV、正文或 claims。`review` 只能由真实核查者登记；不能在自动检查失败时记录 pass，不能审核未来阶段。`advance` 检查截至当前阶段所有证据与人工声明，一次只前进一步；最后阶段标记 complete，不执行投稿。`configure` 与任何证据修改都会使旧审核失效。退出码：0=命令完成（可能仍需人工），1=自动检查失败，2=输入错误/阶段阻断/锁冲突。

项目布局：

```text
project.json                   # schema_version=1, profile/extension/target, stage, reviews, audit_head
protocol/design.md             # 理论、RQ、设计和边界
protocol/measurement.md        # 测量与问卷
protocol/data-audit.md         # 样本流转和数据质量
protocol/analysis.md           # 分析方案与复现命令
protocol/submission.md         # 当前投稿规范证据
data/input.csv                 # 脱敏工作副本；原始数据另外只读保存
data/codebook.json             # 列契约
artifacts/results.json         # 数字唯一来源
artifacts/table.csv            # 内置/契约数字表
artifacts/figure.svg           # 内置散点图或其他清单产物
artifacts/manifest.json        # 图表映射
artifacts/claims.json          # 正文数字映射
manuscript/draft.md            # 内部标记稿
references.json                # 基础文献元数据
reports/validation.json        # 最新报告，可重建
logs/audit.jsonl               # 哈希链，不手改
```

`codebook.json` 形如 `{"schema_version":1,"columns":{"study_id":{"type":"id","sensitive":false},"x":{"type":"number","sensitive":false,"min":1,"max":5},"group":{"type":"category","sensitive":false,"allowed":["A","B"]}}}`，列与 CSV 完全对应。支持 number/category/id/text；空字符串视为缺失，不自动把 NA/99 当缺失。每列必须声明 sensitive，敏感字段在此工作副本中会阻断。补充 question、coding、source、reverse、derivation 等字段供人工使用，MVP 不理解其语义。

结果形如 `{"schema_version":1,"synthetic":false,"data_sha256":"输入文件SHA256","recipe":{"id":"external-r-v1"},"sample_n":100,"models":{"m1":{"n":90,"b":0.2,"se":0.1,"t":2.0,"r2":0.1}}}`。`sample_n` 为工作数据行数，`n` 为模型 N；全部模型字段是有限数字。b/se/t 同时存在则核对；se>0，p若有须在[0,1]，r2专指普通OLS R²。外部模型不自动复算，不能将自动一致性当作分析正确。

图表清单形如 `{"schema_version":1,"items":[{"id":"T1","kind":"table","path":"artifacts/table.csv","sha256":"文件SHA256","cells":[{"key":"b","source":"models.m1.b","decimals":3}]}]}`。CSV 须恰为 `statistic,value` 两列；每行数字全部映射，禁止漏映射/重复。图形 kind=figure，ID如 F1，同样记录 path/sha256；内置 `simple-ols-scatter-v1` 重算点数/坐标，其他图仅检查文件/哈希/正文引用。所有路径在项目内，不接受符号链接与越界。图形视觉正确性还需人看。

正文数字声明形如 `[{"id":"slope","source":"models.m1.b","value":0.2,"decimals":3,"text":"斜率 b = 0.200"}]`，正文须唯一出现 `斜率 b = 0.200 [[stat:slope]]`。误差容限为 0.5×10^(-decimals) 加浮点微差，decimals限0–10。正文图表/文献分别用 `[[Table:T1]]`、`[[Figure:F1]]`、`[[cite:smith2024]]`；双向核对。工具不抽取未标记的自然语言数字、作者—年份引文或自动排版引用。

文献为数组，每项含 id、authors字符串数组、year字符串（如2024、2024a或n.d.）、title、source、url（核验入口），可选 doi（完整https://doi.org/...）、verified布尔值及verification_note。这些都是基础检查；verified只是人工声明，不是联网查证。无 DOI 不报错，不猜造 DOI。空数组只适合没有学术引文的工程示例，不适合完整论文。

阶段必需证据：design要设计文件；measurement增加测量文件/代码本；audit增加数据审计/CSV；analysis增加分析方案/结果/图表清单；writing增加正文/声明/文献；submission增加投稿清单。后阶段累计检查前阶段；非空且无“待填写/TODO/TBD”只是完成度筛查，材料内容必须由人审。所有源文件和配置共同绑定审核快照，新增无关文件也会使审核过期；reports/logs/project状态不纳入内容快照。

报告分 automatic_status（pass/fail）、overall_status（blocked/needs_human_review/review_recorded）和逐阶段 human_checks。警告不会自动阻断，但核查人必须处理；错误阻断。审计日志记录动作与聚合结果，不含原始数据命中值。普通断点续跑使用 status→修复→validate→人工review→advance；损坏日志不自动修复。日志/状态写入是分开的，崩溃时需备份/人工恢复，不能声称事务级持久性。
