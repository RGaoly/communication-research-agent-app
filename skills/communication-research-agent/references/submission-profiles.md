# 可切换规范与投稿人工核查

`--profile` 是工作流路由，不是格式认证或排版器。`configure` 切换配置后旧核查失效。SSCI/CSSCI 是索引/期刊集合，不对应一个统一格式；按具体目标的作者指南决定覆盖项。

| profile | 应用方式 | 人工必须补齐 |
|---|---|---|
| `apa7` | APA 第七版参考规范；DOI 有则以 `https://doi.org/...` 登记 | 文内作者—年份、作者截断规则、同年字母、悬挂缩进、斜体、表格/统计符号；按文献类型选择格式 |
| `ica` | 基于当前年份、Division/Interest Group 和提交类型 | 当期字数/页数、摘要、匿名正文及属性/致谢/共享链接、重复投稿、AI政策、出席/学生身份等实际要求 |
| `cssci` | 指定中文期刊名称与其当前投稿指南 | 文内引注/脚注、参考文献标准与排序、摘要/关键词、图表/黑白、基金与作者信息、匿名要求 |
| `custom` | 任意其他目标，包括某 SSCI 期刊 | 明确指南及与基础规则冲突的覆盖项 |

在 `protocol/submission.md` 登记目标、年份/卷期或会议分会、提交类型、官方 URL、查阅日期、关键要求、适用的覆盖项、各项证据及仍待解决的冲突。优先采用目标的最新官方指南，不把下面链接视为永久有效的投稿规则。无从核实时暂停“可提交”结论，其他研究工作可继续。

官方定位入口（工程实现时于 2026-10-28 检索到；没有将当期页数/截止日硬编码）：

- APA [Style and Grammar Guidelines](https://apastyle.apa.org/style-grammar-guidelines)、[Reference examples](https://apastyle.apa.org/style-grammar-guidelines/references/examples)、[DOIs and URLs](https://apastyle.apa.org/style-grammar-guidelines/references/dois-urls)。
- ICA [Conference Submission Guidelines](https://www.icahdq.org/page/conf-submission-guidelines)、[Submission & Proposal Types](https://www.icahdq.org/page/conf-submission-types)。还需查看实际 Division/IG 的当期 call。

MVP 自动部分只检查所选 profile、特定 profile 的目标字段、参考文献基础字段、DOI 格式和显式引文覆盖；不验证 DOI 解析/作者题名匹配、GB/T 或完整 APA7、不解析 Word/PDF/元数据。`--anonymized` 仅添加可疑作者/单位标签扫描，不能保证匿名。正式版本需用目标编辑工具排版，清除内部标记，再人工比对冻结的结果与文献。
