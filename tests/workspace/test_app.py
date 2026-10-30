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


def test_ui_upload_diagnostic_export_and_private_restore_are_real_operations(tmp_path, monkeypatch):
    """End-to-end UI path with synthetic bytes; no model or external service calls."""
    import io
    import json
    import zipfile

    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-roundtrip"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception

    app.text_input[0].set_value("Synthetic UI roundtrip")
    app.text_area[0].set_value("Check upload, diagnostic handoff and private recovery")
    app.text_area[1].set_value("Synthetic fixture only")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    assert not app.exception
    project = app.session_state["project"]
    workspace = app.session_state["workspace"]

    app.radio[0].set_value("材料与测量").run()
    uploader = next(x for x in app.get("file_uploader") if x.label.startswith("接入CSV或Stata"))
    uploader.set_value(("synthetic.csv", b"x,y\n1,2\n2,4\n3,5\n", "text/csv")).run()
    next(b for b in app.button if b.label == "读取并登记数据").click().run()
    assert not app.exception, [x.message for x in app.exception]
    imported = workspace.snapshot(project)
    assert imported["materials"]["data"][-1]["records"] == 3
    assert (workspace.directory / project / imported["brief"]["data"]["csv"]).read_bytes() == b"x,y\n1,2\n2,4\n3,5\n"

    app.radio[0].set_value("稿件与交付").run()
    next(x for x in app.selectbox if x.label == "成果类型").set_value("diagnostic")
    next(b for b in app.button if b.label == "生成成果包").click().run()
    assert not app.exception
    bundle = app.session_state["bundle_" + project]
    with zipfile.ZipFile(io.BytesIO(bundle["bytes"])) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["kind"] == "diagnostic"
        assert manifest["working"] is True
        assert "diagnostic.json" in archive.namelist()

    next(x for x in app.checkbox if x.label.startswith("我理解恢复备份包含原始材料")).check().run()
    next(b for b in app.button if b.label == "生成私有恢复备份").click().run()
    assert not app.exception
    backup = app.session_state["backup_" + project]["bytes"]
    with zipfile.ZipFile(io.BytesIO(backup)) as archive:
        assert "cra-recovery.json" in archive.namelist()

    next(b for b in app.button if b.label == "＋ 新建 / 恢复研究").click().run()
    assert not app.exception and app.session_state["project"] is None
    recovery = next(x for x in app.get("file_uploader") if x.label.startswith("选择CRA私有恢复备份"))
    recovery.set_value(("recovery.zip", backup, "application/zip")).run()
    next(b for b in app.button if b.label == "导入并验证备份").click().run()
    assert not app.exception, [x.message for x in app.exception]
    restored = app.session_state["project"]
    assert restored != project
    restored_snapshot = app.session_state["workspace"].snapshot(restored)
    assert restored_snapshot["brief"]["name"] == "Synthetic UI roundtrip"
    assert restored_snapshot["materials"]["data"][-1]["records"] == 3
    assert restored_snapshot["status"]["paused"] is True
    assert not restored_snapshot["status"]["approvals"]["authorization"]


