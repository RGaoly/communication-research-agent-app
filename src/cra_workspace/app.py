"""Streamlit presentation over the real, session-owned research service.

No widget inserts human approvals or research results. Mutation buttons execute
only inside their submit branch; polling only reads persisted project state.
"""
import copy
import datetime
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

import streamlit as st

from cra_engine.common import EngineError
from .service import Workspace
from . import environment

PAGES = ["研究概览", "材料与测量", "文献与证据", "研究计划", "分析结果", "稿件与交付", "模型与设置"]
TASK_NAMES = dict(audit="数据审计", corpus="文献定位", protocol="研究设计", analysis="统计分析", claims="发现与证据", draft="研究稿", method_review="方法复核", evidence_review="论述复核")
STATES = dict(pending="待开始", ready="就绪", running="执行中", waiting_human="待你确认", blocked="已阻断", succeeded="已完成", failed="执行失败", cancelled="已取消", stale="输入已变化")
SCOPES = dict(authorization="项目授权", protocol="研究计划冻结", final="成果终审")


def stylesheet():
    st.markdown("""<style>
    :root {--ink:#172b32;--muted:#65787b;--accent:#126c60;}
    .stApp {background:#f6f7f4;color:var(--ink);font-family:'Noto Sans SC',sans-serif}
    [data-testid=stSidebar] {background:#edf1ec;border-right:1px solid #dce4dc}
    .block-container {max-width:1240px;padding-top:2rem;padding-bottom:4rem}
    h1 {font-size:2rem!important;letter-spacing:-.04em;font-weight:700!important}
    h2 {font-size:1.35rem!important} h3 {font-size:1.05rem!important}
    [data-testid=stMetric] {background:white;border:1px solid #dce4dc;border-radius:14px;padding:18px}
    [data-testid=stMetricValue] {font-size:1.65rem!important;font-variant-numeric:tabular-nums}
    [data-testid=stForm] {background:white;border-radius:14px}
    .brand {font-size:11px;letter-spacing:.15em;color:#52746c;font-weight:700;margin-bottom:14px}
    .lede {color:#65787b;font-size:15px;margin-bottom:24px;line-height:1.8}
    div.stButton>button, div.stDownloadButton>button {border-radius:9px;min-height:42px}
    a {color:#126c60} [data-testid=stStatusWidget] {visibility:hidden}
    @media(max-width:640px){.block-container{padding:1rem}.stMetric{padding:10px}}
    </style>""", unsafe_allow_html=True)


def notice(text, error=False):
    st.session_state["flash"] = (text, error)


def act(fn, success="已保存。"):
    """Keep provider errors and arbitrary exception representations out of the UI."""
    try:
        result = fn()
        notice(success)
        return result
    except (EngineError, ValueError, TypeError, KeyError) as exc:
        st.error(str(exc) if isinstance(exc, EngineError) else "输入格式无效，请检查必填项、类型和JSON结构。")
    except Exception:
        st.error("操作未完成。请检查文件与服务状态；原始材料和错误详情不会回显。")
    return None


def value(s, name):
    obj = s["objects"].get(name)
    return obj["value"] if obj and not obj["stale"] else None


def literal(text):
    return "".join("\\" + c if c in "\\`*_{}[]()#+-.!<>" else c for c in str(text))


def manuscript(text):
    # Research prose is untrusted. Plain paragraphs prevent model-supplied image
    # URLs/HTML from making browser requests to unapproved third parties.
    for paragraph in text.split("\n\n"):
        if paragraph.startswith("## ") and "\n" not in paragraph:
            st.subheader(literal(paragraph[3:]))
        else:
            st.text(paragraph)


@st.cache_data(ttl=300, show_spinner="正在检查云端执行环境，不调用模型…")
def hosting_environment(source_identity, _remote=None):
    # This cached value contains host capabilities only, never project state,
    # materials, credentials or review declarations.
    return environment.inspect_host(_remote) if _remote is not None else environment.inspect_host()


def operator_executor():
    """Deployment-only credential; never a user model key or project field."""
    from cra_remote.client import RemoteExecutor
    endpoint, token = os.environ.get("CRA_WORKER_URL", ""), os.environ.get("CRA_WORKER_TOKEN", "")
    try:
        configured = st.secrets.get("statistics_worker", {})
        endpoint, token = configured.get("url", endpoint), configured.get("token", token)
    except (FileNotFoundError, KeyError): pass
    if not endpoint and not token: return None
    return RemoteExecutor(endpoint, token)


def object_view(s, name):
    obj = s["objects"].get(name)
    if not obj:
        st.info("尚未生成" + TASK_NAMES.get(name, name) + "。")
    elif obj["stale"]:
        st.warning("输入已经变化，此产物已过期。重新运行后才能用于当前结论。")
        with st.expander("查看历史产物（不可用于当前交付）"): st.json(obj["value"])
    else:
        st.caption("版本 " + str(obj["version"]) + " · SHA256 " + obj["hash"][:16])
        st.json(obj["value"])


def upload_consent(key, description):
    w = st.session_state.workspace
    if w.deployment != "cloud": return True
    return st.checkbox("我有权处理这些材料，同意将所选" + description + "上传至本云端服务处理；已检查识别信息和使用权限。", key=key)


def dismiss_review():
    st.session_state.pop("pending_review", None)


def choose_project():
    st.session_state.project = st.session_state.project_picker
    st.session_state.pop("pending_review", None)
    if st.session_state.project is None: st.session_state.route = PAGES[0]


