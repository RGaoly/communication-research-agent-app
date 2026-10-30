# 自主科研系统需求与实现追踪

PRD版本1.0；实现目标为v0.2研究引擎，当前交付版本0.2.0a4开发预览。完整科研系统的v0.3—v1.0能力不被计为首版已实现。所有性能和科研质量指标都是待试点测量的验收目标，不是已经获得的结果。

## 产品与用户

面向个人学者和小型课题组，先跑通已有传播学调查数据到研究成果。CLI与Skill管理工作流，统计在本地执行，模型只看检查后的结构摘要、聚合结果和授权文献。用户自带密钥。系统自主执行和迭代，在项目授权、计划冻结、成果终审请求真实研究者确认。

研究者可获得研究包、零结果包、探索包、不可行诊断或等待条件的交接材料。零结果不是无效应证明；探索身份必须在方案中声明。模型不能承诺原创性、真实性、录用、因果或完全匿名。理论、测量效度、问卷与跨国可比性、数据质量优先于文字和显著性。

## 产品目标与指标

北极星：每月完成实质人工终审、能从授权输入重建主结果的研究包数量。关键统计量和论断证据覆盖目标100%，发布测试集主分析重建100%，专家文献支持抽检≥95%，中断恢复≥95%，主动操作时间中位下降≥40%，标准流程不超过三个主要确认点，测试中受限数据外传为0。保留分母与失败样本，不能用LLM评分或论文数量代替质量。

## 首版需求追踪

“代码＋测试”表示该行为已有执行路径与软件验证，不代表科研质量或真实项目验收已经完成。

| ID | 首版需求 | 实现与验证入口 | 当前边界 |
|---|---|---|---|
| FR-01 | 研究任务书与授权 | schema.validate_brief；test_plan_has_all_inputs_acceptance_limits_and_no_execution | 研究者填写实际目标与来源 |
| FR-02 | 有依赖/产物/验收/资源/失败处理的任务图 | runtime.plan；同上测试 | 固定可信任务类型，顺序调度 |
| FR-03 | 修复/计划内执行/实质变更区分 | runtime.run与依赖失效；test_textual_review_triggers_bounded_revision、test_protocol_change_requires_new_freeze | 未支持的方法不生成任意代码补齐 |
| FR-04 | 状态与断点恢复 | store.lease；test_actual_process_crash_recovers_lease_task_and_unknown_cost | 本地单写进程，不是分布式系统 |
| FR-05 | 进度/依据/预算/等待项 | status、evidence、budget | 支持JSON及简洁中文状态 |
| FR-06 | 最多3个有依据候选方向 | model research_designer＋validate_protocol；test_full_model_loop_never_transmits_rows | 无支持文献则停止，不伪造缺口 |
| FR-07 | 理论—测量—分析映射 | Protocol的RQ/theory/models/codebook；validate_protocol | 构念有效性需要研究者确认 |
| FR-08 | 不将场景新颖性等同贡献 | Skill、设计模型约束、冻结批准 | 理论贡献不能确定性证明，待专家验收 |
| FR-09 | 竞争解释和边界 | theory.competing_explanation/boundary必填 | 实质是否充分由人审 |
| FR-10 | 元数据/全文/支持状态分开 | literature.build_corpus；test_matching_title_wrong_author_not_verified | DOI可解析不等于论断支持 |
| FR-11 | 页码/段落/引文/文件版本 | literature.locate；test_quote_must_match_declared_location | 精确定位不证明语义支持 |
| FR-12 | 关键未核验文献阻断 | validate_protocol/validate_narrative；test_missing_evidence_stops_before_statistics | 支持记录为本地声明，需终审 |
| FR-13 | 工作稿与最终稿分离 | export_package；test_export_refuses_final_without_approval | 不能把工作稿直接称可提交 |
| FR-14 | 样本流转与模型N | audit/fit_models；test_missing_cases_flow_no_imputation | 未知招募数保持null |
| FR-15 | 数据质量审计、不静默删除 | read_frame；test_duplicate_respondents_stop_without_deleting | 不替代全部自由文本检查 |
| FR-16 | 题项编码/量尺/派生/用途 | codebook/scales；test_scale_reverse_coding_detection | 题项许可和内容效度人审 |
| FR-17 | 基础量表诊断 | alpha、题项—其余题项相关；同上测试 | 未实现CFA/SEM/等值性 |
| FR-18 | 不支持的前提阻断 | audit/design flags；test_complex_survey_and_invariance_block | 不静默用普通回归代复杂抽样 |
| FR-19 | 统计来自执行 | OS worker→规范结果；test_ols_hc3_matches_independent_sandwich | 无模型填数入口 |
| FR-20 | 记录全部规格尝试 | specification_attempt、逐模型原子进度及诊断导出；test_real_worker_failure_is_retained_in_state_and_diagnostic | 成功、失败与未执行分开；保留此前零结果，不把部分执行称为完成 |
| FR-21 | 批准计划与实际执行对照 | protocol hash、method_review；test_protocol_gate_and_full_offline_loop | 改变量/样本/方法重新冻结 |
| FR-22 | 调查关联边界 | inference固定association；test_protocol_cannot_promote_association_to_causation | 因果识别留给新验证适配器 |
| FR-23 | 正文/表/图同源 | claims/render_draft/exhibits；test_output_tampering_is_not_adopted | 自由文本语义仍需审阅 |
| FR-24 | 环境/输入/代码/种子/重建 | recipe_identity、版本依赖、run_record、reproduce.py；test_real_cli_invalidates_after_recipe_code_changes、test_export_source_tamper_is_caught_after_manifest_is_repaired | 旧无版本绑定结果须重算；Python及依赖须匹配；模型文本不保证逐字重建 |
| FR-25 | 证据稿与可见缺口 | render_draft/review_evidence；test_unknown_citation_and_causal_rewrite_refused | 不确定项目保持等待或不可行 |
| FR-26 | 保护数字/引文/术语 | narrative锚点与禁填数字；test_model_invented_number_blocks_draft | 任意自然语言含义仍需终审 |
| FR-27 | 结果/结论/讨论分工 | Skill、写作分节和计算结果 | 学术叙述质量待真实项目评估 |
| FR-28 | 有来源版本的规范适配 | profile.sources分类与目标；test_profile_official_source_required_for_final | 不承诺完整APA7/GB/T或当期语义自动核实 |
| FR-29 | 可审阅复现包 | export_package；test_export_hash_manifest_no_credentials_or_data_by_default | 数据默认不打包，DOCX含内部引文键 |
| FR-30 | 可定位可解决的审阅问题 | validate_review要求code/location/evidence/resolution | 评审模型也可能出错 |
| FR-31 | 意见不冒充事实或人审 | origin/model/independence字段；test_full_model_loop_never_transmits_rows | 同模型多角色不称独立同行评审 |
| FR-32 | 反证/不适用时停止 | blocking诊断与无隔离拒绝；test_no_isolation_has_no_unrestricted_fallback | 不强制每项任务成为论文 |
| FR-33 | 有限修订和停止 | 错误指纹两次、文字两轮；test_repeated_error_is_bounded_and_change_recovers | 不能自动提高上限 |