def test_ui_settings_save_persists_model_budget_language_and_submission_profile(tmp_path, monkeypatch):
    """Settings controls write the values later used by the real workspace backend."""
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-settings"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    app.text_input[0].set_value("Synthetic settings persistence")
    app.text_area[0].set_value("Verify real saved configuration")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    project = app.session_state["project"]
    workspace = app.session_state["workspace"]

    app.radio[0].set_value("模型与设置").run()
    next(x for x in app.checkbox if x.label == "允许本项目使用模型服务").check()
    next(x for x in app.text_input if x.label == "OpenAI兼容 Base URL").set_value("https://api.example.invalid/v1")
    next(x for x in app.text_input if x.label == "固定模型ID").set_value("synthetic-model-v7")
    next(x for x in app.number_input if x.label == "输入费率 / 百万token").set_value(1.25)
    next(x for x in app.number_input if x.label == "输出费率 / 百万token").set_value(2.5)
    next(x for x in app.number_input if x.label == "本项目累计预算上限").set_value(7.0)
    next(x for x in app.text_input if x.label == "币种").set_value("USD")
    next(x for x in app.selectbox if x.label == "稿件语言").set_value("en")
    next(x for x in app.selectbox if x.label == "规范模式").set_value("ica")
    next(x for x in app.text_input if x.label == "具体期刊 / ICA年份与分会").set_value("ICA 2027 Political Communication")
    next(x for x in app.text_input if x.label == "已查阅的官方规范URL").set_value("https://ica.example.invalid/submission")
    next(x for x in app.text_input if x.label == "查阅日期（YYYY-MM-DD）").set_value("2026-10-30")
    next(x for x in app.text_area if x.label == "规范覆盖范围与限制").set_value("Synthetic fixture: verify settings persistence only.")
    next(b for b in app.button if b.label == "保存项目设置").click().run()
    assert not app.exception, [x.message for x in app.exception]

    saved = workspace.snapshot(project)["brief"]
    assert saved["permissions"]["model"] is True
    assert saved["permissions"]["allowed_hosts"] == ["api.example.invalid"]
    assert saved["model"]["base_url"] == "https://api.example.invalid/v1"
    assert saved["model"]["model"] == "synthetic-model-v7"
    assert saved["model"]["input_per_million"] == 1.25
    assert saved["model"]["output_per_million"] == 2.5
    assert saved["limits"]["max_cost"] == 7.0
    assert saved["limits"]["currency"] == "USD"
    assert saved["language"] == "en"
    assert saved["profile"]["name"] == "ica"
    assert saved["profile"]["target"] == "ICA 2027 Political Communication"
    assert saved["profile"]["sources"][0]["url"] == "https://ica.example.invalid/submission"
    assert workspace.snapshot(project)["status"]["budget"]["calls"] == 0


def test_ui_remote_statistics_scope_requires_consent_and_persists_backend(tmp_path, monkeypatch):
    from cra_remote.protocol import identity
    from cra_workspace import app as app_module

    class RemoteFixture:
        endpoint = "https://synthetic-worker.example.invalid"

        def health(self):
            # Contract fixture: this does not contact or execute on a real server.
            return {"identity": identity()}

    remote = RemoteFixture()
    monkeypatch.setattr(app_module, "operator_executor", lambda: remote)
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-remote-scope"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    app.text_input[0].set_value("Synthetic remote scope")
    app.text_area[0].set_value("Verify separate transfer permission")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    project = app.session_state["project"]
    workspace = app.session_state["workspace"]

    app.radio[0].set_value("模型与设置").run()
    next(x for x in app.checkbox if x.label == "本项目使用上述独立统计服务器").check()
    next(b for b in app.button if b.label == "保存统计执行范围").click().run()
    assert any("请明确允许分析副本" in x.value for x in app.error)
    assert workspace.snapshot(project)["brief"].get("execution", {"backend": "local"})["backend"] == "local"

    next(x for x in app.checkbox if x.label == "我有权并明确同意将本项目经核查的分析副本上传到上述服务器。").check()
    next(b for b in app.button if b.label == "保存统计执行范围").click().run()
    assert not app.exception, [x.message for x in app.exception]
    saved = workspace.snapshot(project)["brief"]
    assert saved["execution"]["backend"] == "remote"
    assert saved["execution"]["endpoint"] == remote.endpoint
    assert saved["permissions"]["remote_statistics"] is True
    assert workspace.snapshot(project)["status"]["budget"]["calls"] == 0