@st.dialog("审阅并确认当前版本", width="large", on_dismiss=dismiss_review)
def review_dialog(w, p, scope, challenge, s):
    st.subheader(SCOPES[scope])
    st.caption("这是你的项目内确认声明，不是身份认证、伦理批准或独立专家验收。")
    if scope == "authorization":
        st.json({"question": s["brief"]["theme"], "objective": s["brief"]["objective"], "permissions": s["brief"]["permissions"], "model": s["brief"]["model"], "limits": s["brief"]["limits"], "processing": w.deployment, "statistics_execution": s["brief"].get("execution", {"backend": "local"})})
        st.warning("允许模型运行后，系统可在这份预算与权限范围内继续研究调用。连接契约测试本身包含两次付费请求；暂停不会自动撤回已经发出的请求。")
    elif scope == "protocol":
        st.json(value(s, "protocol"))
        st.json(value(s, "audit"))
        st.caption("请核对变量、缺失与排除规则、全部模型、竞争解释及接触过的结果。冻结不构成事前预注册。")
    else:
        st.json(s["status"]["readiness"])
        st.json(value(s, "method_review")); st.json(value(s, "evidence_review"))
        manuscript((value(s, "draft") or {}).get("text", "尚无稿件"))
    st.code(challenge["confirmation"], language=None)
    with st.form("human_review_" + scope):
        reviewer = st.text_input("实际审阅者姓名或项目代号")
        note = st.text_area("审阅依据与判断（至少8个字符）")
        confirmation = st.text_input("输入上方版本确认短语")
        reviewed = st.checkbox("我已查看这一版本的材料，并作出上述判断。")
        submitted = st.form_submit_button("记录我的确认", type="primary")
    if submitted:
        result = act(lambda: w.approve(p, scope, challenge["nonce"], confirmation, reviewer, note, reviewed), "已记录当前版本的确认。")
        if result:
            dismiss_review()
            st.rerun()
    if st.button("暂不确认，返回检查材料"):
        dismiss_review()
        st.rerun()


def confirm_button(w, p, scope, s, disabled=False):
    label = SCOPES[scope] + (" · 已确认" if s["status"]["approvals"][scope] else " · 待确认")
    if st.button(label, key="approve_" + scope, disabled=disabled or s["running"], width="stretch"):
        challenge = act(lambda: w.challenge(p, scope), "已打开当前版本供你审阅。")
        if challenge:
            st.session_state.pending_review = {"project": p, "scope": scope, "challenge": challenge}
            st.rerun()


def home(w):
    st.markdown('<div class="brand">COMMUNICATION RESEARCH AGENT</div>', unsafe_allow_html=True)
    st.title("让研究，从一个问题开始。")
    st.markdown('<div class="lede">接入材料，核查测量，执行获批分析，让每个结论都能回到证据。</div>', unsafe_allow_html=True)
    with st.form("create_project"):
        name = st.text_input("研究名称", placeholder="为这项研究起一个容易识别的名字")
        question = st.text_area("你想回答什么问题？", placeholder="说明研究对象、现象和你想理解的关系")
        objective = st.text_area("预期交付与边界", placeholder="例如：分析报告与研究工作稿；仅解释关联")
        synthetic = st.checkbox("这是工程练习，全部输入均为模拟材料")
        submitted = st.form_submit_button("建立研究项目", type="primary")
    if submitted:
        result = act(lambda: w.create(name, question, objective or question, synthetic), "已建立真实项目记录；尚未授权执行。")
        if result:
            st.session_state.next_project = result["project_id"]
            st.session_state.next_route = PAGES[0]
            st.rerun()
    st.subheader("恢复已有项目")
    st.caption("云端运行空间会重启或回收。恢复备份包含原始材料，请只从受控位置导入；恢复后需要重新确认授权。")
    consent = upload_consent("restore_consent", "恢复备份")
    if consent:
        recovery = st.file_uploader("选择CRA私有恢复备份 · 64MB以内", type=["zip"], key="recovery_file", max_upload_size=64)
        if st.button("导入并验证备份", disabled=recovery is None):
            result = act(lambda: w.restore(recovery.getvalue(), cloud_consent=consent), "已恢复到新项目，既有项目未被覆盖。")
            if result:
                st.session_state.next_project = result["project_id"]
                st.rerun()


def overview(w, p, s):
    st.title(literal(s["brief"]["name"]))
    st.text(s["brief"]["theme"])
    budget, state = s["status"]["budget"], s["status"]
    row = st.columns(4)
    data = s["materials"]["data"]
    row[0].metric("接入记录数", data[-1]["records"] if data else "尚未接入")
    row[1].metric("已完成任务", str(sum(t["status"] == "succeeded" for t in state["tasks"])) + " / " + str(len(state["tasks"])) if state["tasks"] else "尚未规划")
    row[2].metric("模型累计估算 · " + budget["currency"], "%.6f" % budget["spent"])
    row[3].metric("剩余预算 · " + budget["currency"], "%.6f" % budget["remaining"])
    if s["synthetic"]: st.warning("模拟项目 · 本项目不能作为真实实证研究或真实试点证据。")
    job = s["job"] or {}
    if s["running"]: st.info("正在执行。状态来自后台记录；可以安全暂停，已发出请求的结果和账单仍需核对。")
    elif state["complete"]: st.success("当前成果已完成项目内终审。对外提交仍需你另行决定。")
    else: st.info("研究进行中 · 尚未完成终审。" + (" 当前已暂停。" if state["paused"] else ""))
    if job.get("message"): st.error(job["message"])
    if state.get("last_problem"):
        with st.expander("当前执行问题", expanded=True): st.json(state["last_problem"])
    a, b, c = st.columns(3)
    with a: confirm_button(w, p, "authorization", s, disabled=not s["files_ready"])
    with b: confirm_button(w, p, "protocol", s, disabled=value(s, "protocol") is None or not s["measurement_reviewed"])
    with c: confirm_button(w, p, "final", s, disabled=not state["readiness"]["ready_for_final"])
    a, b = st.columns([3, 1])
    capability = st.session_state.get("cloud_environment", {})
    remote = s["brief"].get("execution", {}).get("backend") == "remote"
    matching_backend = bool(capability.get("worker")) == remote
    can_compute = w.deployment != "cloud" or capability.get("passed", False) and matching_backend
    if a.button("继续执行获批研究", type="primary", disabled=s["running"] or not s["files_ready"] or not can_compute, width="stretch"):
        if act(lambda: w.start(p), "后台已启动；完成、阻断或等待确认将如实显示。 "): st.rerun()
    if b.button("安全暂停", disabled=not s["running"], width="stretch"):
        if act(lambda: w.pause(p), "已停止调度新任务，正在结束本地执行并保留检查点。"): st.rerun()
    st.subheader("研究进展")
    st.dataframe([{"任务": TASK_NAMES[t["id"]], "状态": STATES.get(t["status"], t["status"]), "执行次数": t["attempts"], "连续错误": t["error_count"]} for t in state["tasks"]], hide_index=True, width="stretch")
    ready = state["readiness"]
    if ready["blocking_issues"]:
        st.subheader("需要解决的证据与规范问题")
        st.dataframe(ready["blocking_issues"], hide_index=True, width="stretch")
    with st.expander("操作记录（实际事件）"): st.dataframe(s["events"], hide_index=True, width="stretch")


