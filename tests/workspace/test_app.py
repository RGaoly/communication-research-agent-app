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