def test_ui_literature_evidence_and_protocol_forms_create_backend_objects(tmp_path, monkeypatch):
    """Synthetic end-to-end flow from UI data/source uploads to a validated plan."""
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-research-plan"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    assert not app.exception
    app.text_input[0].set_value("Synthetic evidence to protocol")
    app.text_area[0].set_value("Does x relate to y in this generated dataset?")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    project = app.session_state["project"]
    workspace = app.session_state["workspace"]

    app.radio[0].set_value("材料与测量").run()
    next(x for x in app.get("file_uploader") if x.label.startswith("接入CSV或Stata")).set_value(
        ("fixture.csv", b"x,y\n1,2\n2,4\n3,5\n4,8\n", "text/csv")
    ).run()
    next(b for b in app.button if b.label == "读取并登记数据").click().run()
    assert not app.exception
    next(x for x in app.text_input if x.label == "实际核查人").set_value("TEST FIXTURE ONLY")
    next(x for x in app.text_area if x.label.startswith("核查依据：")).set_value("TEST FIXTURE ONLY; synthetic scale and coding")
    next(x for x in app.checkbox if x.label.startswith("我已核查以上题项")).check()
    next(b for b in app.button if b.label == "保存核查后的分析副本").click().run()
    assert not app.exception
    assert workspace.snapshot(project)["measurement_reviewed"] is True

    app.radio[0].set_value("文献与证据").run()
    excerpt = b"Synthetic excerpt: respondents infer foreign public sentiment from cross-national media exposure.\n\nThis is a fabricated fixture, not a real citation."
    next(x for x in app.get("file_uploader") if x.label.startswith("接入有权使用的文献")).set_value(
        ("fixture.md", excerpt, "text/markdown")
    ).run()
    next(b for b in app.button if b.label == "登记文献材料").click().run()
    assert not app.exception

    for label, value in {
        "文献ID（英文字母/数字/下划线）": "synthetic_ref",
        "证据片段ID（全项目唯一）": "synthetic_span",
        "题名": "Synthetic source fixture",
        "作者（用分号分隔，保留原文署名）": "Example Author",
        "出版年份": "2026",
        "期刊/出版来源": "Synthetic Journal",
        "来源URL": "https://example.invalid/source",
        "从上方实际位置摘取原文（至少8个字符）": "respondents infer foreign public sentiment",
        "该片段支持或反驳哪项论断？": "Foreign attitudes are perceived by respondents.",
        "实际审阅者": "TEST FIXTURE ONLY",
        "核查依据与条件限制（至少8个字符）": "Synthetic fixture only; no real source was reviewed.",
    }.items():
        widget = next(x for x in (*app.text_input, *app.text_area) if x.label == label)
        widget.set_value(value)
    next(x for x in app.selectbox if x.label == "论断支持判断").set_value("supported")
    next(x for x in app.checkbox if x.label.startswith("我已核对作者")).check()
    next(b for b in app.button if b.label == "保存题录与证据定位").click().run()
    assert not app.exception, [x.message for x in app.exception]
    references = workspace.references(project)
    assert references[0]["id"] == "synthetic_ref"
    assert references[0]["spans"][0]["id"] == "synthetic_span"
    assert references[0]["spans"][0]["status"] == "supported"

    app.radio[0].set_value("研究计划").run()
    next(x for x in app.text_area if x.label == "正式研究问题").set_value("Among generated cases, how is x associated with y?")
    next(x for x in app.text_area if x.label == "理论贡献或拟检验的理论张力").set_value("Synthetic relationship used only to exercise the planning form.")
    next(x for x in app.text_area if x.label == "竞争解释及可区分/不可区分的证据").set_value("Generated values are fixed; this fixture makes no real theoretical claim.")
    next(x for x in app.text_area if x.label == "测量、样本与解释边界").set_value("Synthetic four-row sample; no population or causal inference.")
    next(x for x in app.multiselect if x.label == "理论依据的已核查证据ID").set_value(["synthetic_span"])
    next(x for x in app.text_area if x.label.startswith("冻结前已经接触过哪些数据")).set_value("All synthetic rows were visible before this plan was saved.")
    next(x for x in app.selectbox if x.label == "主要因变量").set_value("y")
    next(x for x in app.multiselect if x.label == "解释变量（不要包含因变量）").set_value(["x"])
    next(b for b in app.button if b.label == "校验并保存计划草案").click().run()
    assert not app.exception, [x.message for x in app.exception]
    snapshot = workspace.snapshot(project)
    protocol = snapshot["protocol_source"]
    assert protocol["rq"] == "Among generated cases, how is x associated with y?"
    assert protocol["models"][0]["y"] == "y"
    assert protocol["models"][0]["x"] == ["x"]
    assert protocol["theory"]["evidence_ids"] == ["synthetic_span"]
    assert not snapshot["status"]["approvals"]["protocol"]