def materials(w, p, s):
    st.title("材料与测量")
    st.write("保留原件，生成分析副本。字段类型、值标签和观测范围需要与你的问卷和代码本逐项核对。")
    consent = upload_consent("data_consent_" + p, "调查数据")
    if consent:
        uploaded = st.file_uploader("接入CSV或Stata DTA · 单份不超过32MB", type=["csv", "dta"], key="datafile_" + p)
        if st.button("读取并登记数据", disabled=uploaded is None or s["running"]):
            if act(lambda: w.import_data(p, uploaded.name, uploaded.getvalue(), cloud_consent=consent), "已保留原件并生成分析副本；请继续核查测量。"): st.rerun()
    if not s["files_ready"]: return
    data = s["materials"]["data"][-1]
    st.text("实际接入：" + data["name"] + " · " + str(data["records"]) + "条记录 · SHA256 " + data["sha256"][:16])
    st.subheader("题项与编码核查")
    st.warning("观测最小值与最大值不是问卷量尺。请依据题干修正量尺，明确拒答/不知道等编码，排除身份字段；不会自动删除样本。")
    book = s["codebook"]
    missing_codes = s.get("missing_codes", {})
    rows = [{"保留": not spec.get("sensitive", False), "变量": name, "类型": spec["type"], "题项含义": spec.get("question", ""), "量尺下界": spec.get("min"), "量尺上界": spec.get("max"), "类别取值JSON": json.dumps(spec.get("allowed", []), ensure_ascii=False), "转为缺失的编码JSON": json.dumps(missing_codes.get(name, []), ensure_ascii=False)} for name, spec in book["columns"].items()]
    with st.form("measurement_" + p):
        edited = st.data_editor(rows, hide_index=True, width="stretch", disabled=["变量"], column_config={"类型": st.column_config.SelectboxColumn(options=["number", "category", "id", "text"])}, key="measurement_grid_" + p + "_" + data["id"])
        reviewer = st.text_input("实际核查人", key="measurement_person")
        note = st.text_area("核查依据：问卷来源、量尺、反向题、缺失处理和排除字段", key="measurement_note")
        confirmed = st.checkbox("我已核查以上题项与编码，保留字段不含可识别信息。")
        submitted = st.form_submit_button("保存核查后的分析副本", disabled=s["running"], type="primary")
    if submitted:
        def commit():
            if not confirmed: raise EngineError("请完成实际核查再确认。")
            revised, missing = copy.deepcopy(book), {}
            revised["columns"] = {}
            for row in edited:
                if not row["保留"]: continue
                name = row["变量"]
                spec = copy.deepcopy(book["columns"][name])
                spec.update(type=row["类型"], question=row["题项含义"])
                if spec["type"] == "number": spec.update(min=row["量尺下界"], max=row["量尺上界"], range_source="researcher_reviewed")
                if spec["type"] == "category": spec["allowed"] = json.loads(row["类别取值JSON"])
                missing[name] = json.loads(row["转为缺失的编码JSON"])
                if not isinstance(missing[name], list) or not all(isinstance(x, str) for x in missing[name]): raise EngineError("缺失编码JSON须为字符串列表，例如 [\"99\"]。")
                revised["columns"][name] = spec
            return w.measurement(p, revised, missing, reviewer, note)
        if act(commit, "已保存新的分析副本与测量声明；受影响的旧结果会失效。"): st.rerun()
    with st.expander("高级测量代码本（量表、分组、权重与设计信息）"):
        st.caption("修改完整JSON后仍须由你核查。复杂抽样、潜变量跨国比较缺乏支持时会阻断分析。")
        with st.form("advanced_measurement_" + p):
            raw = st.text_area("完整代码本JSON", json.dumps(book, ensure_ascii=False, indent=2), height=300, key="book_json_" + p)
            missing_raw = st.text_area("缺失映射JSON", json.dumps(missing_codes, ensure_ascii=False, indent=2), key="book_missing_" + p)
            advanced_reviewer = st.text_input("高级代码本实际核查人")
            advanced_note = st.text_area("高级代码本核查依据")
            advanced_confirmed = st.checkbox("我已核查这份高级代码本及其缺失、量表与设计规则。")
            advanced_submit = st.form_submit_button("采用高级代码本并记录核查声明", disabled=s["running"])
        if advanced_submit:
            if advanced_confirmed:
                if act(lambda: w.measurement(p, json.loads(raw), json.loads(missing_raw), advanced_reviewer, advanced_note)): st.rerun()
            else: st.error("请先核查这份高级代码本并确认。")
    st.subheader("实际审计产物")
    object_view(s, "audit")


