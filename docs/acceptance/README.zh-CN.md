# v0.2 验收执行手册

本目录最初记录 v0.2.0a4 的验收方案与结果；当前工作候选版本为 `0.2.0a5.dev5`，仍是开发预览。自动工程观察、真人黑盒验收、科研盲测、真实试点分别判定，不能相互替代。旧 `docs/v0.2/acceptance.md` 保留为历史记录。

开发候选 `0.2.0a5.dev1` 收紧了软件回归证据：完成公开的全量 pytest 后，向 `cra-accept run` 额外传入 `--software-junit /absolute/path/software-tests.xml`。工具将原始逐项 XML 和源码版本报告登记为 `software/software-tests.xml` 与 `reports/software.json`，并纳入独立操作人签署的自动观察哈希。该历史候选冻结并运行了191个用例。当前工作候选在此基础上加入 Streamlit 界面的 CSV 接入、诊断包导出、私有备份和新项目恢复闭环；下一次候选冻结必须将 `software_baseline.CASES` 的194个身份全部运行并登记，不能缺失、同数量替换、重复或跳过；报告总数须与逐项内容一致。新增测试应在候选冻结时补入基线，既有身份不能静默删除。旧式仅填写测试数的汇总不再作为充分证据；未附原始报告时仍可执行工程组，但不能正式放行。

本次自动 UI 回归通过 `AppTest` 实际点击上传、设置保存、远程统计范围保存、导出与恢复控件，确认模拟 CSV 保存、模型预算和目标规范写入项目、远程执行必须逐项目同意、诊断 ZIP 清单、私有备份 ZIP 和恢复后授权清空。它不调用真实模型或真实云端统计服务器，也不构成真人黑盒验收或真实项目试点。

2026-10-30 本地复验结果：开启 `CRA_ISOLATION_TESTS=1` 后，全量 `pytest` 为256通过、0失败、0错误、0跳过；冻结回归选择集为194通过、0失败、0错误、0跳过。两份原始 JUnit 均通过 `junit_summary` 校验，身份、总数及结果一致。原始报告位于执行机临时目录 `/private/tmp/cra-full-isolated-tests.xml` 和 `/private/tmp/cra-frozen-194.xml`；这些是开发过程观察，尚未作为独立操作人签署的正式验收包。

XML、源码哈希和用例身份不能独立证明测试真的执行过，也不能发现用例实现被人为削弱。独立操作人仍须核查候选来源、测试源码、完整执行命令和原始输出，再签署当前材料；程序不会生成这一真人记录。历史 Alpha 不自动获得新候选的验证结论。

## 冻结与运行

候选版本以 wheel SHA256 为主标识，另记录引擎源码、验收代码、Python 和已安装依赖。每次运行必须使用新目录，保留失败运行；修改代码后重新构建、重跑受影响用例，不能沿用旧包结果。

```sh
python3 -m venv work/build-env
work/build-env/bin/python -m pip install build
work/build-env/bin/python -m build --wheel --outdir work/candidate-dist
python3 -m venv work/clean-acceptance-env
# 将下面路径替换为实际构建出的 wheel；显式安装依赖，不复用 editable 开发安装。
work/clean-acceptance-env/bin/python -m pip install 'work/candidate-dist/communication_research_agent_tools-0.2.0a4-py3-none-any.whl[engine,acceptance]'
work/clean-acceptance-env/bin/cra-accept run \
  --wheel work/candidate-dist/communication_research_agent_tools-0.2.0a4-py3-none-any.whl \
  --output work/acceptance-run-001
work/clean-acceptance-env/bin/cra-accept verify work/acceptance-run-001
```

`run` 拒绝 editable 源码环境。应从不含项目源码的工作目录启动，以额外排除导入路径偶合；参数使用绝对路径。macOS 需允许实际系统隔离和本地协议测试端口；不能以删除隔离层来让测试通过。Linux 云端真实工程集成已在 dev0 完成，新候选须重验；独立真人操作仍待完成。同一开发过程发起的自动观察不能称为独立人员验收。

