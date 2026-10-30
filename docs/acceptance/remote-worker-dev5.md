# 远程统计服务 dev5 部署记录

## 已验证

- 阿里云 Linux 3 上以 `cra-worker` 非 root 服务账号启动；服务端口仅监听回环地址。
- systemd 实际服务限制内执行隔离探针通过：网络访问、控制文件读取和隔离目录外写入均被拒绝。
- 统计运行时为 Python 3.12.16，NumPy 2.5.4、SciPy 1.18.1、pandas 2.3.3、statsmodels 0.14.6。
- 服务端身份包含协议、固定分析配方、依赖版本及源码哈希；前端只有在身份一致、隔离探针通过且项目明确授权后才允许上传分析副本。
- 凭证文件采用 root 所有、专用服务组只读的 0640 权限。worker 使用 `O_NOFOLLOW` 打开，并校验文件所有者、组、类型与精确权限。
- 实际 worker HTTP 接口的签名健康检查通过；一项 4 行模拟 CSV 的审计任务经认证提交、bubblewrap 隔离、统计审计及签名结果返回后成功。
- GitHub Linux 回归工作流通过：250 项测试通过，实际 wheel 构建及工程验收命令完成。工程报告仍将最终验收标为未通过，因为真人独立验收报告缺失；这不是正式科研发布通过。

## 尚未完成

- 公网 TLS 入口尚未配置。已安装 Caddy，但未启用服务，也未绑定公网端口。公网 IP 可通过 Let's Encrypt 的 TLS-ALPN-01 在 TCP 443 验证；因此这套方案不需要开放 TCP 80。只有用户决定继续云端连接后，才需在 ECS 安全组添加 TCP 443 入方向；TCP 8781 始终只监听 `127.0.0.1`。来源：[Let's Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/)、[IP and short-lived certificates](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)。
- Streamlit secrets 尚未配置，因此在线前端尚不能连接该 worker。
- 尚未完成真实模型盲测、独立工程验收、双专家文献核查或三个真实项目试点；本记录不能作为正式科研发布验收。
- 在独立 Python 3.12 环境完成本机全量 pytest：宿主系统权限下 `245 passed, 5 skipped`。受 Codex 受限进程直接运行时，19 项嵌套 macOS Seatbelt 用例被父级沙盒拒绝；使用宿主权限重跑远程隔离组后 `22 passed`，全量宿主权限运行通过。GitHub Actions 的独立 Linux 构建也成功。
- 公共 Streamlit 页面真实浏览器冒烟：填写合成项目名称、问题和边界后成功建立项目；概览显示项目输入，实际事件表出现 `initialized` 记录。没有上传文件、真实研究材料、模型密钥或服务凭证。云端页面明确显示远程统计未配置并禁用研究执行。
- ECS Caddy 示例配置经服务器上的 Caddy 2.11.7 `caddy adapt` 检查通过，生成的监听地址只有 `:443`，转发范围限于 `/v1/health` 和 `/v1/jobs/*`，其余路径返回 404。Caddy 服务仍 disabled/inactive；静态证书文件尚未签发，因而还未提供公网 HTTPS。

## 数据边界

本次没有向服务器上传调查数据、私人文献、研究工作稿或模型 API 密钥。隔离自检仅使用模拟数据。worker 不接收模型密钥或人工批准记录。