def literature(w, p, s):
    st.title("文献与证据")
    st.write("题录存在、读到全文、片段支持论断是不同状态。支持判断由实际审阅者作出，程序只核对定位与格式。")
    consent = upload_consent("lit_consent_" + p, "文献")
    if consent:
        upload = st.file_uploader("接入有权使用的文献 · PDF / TXT / MD / BibTeX / RIS", type=["pdf", "txt", "md", "bib", "ris"], key="litfile_" + p, max_upload_size=20)
        if st.button("登记文献材料", disabled=upload is None or s["running"]):
            if act(lambda: w.upload_literature(p, upload.name, upload.getvalue(), cloud_consent=consent), "文献已登记；题录和论断支持仍需核查。"): st.rerun()
    sources = [r for r in s["materials"]["literature"] if Path(r["path"]).suffix in (".pdf", ".txt", ".md")]
    refs = w.references(p)
    if refs:
        st.subheader("已登记题录")
        st.dataframe([{"ID": r["id"], "题名": r["title"], "年": r["year"], "证据片段": len(r.get("spans", []))} for r in refs], hide_index=True, width="stretch")
    if sources:
        st.subheader("定位原文并记录核查")
        source = st.selectbox("选择已上传材料", sources, format_func=lambda x: x["name"])
        position = st.number_input("PDF页码 / 文本段落（从1开始）", min_value=1, value=1, step=1)
        text = act(lambda: w.literature_text(p, source["id"], int(position)), "")
        if text:
            st.caption(("页" if text["kind"] == "page" else "段落") + f" {position} / {text['total']}")
            st.text_area("原文（仅供核对）", text["text"], height=200, disabled=True)
        with st.form("reference_" + p):
            a, b = st.columns(2)
            rid = a.text_input("文献ID（英文字母/数字/下划线）")
            sid = b.text_input("证据片段ID（全项目唯一）")
            title = st.text_input("题名")
            authors = st.text_input("作者（用分号分隔，保留原文署名）")
            a, b = st.columns(2)
            year = a.text_input("出版年份"); journal = b.text_input("期刊/出版来源")
            url = st.text_input("来源URL"); doi = st.text_input("DOI（可留空）")
            quote = st.text_area("从上方实际位置摘取原文（至少8个字符）")
            claim = st.text_area("该片段支持或反驳哪项论断？")
            support = st.selectbox("论断支持判断", ["pending", "supported", "contradicted"], format_func=lambda x: {"pending": "待核查", "supported": "经实际审阅，支持", "contradicted": "与论断矛盾"}[x])
            reviewer = st.text_input("实际审阅者")
            note = st.text_area("核查依据与条件限制（至少8个字符）")
            metadata = st.checkbox("我已核对作者、年份、题名与来源（项目内声明）")
            egress = st.checkbox("我有权允许模型接收这一原文片段与对应论断")
            submitted = st.form_submit_button("保存题录与证据定位", disabled=s["running"])
        if submitted:
            ref = {"id": rid, "title": title, "authors": [x.strip() for x in authors.split(";") if x.strip()], "year": year, "source": journal, "url": url, "doi": doi, "spans": [{"id": sid, "path": source["path"], "locator": {"page" if Path(source["path"]).suffix == ".pdf" else "paragraph": int(position)}, "quote": quote, "claim": claim, "status": support, "reviewer": reviewer, "note": note, "permitted_for_model": egress}]}
            if metadata: ref["metadata_declaration"] = {"reviewer": reviewer, "note": note}
            if act(lambda: w.save_reference(p, ref), "已保存定位与核查声明；这不代表双专家验收。"): st.rerun()
    with st.expander("高级：修改完整题录（保留多个证据片段）"):
        raw = st.text_area("单条题录JSON", "{}", height=200)
        if st.button("校验并替换同ID题录", disabled=s["running"]):
            if act(lambda: w.save_reference(p, json.loads(raw))): st.rerun()
    st.subheader("当前证据索引")
    object_view(s, "corpus")


def protocol_page(w, p, s):
    st.title("研究计划")
    st.write("先说明理论、测量与推断边界，再冻结模型。所有实际运行的规格都会保留，包括失败和零结果。")
    current = s["protocol_source"] or value(s, "protocol") or {}
    if value(s, "protocol"):
        st.json(value(s, "protocol"))
        confirm_button(w, p, "protocol", s, disabled=not s["measurement_reviewed"])
    if not s["files_ready"]:
        st.info("先接入数据并核查测量，再选择实际变量。")
        return
    from cra_engine.statistics import effective_book
    columns = effective_book(s["codebook"])["columns"]
    numeric = [n for n, v in columns.items() if v["type"] == "number"]
    predictors = [n for n, v in columns.items() if v["type"] in ("number", "category")]
    refs = w.references(p)
    spans = [span["id"] for ref in refs for span in ref.get("spans", []) if span.get("status") == "supported"]
    if not numeric or not spans:
        st.info("生成可执行计划还需要数值型结果变量，以及经过定位和实际审阅的支持证据。可以在模型配置与项目授权后，让系统基于这些材料提出候选计划。")
    else:
        models = current.get("models", [])
        primary = next((m for m in models if m.get("role") == "primary"), models[0] if models else {})
        with st.form("protocol_form_" + p):
            rq = st.text_area("正式研究问题", current.get("rq", s["brief"]["theme"]))
            theory = current.get("theory", {})
            contribution = st.text_area("理论贡献或拟检验的理论张力", theory.get("contribution", ""))
            competing = st.text_area("竞争解释及可区分/不可区分的证据", theory.get("competing_explanation", ""))
            boundary = st.text_area("测量、样本与解释边界", theory.get("boundary", ""))
            evidence = st.multiselect("理论依据的已核查证据ID", spans, default=[x for x in theory.get("evidence_ids", []) if x in spans])
            seen = st.text_area("冻结前已经接触过哪些数据、统计或研究结果？", current.get("results_seen_before_freeze", ""))
            a, b = st.columns(2)
            y = a.selectbox("主要因变量", numeric, index=numeric.index(primary["y"]) if primary.get("y") in numeric else 0)
            xs = b.multiselect("解释变量（不要包含因变量）", predictors, default=[x for x in primary.get("x", []) if x in predictors])
            families, covariances = ["ols", "logit", "wls"], ["HC3", "classical", "cluster"]
            family = a.selectbox("统计方法", families, index=families.index(primary.get("family", "ols")))
            cov = b.selectbox("标准误", covariances, index=covariances.index(primary.get("covariance", "HC3")))
            st.caption("Logit结果必须为0/1；WLS仅支持有依据的逆方差权重；HC3仅适用于非加权OLS。调查权重不能自动替代复杂抽样方差。")
            weight = st.text_input("WLS权重变量（其他方法留空）", primary.get("weight", ""))
            justification = st.text_input("逆方差权重依据（WLS必填）", primary.get("weight_justification", ""))
            cluster = st.text_input("聚类变量（聚类标准误必填）", primary.get("cluster", ""))
            reference = {name: st.selectbox("类别参照组 · " + name, spec["allowed"], index=spec["allowed"].index(primary.get("reference", {}).get(name)) if primary.get("reference", {}).get(name) in spec["allowed"] else 0) for name, spec in columns.items() if spec["type"] == "category"}
            exploratory = st.checkbox("这是一项探索性研究，终审成果必须保留探索标记", value=current.get("exploratory", False))
            submitted = st.form_submit_button("校验并保存计划草案", type="primary", disabled=s["running"])
        if submitted:
            def commit():
                model = dict(primary, id=primary.get("id", "main"), family=family, role=primary.get("role", "primary"), y=y, x=xs, covariance=cov, reference={k: v for k, v in reference.items() if k in xs})
                for field in ("weight", "weight_kind", "weight_justification", "cluster"):
                    model.pop(field, None)
                if weight: model.update(weight=weight, weight_kind="inverse_variance", weight_justification=justification)
                if cluster: model["cluster"] = cluster
                revised = copy.deepcopy(current)
                revised.update(schema_version=2, rq=rq, inference="association", missing="complete_case", results_seen_before_freeze=seen, theory={"contribution": contribution, "competing_explanation": competing, "boundary": boundary, "evidence_ids": evidence}, models=[model if m is primary else copy.deepcopy(m) for m in models] if models else [model], exploratory=exploratory)
                revised.setdefault("candidates", [])
                revised.setdefault("exclusions", [])
                return w.save_protocol(p, revised)
            if act(commit, "计划草案已保存，尚未冻结；请审阅当前版本再确认。"): st.rerun()
    with st.expander("高级计划：多个模型、稳健性与排除规则"):
        raw = st.text_area("完整计划JSON", json.dumps(current, ensure_ascii=False, indent=2), height=320)
        if st.button("校验并保存完整计划", disabled=s["running"]):
            if act(lambda: w.save_protocol(p, json.loads(raw)), "已保存完整计划草案，需重新冻结。"): st.rerun()