`run`/`verify` 退出码 0 只表示自动工程组通过；最终 `release_eligible` 是独立字段，缺少真人或科研证据时仍为 false。包验证 `package` 返回 0 只表示内部一致性。

## 八项验收的实现与剩余人工工作

| 验收项 | 工具与观察 | 尚不能自动证明的部分 |
|---|---|---|
| 安装、公共 CLI | 实际 wheel 安装、公开命令、真实 OS worker、诊断导出及另目录复现 | 新机器、独立操作人，以及授权/冻结/终审三次真实交互 |
| 统计正确性 | 7 种支持的模型/协方差组合 × 4 个输入变体 + 2 个加权描述；独立 NumPy/SciPy 正规方程、Newton Logit 及 sandwich 公式 | 方法是否适合具体实证问题；未支持方法的数值正确性 |
| 文献与论断 | 100 条校准材料、双人空白评分表、分歧裁定、准确率及 Wilson 95% 区间计算器 | 校准材料由模板生成、并非独立保留集；真实来源、定位及专家内容核查均待补 |
| 真实模型 | GUI 两次授权调用，真实 usage、模型返回身份和预算记录 | 30 个独立任务各 3 次、保留集保密、专家判分、模型版本稳定性；接口测试不能代替 |
| 权限与边界 | CLI 负例、真实隔离探针、敏感字段阻断、实际出站观察正控 | 真实模型读到恶意全文后的行为、操作系统外部独立观察 |
| 故障与恢复 | 10 个持久化/请求边界各 10 次 SIGKILL；暂停、SIGTERM、父进程 SIGKILL 与真实子进程状态 | 所有可能的 I/O 指令点和真实厂商内部计费状态未被穷尽 |
| 成果复现 | 实际统计 worker、CSV/SVG/Word 数字核对、独立目录运行复现代码 | 独立人员/新机器复现、Word 逐页视觉审阅、完整 APA7/CSSCI/ICA 排版 |
| 真实研究者 | 三个空白试点记录和签名协议、真实研究包哈希核验 | 用户确认目前没有真实项目；全部保留待验证 |

数值容差在运行前固定为绝对 1e-7、相对 1e-6；样本 N、筛选、编码和参照组必须完全一致。OLS/WLS 聚类修正和 t 自由度、Logit 正态推断单独实现。加权描述只比较均值，不宣称复杂抽样方差支持。

## 故障注入边界

1. 事务提交前：未提交对象回滚。
2. 事务提交后：已提交对象保留。
3. 预算预留后、发请求前：恢复为费用待核对，拒绝新请求。
4. 本地协议服务已收到请求、响应返回前：只观察到一次请求，不自动重发。
5. 收到响应、计费与响应检查点提交前：费用待核对。
6. 计费与响应原子提交后、任务产物提交前：重用持久响应，不新增费用。
7. 产物原子落盘、数据库登记前：文件完整，但不能冒充已登记任务成功。
8. 文件和登记均提交后：保留登记。
9. 上游变化提交后：下游结果过期，不得使用。
10. 任务运行状态保存后：恢复任务就绪、旧运行标记中断。

这 100 次是 10 个边界的重复观测，不是 100 种不同故障。传输使用明确标记的本机协议服务，不计入真实模型成绩。外部控制器在子进程写出边界标记后发送 SIGKILL；没有替换 SQLite、文件 I/O 或统计执行层。子进程生命周期另做三项测试，控制器可对真实 worker 发 SIGSTOP，以保证取消时仍有在途进程。

## 测试有效性与证据验证

- 改错导出表系数后重新生成 manifest 哈希，检查语义对账是否失败。
- 向实际监听器发送特意标记的未经授权出站哨兵，验证监听器能捕捉；这是传感器正控，不能据此声称阻止了所有越权请求。
- 改变已冻结输入，检查相关分析和批准失效。

`cra-accept package /path/to/package.zip` 检查成员哈希、数据/代码本/计划绑定、统计声明、表格、SVG 实际坐标和 Word 表格。它只证明内部一致性；若整个结果源本身错误，需要独立数值复现才能发现。

## 真人黑盒操作