## 关键接口与兼容

新增plan/run/resume/pause/approve/evidence/reproduce/export/migrate，另有doctor/model-test/literature/budget/release-check。原schema1CLI完整保留，schema2需显式迁移和备份，不继承旧批准。新增统计依赖位于engine extra。模型、统计、文献与目标规范具备独立契约；R/Stata为后续适配，不宣称已接入。

## 验收与路线

M0事务引擎、M1离线闭环、M2文献/模型/方法适配已有开发实现；后续开发候选增加了Ubuntu 24.04云端新机器的Linux工程集成。M3正式发布尚需独立真人操作、真实模型研究质量、方法与文献保留集、三个获授权真实项目双角色终审及性能目标测量。没有任何“全部通过”字段可自动替代这些证据。

后续v0.3深化跨国测量等值、多层与复杂抽样；v0.4问卷预测试、真人信息实验与预注册材料；v1.0项目组合、长期证据更新、LLM硅基样本与媒体研究。真人招募、伦理、对外提交、费用权限扩大始终单独授权。

## 参考项目与取舍

- [APE](https://github.com/SocialCatalystLab/ape-papers)：借鉴真实执行与复现档案，不以LLM竞赛评分认证科学有效性。
- [AIGC Reduce](https://github.com/xiaofenggan01/aigc-reduce)：借鉴保护片段和修订审计，不优化检测分数或修改比例。
- [中文经济学工作流](https://github.com/ZehChou/cn-economics-thesis-workflow-skill)：借鉴状态/后端/规格记录，数据审计在本系统必经。
- [Awesome Journal Skills](https://github.com/brycewang-stanford/Awesome-Journal-Skills)：借鉴按刊路由，区分官方规则/建议/经验/推断。

实现代码为本项目新编写；未直接复制这些仓库代码。第三方运行依赖通过明确安装的包接入，不将许可证不明材料直接内嵌。