def results(w, p, s):
    st.title("分析结果")
    st.caption("统计量直接读取实际执行产物。过期结果不会作为当前结论显示；关联证据不会自动转为因果。")
    analysis = value(s, "analysis")
    if not analysis:
        object_view(s, "analysis")
    else:
        import pandas as pd
        import altair as alt
        for model in analysis["models"]:
            st.subheader(model["id"] + " · " + model["family"].upper())
            a, b, c = st.columns(3)
            a.metric("模型样本 N", model["n"]); b.metric("因缺失未入模型", model["missing_dropped"]); c.metric("标准误", model["covariance"])
            st.write("因变量：", model["outcome"], "　解释变量：", "、".join(model["predictors"]))
            frame = pd.DataFrame(model["parameters"])
            st.dataframe(frame, hide_index=True, width="stretch")
            plot = frame[frame.term != "const"]
            if not plot.empty:
                base = alt.Chart(plot).encode(y=alt.Y("term:N", title="参数"))
                interval = base.mark_rule(color="#126c60").encode(x=alt.X("ci_low:Q", title="估计值与95%置信区间"), x2="ci_high:Q")
                points = base.mark_point(filled=True, size=75, color="#126c60").encode(x="estimate:Q", tooltip=list(frame.columns))
                zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(strokeDash=[4, 4], color="#83938d").encode(x="zero:Q")
                st.altair_chart(interval + points + zero, width="stretch")
            st.json({"fit": model["fit"], "diagnostics": model["diagnostics"], "reference": model["reference"], "clusters": model["clusters"]})
        if st.button("从授权输入独立重算并对账", disabled=s["running"]):
            report = act(lambda: w.reproduce(p), "已完成实际重算，请查看差异报告。")
            if report:
                st.session_state["reproduction_" + p] = report
                st.rerun()
    if "reproduction" in s["objects"]:
        st.subheader("最近一次独立复现")
        object_view(s, "reproduction")
    st.subheader("全部已执行规格")
    if s["specifications"]: st.json(s["specifications"])
    else: st.info("尚未执行任何规格。")
    with st.expander("论断与计算证据映射"): object_view(s, "claims")
    with st.expander("方法复核"): object_view(s, "method_review")