def test_ui_run_button_calls_backend_and_refuses_without_current_authorization(tmp_path, monkeypatch):
    """A click reaches the real service gate and starts no work before approval."""
    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-run-gate"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    app.text_input[0].set_value("Synthetic run authorization gate")
    app.text_area[0].set_value("Ensure no run bypasses current project authorization")
    app.checkbox[0].check()
    next(b for b in app.button if b.label == "建立研究项目").click().run()
    project = app.session_state["project"]
    workspace = app.session_state["workspace"]
    app.radio[0].set_value("材料与测量").run()
    next(x for x in app.get("file_uploader") if x.label.startswith("接入CSV或Stata")).set_value(
        ("fixture.csv", b"x,y\n1,2\n2,4\n3,6\n", "text/csv")
    ).run()
    next(b for b in app.button if b.label == "读取并登记数据").click().run()
    app.radio[0].set_value("研究概览").run()
    run_button = next(b for b in app.button if b.label == "继续执行获批研究")
    assert not run_button.disabled
    run_button.click().run()
    assert any("请先批准当前项目授权" in x.value for x in app.error)
    snapshot = workspace.snapshot(project)
    assert not snapshot["running"]
    assert snapshot["status"]["budget"]["calls"] == 0
    assert not snapshot["status"]["approvals"]["authorization"]


def test_ui_narrative_form_persists_evidence_anchored_text_without_model_call(tmp_path, monkeypatch):
    from cra_engine.literature import build_corpus
    from cra_engine.runtime import sync

    monkeypatch.setenv("CRA_WORKSPACE_ROOT", str(tmp_path / "ui-narrative"))
    monkeypatch.setenv("CRA_DEPLOYMENT", "local")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"), default_timeout=15).run()
    workspace = app.session_state["workspace"]
    project = workspace.create("Synthetic narrative UI", "Verify evidence-bound manuscript input", synthetic=True)["project_id"]
    workspace.import_data(project, "fixture.csv", b"x,y\n1,2\n2,3\n3,4\n")
    source_text = b"Synthetic excerpt: generated respondents describe a perceived foreign attitude.\n\nThis is a fabricated source fixture."
    source = workspace.upload_literature(project, "fixture.md", source_text)
    workspace.save_reference(project, {
        "id": "synthetic_ref", "title": "Synthetic citation fixture", "authors": ["Example Author"],
        "year": "2026", "source": "Synthetic Journal", "url": "https://example.invalid/source", "doi": "",
        "metadata_declaration": {"reviewer": "TEST FIXTURE ONLY", "note": "Synthetic fixture metadata only."},
        "spans": [{"id": "synthetic_span", "path": source["path"], "locator": {"paragraph": 1},
                   "quote": "generated respondents describe a perceived foreign attitude", "claim": "Perceived foreign attitude",
                   "status": "supported", "reviewer": "TEST FIXTURE ONLY", "note": "Synthetic fixture only; no real literature checked.",
                   "permitted_for_model": False}],
    })
    with workspace._store(project) as store:
        brief = sync(store)
        corpus = build_corpus(store.root, brief)
        with store.tx():
            store.put("corpus", "corpus", corpus)
            store.put("claims", "claims", {"schema_version": 2, "analysis_hash": "SYNTHETIC", "items": [
                {"id": "main_n", "kind": "statistic", "source": "analysis", "model": "main", "field": "n", "value": 3, "text": "Synthetic N"}
            ]})
    app.session_state["project"] = project
    app.session_state["route"] = "稿件与交付"
    app.run()
    assert not app.exception
    narrative = {
        "introduction": "This synthetic introduction is anchored to [[cite:synthetic_ref]].",
        "theory": "This synthetic theory note cites [[cite:synthetic_ref]].",
        "discussion": "The generated sample size is {{claim:main_n}}.",
        "limitations": "This fixture contains no real respondents or population-level evidence.",
    }
    for label, value in (("引言", narrative["introduction"]), ("理论", narrative["theory"]),
                         ("讨论", narrative["discussion"]), ("限制", narrative["limitations"])):
        next(x for x in app.text_area if x.label == label).set_value(value)
    next(b for b in app.button if b.label == "保存写作材料并校验证据").click().run()
    assert not app.exception, [x.message for x in app.exception]
    assert not app.error, [x.value for x in app.error]
    saved = workspace.snapshot(project)
    assert saved["draft_source"] == narrative
    assert saved["status"]["budget"]["calls"] == 0


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
