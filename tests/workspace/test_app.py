from pathlib import Path

from streamlit.testing.v1 import AppTest

from cra_workspace.app import PAGES


def test_native_form_creates_persisted_project_and_all_pages_render(tmp_path, monkeypatch):
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    source = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(source), default_timeout=15).run()
    assert not app.exception
    app.text_input[0].set_value("Native UI engineering fixture")
    app.text_area[0].set_value("What can this synthetic input answer?")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    assert not app.exception
    p = app.session_state["project"]
    workspace = app.session_state["workspace"]
    assert workspace.snapshot(p)["brief"]["name"] == "Native UI engineering fixture"
    assert workspace.snapshot(p)["materials"]["data"] == []
    for page in PAGES:
        app.radio[0].set_value(page).run()
        assert not app.exception, page
    assert workspace.snapshot(p)["status"]["budget"]["calls"] == 0
    workspace.import_data(p, "synthetic.csv", b"x,y\n1,2\n2,4\n3,5\n")
    app.radio[0].set_value("材料与测量").run()
    assert not app.exception
    next(x for x in app.text_input if x.label == "实际核查人").set_value("TEST FIXTURE ONLY")
    next(x for x in app.text_area if x.label.startswith("核查依据：")).set_value("TEST FIXTURE ONLY; generated numbers are known synthetic bounds")
    next(x for x in app.checkbox if x.label.startswith("我已核查以上")).check()
    next(b for b in app.button if b.label == "保存核查后的分析副本").click().run()
    assert not app.exception and workspace.snapshot(p)["measurement_reviewed"]
    app.radio[0].set_value("研究概览").run()
    next(b for b in app.button if b.label == "项目授权 · 待确认").click().run()
    assert not app.exception
    next(x for x in app.text_input if x.label == "实际审阅者姓名或项目代号").set_value("TEST FIXTURE ONLY")
    next(x for x in app.text_area if x.label == "审阅依据与判断（至少8个字符）").set_value("TEST FIXTURE ONLY; no actual research authorization")
    challenge = next(x.value for x in app.code if x.value.startswith("APPROVE "))
    next(x for x in app.text_input if x.label == "输入上方版本确认短语").set_value(challenge)
    next(x for x in app.checkbox if x.label.startswith("我已查看这一版本")).check()
    next(b for b in app.button if b.label == "记录我的确认").click().run()
    assert not app.exception and workspace.snapshot(p)["status"]["approvals"]["authorization"], [x.value for x in app.error]
    reopened = AppTest.from_file(str(source), default_timeout=15).run()
    assert not reopened.exception
    assert reopened.session_state["workspace"].directory == workspace.directory
    reopened.selectbox[0].set_value(p).run()
    assert not reopened.exception
    assert reopened.session_state["project"] == p
    assert not reopened.session_state["workspace"].snapshot(p)["has_session_key"]


def test_cloud_upload_controls_require_consent(tmp_path, monkeypatch):
    from cra_workspace import environment
    # UI boundary test double only; real OS probes are covered separately.
    monkeypatch.setattr(environment, "inspect_host", lambda: {"passed": False, "at": "SYNTHETIC UI FIXTURE"})
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "cloud")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    assert any("自动统计隔离自检未通过" in x.value for x in app.warning)
    # The uploader is not merely disabled: it isn't mounted before consent.
    assert not app.get("file_uploader")
    app.checkbox[1].check().run()
    assert len(app.get("file_uploader")) == 1
    app.text_input[0].set_value("Cloud synthetic UI fixture")
    app.text_area[0].set_value("Test refused execution when isolation is unavailable")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    p = app.session_state["project"]
    workspace = app.session_state["workspace"]
    workspace.import_data(p, "synthetic.csv", b"x,y\n1,2\n2,3\n", cloud_consent=True)
    app.run()
    assert not app.exception
    assert next(b for b in app.button if b.label == "继续执行获批研究").disabled
    assert workspace.snapshot(p)["files_ready"]
    assert workspace.snapshot(p)["status"]["budget"]["calls"] == 0


def test_hot_upgrade_preserves_records_but_waits_for_old_task_and_discards_key(tmp_path, monkeypatch):
    from cra_engine.common import digest
    from cra_workspace.service import Workspace
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "hot-upgrade"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    source = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(source), default_timeout=15).run()
    original = app.session_state["workspace"]
    p = original.create("Synthetic upgrade fixture", "Preserve actual saved input", synthetic=True)["project_id"]
    original.import_data(p, "fixture.csv", b"x,y\n1,2\n2,3\n")
    config = digest(original.snapshot(p)["brief"]["model"])
    original.credentials.put(p, config, "SYNTHETIC-KEY-NEVER-SENT")
    class SyntheticThread:
        alive = True
        def is_alive(self): return self.alive
    thread = SyntheticThread()
    class LegacySession:
        # UI migration double, not an actual research execution or approval.
        directory = original.directory
        deployment = original.deployment
        credentials = original.credentials
        _threads = {p: thread}
        def pause(self, project): return original.pause(project)
    app.session_state["workspace"] = LegacySession()
    app.session_state["project"] = p
    app.run()
    assert not app.exception
    assert any("旧任务正在安全停止" in item.value for item in app.warning)
    assert not isinstance(app.session_state["workspace"], Workspace)
    assert original.credentials.get(p, config) is None
    thread.alive = False
    next(b for b in app.button if b.label == "检查旧任务是否已停止").click().run()
    assert not app.exception
    migrated = app.session_state["workspace"]
    assert isinstance(migrated, Workspace)
    assert migrated.directory == original.directory
    s = migrated.snapshot(p)
    assert s["brief"]["theme"] == "Preserve actual saved input"
    assert s["materials"]["data"][-1]["records"] == 2
    assert not s["has_session_key"] and not s["status"]["approvals"]["authorization"]