def deliver(w, p, s):
    st.title("稿件与交付")
    draft = value(s, "draft")
    if draft: manuscript(draft["text"])
    else: object_view(s, "draft")
    with st.expander("编辑证据约束的写作材料", expanded=not draft):
        st.caption("保存后使用你提供的四节文字生成稿件；即使启用模型，也不会自动改写这些文字。复核问题需由你修订。数字必须用 {{claim:ID}}，引文用 [[cite:文献ID]]；系统会校验实际证据。")
        claims = value(s, "claims")
        if claims: st.json(claims)
        original = s["draft_source"] or {}
        with st.form("narrative_" + p):
            narrative = {k: st.text_area(label, original.get(k, ""), height=150) for k, label in [("introduction", "引言"), ("theory", "理论"), ("discussion", "讨论"), ("limitations", "限制")]}
            submitted = st.form_submit_button("保存写作材料并校验证据", disabled=s["running"] or claims is None)
        if submitted:
            if act(lambda: w.save_narrative(p, narrative), "写作材料已保存，请继续运行以重新生成与复核稿件。"): st.rerun()
    with st.expander("证据与论述复核"): object_view(s, "evidence_review")
    confirm_button(w, p, "final", s, disabled=not s["status"]["readiness"]["ready_for_final"])
    st.subheader("导出真实成果")
    st.caption("工作稿、终审包和不可行诊断分别标记。DOCX可编辑；完整APA/ICA/CSSCI排版及正式投稿仍需核查。")
    kind = st.selectbox("成果类型", ["working", "final", "diagnostic"], format_func=lambda k: {"working": "研究工作稿（允许未终审）", "final": "当前终审成果包", "diagnostic": "诊断与交接包"}[k])
    include = st.checkbox("成果包包含分析数据（另行共享授权）")
    sharing = st.checkbox("我有权将包内数据交给接收方，已核对共享范围。", disabled=not include)
    if st.button("生成成果包", disabled=s["running"]):
        bundle = act(lambda: w.export(p, kind, include, sharing), "成果包已按当前实际产物生成。")
        if bundle: st.session_state["bundle_" + p] = bundle
    bundle = st.session_state.get("bundle_" + p)
    if bundle:
        st.caption("已生成的固定版本 · SHA256 " + bundle["sha256"] + "；后续修改不会改写这份下载文件。")
        st.download_button("下载已生成成果包", bundle["bytes"], bundle["filename"], "application/zip")
    st.subheader("私有恢复备份")
    st.caption("包含项目状态、原始材料与历史声明；不含会话密钥。备份用于恢复，不是公开发布包。云端会回收运行空间，请及时下载。")
    private = st.checkbox("我理解恢复备份包含原始材料，将保存到受控位置。")
    if st.button("生成私有恢复备份", disabled=s["running"] or not private):
        backup = act(lambda: w.backup(p, private), "私有恢复备份已生成，请下载并妥善保存。")
        if backup: st.session_state["backup_" + p] = backup
    backup = st.session_state.get("backup_" + p)
    if backup: st.download_button("下载私有恢复备份", backup["bytes"], backup["filename"], "application/zip")


