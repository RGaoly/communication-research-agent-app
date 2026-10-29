# Communication Research Agent · 研究工作台

浏览器界面连接真实研究引擎：材料与测量、文献证据、计划冻结、统计、写作、复核、费用、重算及成果导出。

**0.2.0a5.dev2 开发预览。** 软件测试不能代替独立真人、文献专家、真实模型盲测与真实项目验收；当前不能宣称正式自主科研系统发布验收已经通过。

## 本机运行

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[engine,ui]'
CRA_DEPLOYMENT=local .venv/bin/python -m streamlit run streamlit_app.py
```

## 云端部署

Streamlit Community Cloud入口为 `streamlit_app.py`，Python 3.12。默认标记云端处理，用户明确同意后才展示上传控件；不设置共享模型密钥。安装包配置请求安装bubblewrap，但托管内核是否允许隔离，必须部署后实际检查。隔离失败会停止统计，不能关闭保护来冒充闭环成功。

云端空间与会话可能回收，请及时下载私有恢复备份。备份包含原始材料与项目状态，不含会话密钥；恢复后需要重新确认授权。不会自动把上传材料、运行项目或密钥提交到GitHub。

详见[使用、部署与限制](docs/STREAMLIT_WORKSPACE_ZH.md)。

## 工程测试

```sh
python -m pip install '.[engine,ui,acceptance,test]'
CRA_ISOLATION_TESTS=1 python -m pytest -q
```

测试与examples均为合成工程材料，不是真实学术文献、受访者、人工审批或真实研究试点。真实模型请求必须由用户在自己的项目中明确配置并授权，不因打开应用而自动发生。

本仓库是经用户授权建立的公开部署快照，仅包含源码、说明和合成工程夹具，不包含私有开发仓库的历史、调查数据、私人文献或密钥。`SOURCE_PROVENANCE.json`记录源提交与所复制文件的哈希，便于核对来源；它不构成科研质量认证。