def test_new_project_navigation_does_not_reselect_the_previous_project(tmp_path, monkeypatch):
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "navigation"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    source = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(source), default_timeout=15).run()
    created = []
    for name in ("Synthetic project A", "Synthetic project B"):
        next(x for x in app.text_input if x.label == "研究名称").set_value(name)
        next(x for x in app.text_area if x.label == "你想回答什么问题？").set_value("Synthetic navigation verification")
        next(x for x in app.checkbox if x.label.startswith("这是工程练习")).check()
        next(b for b in app.button if b.label == "建立研究项目").click().run()
        assert not app.exception
        created.append(app.session_state["project"])
        next(b for b in app.button if b.label == "＋ 新建 / 恢复研究").click().run()
        assert not app.exception and app.session_state["project"] is None
        assert any(x.label == "研究名称" for x in app.text_input)
    assert len(set(created)) == 2
    assert len(app.session_state["workspace"].projects()) == 2
    next(x for x in app.selectbox if x.label == "当前会话的研究").set_value(created[0]).run()
    assert not app.exception and app.session_state["project"] == created[0]
    next(x for x in app.selectbox if x.label == "当前会话的研究").set_value(None).run()
    assert not app.exception and app.session_state["project"] is None


def test_advanced_measurement_submits_its_own_review_fields(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "advanced"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    w = app.session_state["workspace"]
    p = w.create("Synthetic advanced fixture", "Review generated fields", synthetic=True)["project_id"]
    w.import_data(p, "fixture.csv", b"x,y\n1,2\n2,3\n")
    book = w.snapshot(p)["codebook"]
    book["columns"]["x"]["min"] = 0
    app.session_state["project"] = p
    app.session_state["route"] = "材料与测量"
    app.run()
    next(x for x in app.text_area if x.label == "完整代码本JSON").set_value(json.dumps(book))
    next(x for x in app.text_input if x.label == "高级代码本实际核查人").set_value("TEST FIXTURE ONLY")
    next(x for x in app.text_area if x.label == "高级代码本核查依据").set_value("TEST FIXTURE ONLY; known synthetic scale boundaries")
    next(x for x in app.checkbox if x.label.startswith("我已核查这份高级")).check()
    next(b for b in app.button if b.label == "采用高级代码本并记录核查声明").click().run()
    assert not app.exception
    s = w.snapshot(p)
    assert s["measurement_reviewed"] and s["codebook"]["columns"]["x"]["min"] == 0


def test_key_clear_removes_pending_input_and_keeps_saved_target(tmp_path, monkeypatch):
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "key-clear"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    w = app.session_state["workspace"]
    p = w.create("Synthetic credential UI fixture", "No network calls", synthetic=True)["project_id"]
    brief = w.snapshot(p)["brief"]
    w.save_brief(p, {"permissions": {"model": True, "literature_network": False, "allowed_hosts": ["example.invalid"]}, "model": dict(brief["model"], base_url="https://example.invalid/v1", model="synthetic-model", input_per_million=1, output_per_million=1), "limits": dict(brief["limits"], max_cost=1)})
    app.session_state["project"] = p
    app.session_state["route"] = "模型与设置"
    app.run()
    next(x for x in app.text_input if x.label == "API Key").set_value("SYNTHETIC-KEY-NEVER-SENT")
    next(x for x in app.checkbox if x.label.startswith("我同意该密钥")).check()
    next(b for b in app.button if b.label == "使用此密钥").click().run()
    assert not app.exception and w.snapshot(p)["has_session_key"]
    next(x for x in app.text_input if x.label == "API Key").set_value("SYNTHETIC-PENDING-INPUT")
    next(x for x in app.text_input if x.label == "OpenAI兼容 Base URL").set_value("https://unsaved.invalid/v1")
    next(b for b in app.button if b.label == "清除密钥并暂停").click().run()
    assert not app.exception
    assert next(x for x in app.text_input if x.label == "API Key").value == ""
    assert not w.snapshot(p)["has_session_key"]
    assert w.snapshot(p)["brief"]["model"]["base_url"] == "https://example.invalid/v1"
    assert w.snapshot(p)["status"]["budget"]["calls"] == 0


def test_settings_button_shows_remote_health_when_current_local_isolation_fails(tmp_path, monkeypatch):
    from cra_workspace import app as app_module, environment

    class RemoteFixture:
        endpoint = "https://worker.example.invalid"
        def __init__(self): self.calls = 0
        def health(self):
            self.calls += 1
            return {"passed": True, "isolation": "linux-bubblewrap", "controls": {
                "network_denied": True, "write_denied": True, "control_read_denied": True},
                "identity": {"protocol": 1, "recipe": "SYNTHETIC"}}

    remote = RemoteFixture()
    monkeypatch.setattr(app_module, "operator_executor", lambda: remote)
    monkeypatch.setattr(environment, "inspect_environment", lambda store: {
        "passed": False, "message": "SYNTHETIC local sandbox unavailable"})
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "remote-health-ui"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    source = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    app = AppTest.from_file(str(source), default_timeout=15).run()
    workspace = app.session_state["workspace"]
    p = workspace.create("Synthetic remote health UI", "No research data is transferred", synthetic=True)["project_id"]
    app.session_state["project"] = p
    app.session_state["route"] = "模型与设置"
    app.run()
    next(b for b in app.button if b.label == "执行环境自检").click().run()

    assert not app.exception
    assert remote.calls == 1
    assert any("独立服务器健康检查通过" in item.value for item in app.warning)
    assert any("没有上传材料" in item.value for item in app.warning)
    assert workspace.snapshot(p)["brief"].get("execution", {"backend": "local"}) == {"backend": "local"}