def settings(w, p, s):
    st.title("模型与设置")
    brief = s["brief"]
    st.subheader("统计执行位置")
    scope = brief.get("execution", {"backend": "local"})
    st.text("当前：" + ("独立服务器 · " + scope["endpoint"] if scope["backend"] == "remote" else "工作台所在机器"))
    if w.remote_executor is not None:
        st.text("可用独立服务器：" + w.remote_executor.endpoint)
        st.caption("只发送已核查的分析CSV、代码本与冻结方案；原始上传文件、私人文献、模型密钥及人工批准记录不会发送。服务器材料默认约24小时后清理，保留不含材料的任务索引以防重复执行；备份不包含服务器凭证。")
        capability = st.session_state.get("cloud_environment", {})
        from cra_remote.protocol import identity
        from cra_engine.common import digest
        expected = digest(identity())
        with st.form("execution_scope_" + p):
            enabled = st.checkbox("本项目使用上述独立统计服务器", value=scope["backend"] == "remote")
            consent = st.checkbox("我有权并明确同意将本项目经核查的分析副本上传到上述服务器。")
            submitted = st.form_submit_button("保存统计执行范围", disabled=s["running"])
        if submitted:
            if act(lambda: w.configure_execution(p, enabled, consent, expected), "统计执行范围已保存，请重新审阅项目授权。"):
                hosting_environment.clear(); st.rerun()
    else:
        st.info("尚未接入独立统计服务器。管理员完成部署后，这里会显示真实地址与项目授权选项。")
    key_field = "api_key_input_" + p
    if st.session_state.pop("clear_api_key_input_" + p, False): st.session_state[key_field] = ""
    with st.expander("运行环境检查（不调用模型）", expanded=s["environment"] is not None and not s["environment"]["passed"]):
        st.caption("检查当前项目选择的执行位置及已配置的独立服务器；不调用模型、不上传研究材料。安装了依赖不代表托管平台允许隔离。")
        if st.button("执行环境自检", disabled=s["running"]):
            if act(lambda: w.check_environment(p), "环境检查已完成，请查看实际结果。"):
                hosting_environment.clear()
                st.rerun()
        if s["environment"]:
            remote_check = s["environment"].get("remote_worker_check")
            if not s["environment"]["passed"]:
                if remote_check and remote_check.get("passed"):
                    st.warning("当前项目仍使用工作台所在机器，本机隔离自检未通过；独立服务器健康检查通过。要远程运行，请在上方单独选择服务器并明确同意传输。本次没有上传材料。")
                else:
                    st.error(s["environment"]["message"])
            st.json(s["environment"])
            if remote_check and not remote_check.get("passed"):
                st.error(remote_check.get("message", "独立服务器检查未通过；没有发送研究材料。"))
    st.caption("保存配置不会自动发起模型请求，也不等于研究授权。模型密钥只留在此会话的服务进程内存；配置变化、到期、清除或终审后失效。")
    brief = s["brief"]
    with st.form("settings_" + p):
        enabled = st.checkbox("允许本项目使用模型服务", value=brief["permissions"]["model"])
        model = brief["model"]
        base = st.text_input("OpenAI兼容 Base URL", model["base_url"], placeholder="https://api.example.com/v1")
        model_id = st.text_input("固定模型ID", model["model"])
        st.caption("请从厂商控制台核对可用模型和价格。以下采用你配置的每百万token费率估算；缓存折扣、峰谷价与实际账单可能不同。建议填最高适用费率。")
        a, b = st.columns(2)
        inp = a.number_input("输入费率 / 百万token", min_value=0.0, value=float(model["input_per_million"]), format="%.6f", step=0.01)
        out = b.number_input("输出费率 / 百万token", min_value=0.0, value=float(model["output_per_million"]), format="%.6f", step=0.01)
        budget = a.number_input("本项目累计预算上限", min_value=0.0, value=float(brief["limits"]["max_cost"]), step=1.0)
        currency = b.text_input("币种", brief["limits"]["currency"])
        cap = a.number_input("单次输出token上限", min_value=100, max_value=16000, value=model["max_output_tokens"], step=100)
        seconds = b.number_input("授权运行时长 / 秒", min_value=1, max_value=86400, value=brief["limits"]["max_seconds"])
        mincell = a.number_input("聚合结果最小单元格", min_value=2, max_value=10000, value=brief["limits"]["min_cell"])
        lang = b.selectbox("稿件语言", ["zh-CN", "en"], index=0 if brief["language"].startswith("zh") else 1)
        st.subheader("目标规范")
        profile_name = st.selectbox("规范模式", ["apa7", "ica", "cssci", "custom"], index=["apa7", "ica", "cssci", "custom"].index(brief["profile"]["name"]))
        target = st.text_input("具体期刊 / ICA年份与分会", brief["profile"]["target"])
        existing_sources = brief["profile"]["sources"]
        official = next((x for x in existing_sources if x.get("kind") == "official"), {})
        source_url = st.text_input("已查阅的官方规范URL", official.get("url", ""), placeholder="请填写实际查阅的官方网页地址")
        source_date = st.text_input("查阅日期（YYYY-MM-DD）", official.get("accessed_at", ""))
        source_note = st.text_area("规范覆盖范围与限制", official.get("note", ""), placeholder="说明核查了哪些要求；不等于完整投稿格式已通过")
        with st.expander("高级：其余规范来源与明确检查规则"):
            extra_sources = st.text_area("其余来源JSON", json.dumps([x for x in existing_sources if x is not official], ensure_ascii=False, indent=2))
        submitted = st.form_submit_button("保存项目设置", disabled=s["running"], type="primary")
    if submitted:
        def commit():
            revised_model = dict(model, base_url=base.strip().rstrip("/"), model=model_id.strip(), input_per_million=inp, output_per_million=out, max_output_tokens=int(cap))
            permissions = dict(brief["permissions"], model=enabled)
            permissions["allowed_hosts"] = [urlsplit(base).hostname] if enabled else []
            sources = json.loads(extra_sources)
            if source_url:
                datetime.date.fromisoformat(source_date)
                sources = [dict(official, kind="official", url=source_url, accessed_at=source_date, note=source_note)] + sources
            return w.save_brief(p, {"language": lang, "model": revised_model, "permissions": permissions, "limits": dict(brief["limits"], max_cost=budget, currency=currency, max_seconds=int(seconds), min_cell=int(mincell)), "profile": {"name": profile_name, "target": target, "sources": sources}})
        if act(commit, "设置已保存。权限或预算变化后，需在研究概览重新审阅项目授权。"): st.rerun()
    st.subheader("本次会话密钥")
    st.text("当前生效配置：" + (brief["model"]["model"] + " · " + brief["model"]["base_url"] if brief["permissions"]["model"] else "离线，尚未启用模型服务"))
    st.caption("连接和研究请求只使用已保存配置。修改上方字段后，请先保存，再填写对应厂商的密钥。")
    st.write("状态：", "当前配置的密钥已填入内存" if s["has_session_key"] else "尚未填写或已失效")
    # clear_on_submit removes the password widget value after it has been handed
    # to the short-lived vault; never place it in a cached global/environment.
    with st.form("key_" + p, clear_on_submit=True):
        key = st.text_input("API Key", type="password", autocomplete="new-password", key=key_field)
        key_consent = st.checkbox("我同意该密钥仅在当前会话中用于本项目，并向已保存端点 " + (brief["model"]["base_url"] or "（尚未设置）") + " 发送获批内容。")
        key_submit = st.form_submit_button("使用此密钥", disabled=s["running"])
    if key_submit:
        if not key_consent: st.error("请先确认本次密钥使用范围。")
        elif act(lambda: w.set_key(p, key), "密钥已留在当前会话内存；未发起模型调用。"): st.rerun()
    a, b = st.columns(2)
    if a.button("清除密钥并暂停", width="stretch"):
        if act(lambda: w.clear_key(p), "已清除会话密钥并请求暂停；已发出的请求仍需核对。"):
            st.session_state["clear_api_key_input_" + p] = True
            st.rerun()
    if b.button("验证模型契约 · 两次付费请求", disabled=s["running"] or not s["has_session_key"], width="stretch"):
        if act(lambda: w.start(p, model_test=True), "已在项目授权预算内启动两次接口契约请求；不等于科研能力盲测。"): st.rerun()
    if s.get("model_contract"):
        st.success("当前模型配置已通过接口契约检查 · " + s["model_contract"]["at"])
    else:
        st.info("当前模型配置尚未通过接口契约检查。")
    job = s.get("job") or {}
    if job.get("kind") == "model_contract" and s["running"]:
        st.info("接口检查正在后台执行；可刷新查看结果与实际费用记录。")
    if job.get("message"):
        st.error(job["message"])
    if st.button("刷新执行状态与费用"):
        st.rerun()
    st.subheader("费用与待核对请求")
    st.json(s["status"]["budget"])
    if s["calls"]: st.dataframe(s["calls"], hide_index=True, width="stretch")
    uncertain = [c["id"] for c in s["calls"] if c["status"] == "uncertain"]
    if uncertain:
        with st.form("billing_" + p):
            call = st.selectbox("待核对请求", uncertain)
            actual = st.number_input("已从厂商账单核对的实际费用", min_value=0.0, format="%.6f", step=0.000001)
            note = st.text_area("实际账单核对依据")
            confirmed = st.checkbox("我已核对结果与费用，允许记录这一账单。")
            commit_billing = st.form_submit_button("登记核对结果", disabled=s["running"])
        if commit_billing:
            if act(lambda: w.reconcile(p, call, actual, note, confirmed), "已登记实际账单核对结果。"): st.rerun()
    st.caption("未决付费请求不会自动重发；费用是按配置费率估算的项目账本，并非厂商最终账单。")