独立操作人在真实终端从候选 wheel 安装后执行公开 `cra`：init → plan → approve authorization → run → approve protocol → resume → pause/resume → reproduce → approve final → export。还需执行 schema1 项目的 migrate --dry-run 并核查备份后迁移。

每次批准先实际阅读材料，再输入当前证据绑定短语。自动程序不能代填，也不能以通用 --yes 跳过。自动夹具的 `TEST FIXTURE ONLY` 批准仅用于组件测试，不是这项证据。

将操作命令、退出码、材料哈希、实际操作人、操作耗时、失败及复验记录写入 `manual-cli-results.json`。操作人应核对全部规定链路，不仅填写“通过”。签署其哈希后提交 `manual-cli-attestation.json`；缺失时 `engineering_acceptance_passed=false`。

记录还必须包含 `checkpoints: {authorization: true, protocol: true, final: true}`、`independent_operator: true`，以及 verify 返回的 `automated_observations_sha256`。这一哈希绑定全部原始自动观察；替换自动报告后，既有操作人签署即失效。布尔字段本身不是凭证，必须有外部可信公钥签名并由组织核实实际操作。

## 双专家与保留集

```sh
cra-accept prepare work/reviewer-materials
cra-accept score-literature /authorized/expert-rated-cases.json
```

模板中的校准语句不是真实文献。独立策展人必须提供至少 100 个获授权的真实“来源片段—论断”对、文件版本和定位，覆盖错作者、否定、条件限制、摘要范围、真 DOI 错题名等。两位专家先独立评分，再裁定分歧；保留全部分母、逐项预测、评分和严重错引记录。≥95% 准确率与核心严重错引为零同时满足才通过，Wilson 区间展示不确定性，不另行偷换为区间下界门槛。

真实模型集至少 30 个任务、每任务 3 次，覆盖六类研究结果。前 10 个任务先评估成本，再在新增明确授权范围内继续。本轮授权仅有两次接口/小任务调用，不能用于启动这 90 次评估。每个固定模型版本单独出结论；别名本身不能证明不可变版本。

## 签名、证据包与放行

证据包 `manifest.json` 登记候选 wheel、报告、逐案观察和原始输出的 SHA256。核心报告放 `reports/{installation,statistics,faults,boundaries,mutations,literature,live_model,pilots}.json`。每个通过案例必须指向实际登记的观察文件。

科研组的 `cases` 还须写入 `reports/名称-results.json`，与报告逐项相同；专家签署该结果文件和候选 wheel 的双重哈希。试点必须具有实际包、包哈希、非模拟标记及数据授权；仅有注册表声明不足以放行。

项目负责人单独维护外部 trust-store（不放在待审证据包内），登记独立评审人的 Ed25519 公钥和角色。同一组的两个角色须由不同签署人承担。签名只能证明指定密钥对指定记录作出声明；不能证明学术判断正确、人的真实身份或独立性，仍需组织核实。

```sh
cra-accept sign-review --results reports/literature-results.json \
  --candidate-sha256 ACTUAL_WHEEL_SHA256 --key /private/reviewer-key.pem \
  --role literature_expert_a --signer-id ACTUAL_REVIEWER \
  --note '实际完成核查的范围与依据' --output expert-a-statement.json
cra-accept verify /evidence/bundle --trust-store /owner/trust-store.json
cra release-check /research/project --acceptance-bundle /evidence/bundle \
  --trust-store /owner/trust-store.json --software-report /evidence/bundle/reports/software.json \
  --pilot-registry /authorized/pilot-registry.json
```

不要让 Agent 生成实际评审签名或代签。测试代码使用的临时测试密钥没有评审效力。严重伪造、越权外传、批准/预算/隔离绕过、选择性报告、过期结果误报完成及主结果不可复现，均阻断放行；不能通过平均分抵消。

## 放行结论

自动工程组通过 → 可继续开发预览；独立工程人员＋模型保留集＋真实试点通过 → 才可评估限定范围的受控试用；正式版本还需持续独立复核与稳定性证据。`release-check` 不接受调用者自填的 pass 字段作为充分条件。所有欠缺项必须在最终报告可见。