def main():
    st.set_page_config(page_title="Communication Research Agent · 研究工作台", page_icon="◒", layout="wide")
    stylesheet()
    if "next_route" in st.session_state:
        st.session_state.route = st.session_state.pop("next_route")
    if "next_project" in st.session_state:
        st.session_state.project = st.session_state.pop("next_project")
        st.session_state.project_picker = st.session_state.project
    previous = st.session_state.get("workspace")
    if previous is not None and not isinstance(previous, Workspace):
        # A live Streamlit code update can retain an instance of the previous
        # class. Keep its project namespace, never its credential/review vault.
        for folder in previous.directory.iterdir():
            if folder.is_dir(): previous.credentials.clear(folder.name)
        for key in list(st.session_state):
            if key.startswith("api_key_input_"): st.session_state[key] = ""
        active = [(p, thread) for p, thread in previous._threads.items() if thread.is_alive()]
        if active:
            if st.session_state.get("upgrade_pause_requested") != id(previous):
                for project, _ in active: previous.pause(project)
                st.session_state.upgrade_pause_requested = id(previous)
            st.warning("应用版本已更新，旧任务正在安全停止。已清除会话密钥；研究记录保留，待停止后继续。")
            if st.button("检查旧任务是否已停止"): st.rerun()
            st.stop()
        st.session_state.workspace = Workspace(previous.directory.parent, owner=previous.directory.name, deployment=previous.deployment)
        st.session_state.pop("pending_review", None)
        st.session_state.pop("upgrade_pause_requested", None)
        notice("应用版本已更新，研究记录已接管；模型密钥需重新填写，待确认窗口需重新打开。")
    if "workspace" not in st.session_state:
        mode = os.environ.get("CRA_DEPLOYMENT", "cloud")
        default_root = Path(tempfile.gettempdir()) / "cra-workspaces" if mode == "cloud" else Path.cwd() / ".cra-workspaces"
        root = Path(os.environ.get("CRA_WORKSPACE_ROOT", str(default_root)))
        owner = None
        if mode == "local":
            import hashlib
            owner = hashlib.sha256((str(root.resolve()) + ":" + str(getattr(os, "getuid", lambda: "local-user")())).encode()).hexdigest()[:32]
        st.session_state.workspace = Workspace(root, owner=owner, deployment=mode)
    w = st.session_state.workspace
    try: w.remote_executor = operator_executor()
    except EngineError:
        w.remote_executor = None
        st.error("独立执行服务配置不完整或地址不符合要求；不会自动改用其他服务器。")
    st.caption("开发预览 · " + ("云端处理" if w.deployment == "cloud" else "本机处理") + " · 尚未完成正式科研发布验收")
    if w.deployment == "cloud":
        from cra_engine.common import digest, sha
        from cra_engine.statistics import recipe_identity
        identity = digest({"recipe": recipe_identity(), "diagnostic": sha(Path(environment.__file__)), "worker": w.remote_executor.endpoint if w.remote_executor else None})
        capability = hosting_environment(identity, w.remote_executor)
        st.session_state.cloud_environment = capability
        if not capability["passed"]:
            st.warning("当前云端仅提供材料与方案工作区：自动统计隔离自检未通过，研究执行已禁用。分析请在已验证的本机环境完成，或配置经验证的独立执行服务器。")
            st.link_button("查看本机运行与恢复说明", "https://github.com/RGaoly/communication-research-agent-app/blob/main/docs/STREAMLIT_WORKSPACE_ZH.md")
        elif w.remote_executor:
            st.info("独立执行服务器隔离自检通过。每个项目仍需在“模型与设置”中允许分析副本传输，并确认当前项目授权后才能运行。")
    with st.sidebar:
        st.markdown('<div class="brand">COMMUNICATION<br>RESEARCH AGENT</div>', unsafe_allow_html=True)
        st.caption("开发预览 · 云端处理" if w.deployment == "cloud" else "开发预览 · 本机处理")
        st.caption("尚未完成独立真人、真实模型盲测和真实项目发布验收。")
        if st.button("＋ 新建 / 恢复研究", width="stretch"):
            st.session_state.project = None
            st.session_state.project_picker = None
            st.session_state.route = PAGES[0]
            st.session_state.pop("pending_review", None)
            st.rerun()
        projects = w.projects()
        if projects:
            ids = [x["project_id"] for x in projects]
            current = st.session_state.get("project")
            options = [None] + ids
            if current not in ids: st.session_state.project = current = None
            st.session_state.project_picker = current
            st.selectbox("当前会话的研究", options, index=None, placeholder="选择研究", key="project_picker", on_change=choose_project,
                         format_func=lambda x: "选择研究" if x is None else next(r["name"] for r in projects if r["project_id"] == x))
        route = st.radio("研究工作区", PAGES, key="route", label_visibility="collapsed")
        st.divider()
        st.caption("材料不会自动发布到GitHub。" + ("云端空间和浏览器会话可能回收，请及时下载私有恢复备份。会话丢失后可重新导入备份。" if w.deployment == "cloud" else "研究保存在本机研究库，重新打开仍可选择；密钥按浏览器会话隔离，需要重新填写。请定期备份。"))
    flash = st.session_state.pop("flash", None)
    if flash and flash[0]: (st.error if flash[1] else st.success)(flash[0])
    p = st.session_state.get("project")
    if not p:
        home(w)
        return
    pages = dict(zip(PAGES, [overview, materials, literature, protocol_page, results, deliver, settings]))

    @st.fragment(run_every="2s")
    def project_content():
        try:
            s = w.snapshot(p)
            pages[route](w, p, s)
        except EngineError as exc:
            st.error(str(exc))
        except Exception:
            st.error("无法读取当前项目状态。请保留恢复备份并检查运行环境；没有回显原始材料。")
    # Don't refresh live forms: polling is enabled only on the overview while an
    # actual background worker exists; all other views rerun on user actions.
    if route == PAGES[0] and w.running(p): project_content()
    else:
        try: pages[route](w, p, w.snapshot(p))
        except EngineError as exc: st.error(str(exc))
    pending = st.session_state.get("pending_review")
    if pending and pending["project"] == p:
        review_dialog(w, p, pending["scope"], pending["challenge"], w.snapshot(p))


if __name__ == "__main__": main()
