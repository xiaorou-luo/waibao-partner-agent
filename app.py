"""外脑伙伴 —— Streamlit 网页版（商务风界面）

运行：
  pip install streamlit
  streamlit run app.py

功能：自然对话（流式）、画像初始化、跨重启对话历史、联网搜索、读文件/列目录、
商务风格界面、一键清空对话、重置记忆（二次确认）。
"""

from __future__ import annotations

import os
import shutil
import uuid

import streamlit as st

from waibao import db, tools
from waibao.agent import PersonalExplorerAgent
from waibao.llm import load_dotenv


_FIELD_CN = {
    "cognition.thinking_macro_first": "宏观优先",
    "cognition.detail_assist_needed": "需要细节",
    "cognition.logic_over_intuition": "逻辑vs直觉",
    "cognition.depth_first": "深度优先",
    "expression.structure_density": "结构化程度",
    "expression.example_preference": "举例偏好",
    "expression.abstraction_level": "抽象程度",
    "expression.output_tone": "语气",
    "domain.domain_depth_primary": "主领域深度",
    "domain.domain_depth_secondary": "次领域深度",
    "collaboration.decision_speed": "决策速度",
    "collaboration.followup_tolerance": "追问耐受",
    "collaboration.abandon_after_first_draft": "初稿后放弃",
    "value_red_lines": "红线",
}


st.set_page_config(
    page_title="外脑伙伴",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 部署到 Streamlit Cloud 时，从平台 Secrets 读取密钥（本地则用 .env）
try:
    for _key in (
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "LLM_MODEL",
        "TAVILY_API_KEY",
        "ACCESS_PASSWORD",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
    ):
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass

# 本地读取 .env（云端 Secrets 已通过上面的 st.secrets 注入，优先级更高）
load_dotenv()


# ---- 商务风样式 --------------------------------------------------------
st.markdown(
    """
<style>
.stApp {
    background: #ffffff;
}
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Segoe UI", sans-serif;
    color: #262730;
}
/* 顶部标题栏：极简，无重色 */
.waibao-hero {
    background: transparent;
    padding: 0.3rem 0.2rem 0.65rem 0.2rem;
    border-radius: 0;
    margin-bottom: 0.35rem;
    box-shadow: none;
    border-bottom: 1px solid #f0f0f2;
}
.waibao-hero h1 {
    color: #262730;
    font-size: 1.28rem;
    margin: 0;
    letter-spacing: 0;
}
.waibao-hero .sub {
    color: #9a9fa8;
    font-size: 0.82rem;
    font-weight: 400;
    margin-left: 0.5rem;
}
.waibao-hero .badges {
    margin-top: 0.4rem;
}
.waibao-badge {
    display: inline-block;
    background: #f3f4f6;
    border: 1px solid #e9eaee;
    color: #6b7280;
    padding: 0.12rem 0.6rem;
    border-radius: 999px;
    font-size: 0.7rem;
    margin-right: 0.35rem;
}
/* 聊天气泡：极简，去边框阴影 */
[data-testid="stChatMessage"] {
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0.35rem 0.05rem;
    margin-bottom: 0.3rem;
    box-shadow: none;
}
/* 输入框 */
[data-testid="stChatInput"] {
    border-top: 1px solid #f0f0f2;
}
[data-testid="stChatInput"] textarea {
    border-radius: 8px;
}
/* 按钮：柔和圆角 */
.stButton > button {
    border-radius: 8px;
    font-weight: 500;
}
</style>
""",
    unsafe_allow_html=True,
)


# ---- 可选访问密码 ------------------------------------------------------
_pwd = os.environ.get("ACCESS_PASSWORD", "")
if _pwd and not st.session_state.get("_authed"):
    st.title("🔒 外脑伙伴")
    st.markdown("这是一个受保护的演示，请输入访问密码。")
    _inp = st.text_input("访问密码", type="password")
    if st.button("进入", type="primary"):
        if _inp == _pwd:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("密码不对")
    st.stop()


# ---- 账号登录 / 注册（配置了 Supabase 时启用） ------------------------
_auth_enabled = db.configured()
if _auth_enabled and not st.session_state.get("auth_user"):
    # 密码重置邮件里的链接会带 type=recovery&access_token=...
    if st.query_params.get("type") == "recovery" and st.query_params.get("access_token"):
        st.title("🔐 设置新密码")
        st.markdown("输入你的新密码（至少 6 位）。")
        _np = st.text_input("新密码", type="password", key="new_pwd")
        _np2 = st.text_input("再次输入新密码", type="password", key="new_pwd2")
        if st.button("保存新密码", type="primary", use_container_width=True):
            if len(_np) < 6 or _np != _np2:
                st.warning("密码至少 6 位，且两次输入要一致")
            else:
                _r = db.update_password(st.query_params["access_token"], _np)
                if _r.get("ok"):
                    st.success("密码已更新，请返回登录页重新登录。")
                    st.query_params.clear()
                else:
                    st.error(_r.get("error", "更新失败，可能链接已过期，请重新发送重置邮件。"))
        st.stop()

    st.title("🧠 外脑伙伴")
    st.markdown("登录后，你的画像、记忆和聊天历史会跨设备保存在云端。")
    _tab_login, _tab_signup = st.tabs(["登录", "注册"])
    with _tab_login:
        _email = st.text_input("邮箱", key="login_email")
        _pwd = st.text_input("密码", type="password", key="login_pwd")
        if st.button("登录", type="primary", use_container_width=True):
            if not _email or not _pwd:
                st.warning("请输入邮箱和密码")
            else:
                _res = db.sign_in(_email, _pwd)
                if _res.get("ok"):
                    st.session_state["auth_user"] = {
                        "id": _res["user_id"],
                        "email": _email.strip(),
                        "access_token": _res["access_token"],
                    }
                    st.session_state.pop("_data_loaded", None)
                    st.rerun()
                else:
                    st.error(_res.get("error", "登录失败"))
        with st.expander("忘记密码？"):
            _reset_email = st.text_input("注册邮箱", key="reset_email")
            if st.button("发送重置邮件", use_container_width=True):
                if not _reset_email:
                    st.warning("请输入注册邮箱")
                else:
                    _r = db.reset_password(_reset_email)
                    if _r.get("ok"):
                        st.success("重置邮件已发送，请查收（可能延迟几分钟，也请看看垃圾箱）。")
                    else:
                        st.error(_r.get("error", "发送失败"))
    with _tab_signup:
        _email2 = st.text_input("邮箱", key="signup_email")
        _pwd2 = st.text_input("密码（至少 6 位）", type="password", key="signup_pwd")
        if st.button("注册并登录", type="primary", use_container_width=True):
            if not _email2 or len(_pwd2) < 6:
                st.warning("请输入邮箱，密码至少 6 位")
            else:
                _res = db.sign_up(_email2, _pwd2)
                if _res.get("ok"):
                    if _res.get("access_token"):
                        st.session_state["auth_user"] = {
                            "id": _res["user_id"],
                            "email": _email2.strip(),
                            "access_token": _res["access_token"],
                        }
                        st.session_state.pop("_data_loaded", None)
                        st.rerun()
                    else:
                        st.info("注册成功，请先到邮箱点击确认链接，再回来登录。")
                else:
                    st.error(_res.get("error", "注册失败"))
    st.stop()


def _is_cloud_deployment() -> bool:
    """判断是否运行在 Streamlit Cloud（云端多人访问需要会话隔离）。"""
    return os.path.exists("/mount/src")


def _get_agent() -> PersonalExplorerAgent:
    """按场景选择存储目录：

    - 云端（公开链接）：每个浏览器会话一个独立目录，互不看到彼此的聊天记录。
    - 本机：固定目录，保留你的画像和跨重启对话历史。
    """
    if _is_cloud_deployment():
        if "session_id" not in st.session_state:
            st.session_state["session_id"] = uuid.uuid4().hex[:12]
        storage_dir = f"waibao_data/{st.session_state['session_id']}"
    else:
        storage_dir = "waibao_data"
    return PersonalExplorerAgent(storage_dir=storage_dir)


if _auth_enabled:
    _user = st.session_state["auth_user"]
    _user_id = _user["id"]
    _token = _user["access_token"]
    _storage_dir = f"waibao_data/users/{_user_id}"
    if not st.session_state.get("_data_loaded"):
        try:
            db.download_user_data(_user_id, _token, _storage_dir)
        except Exception:
            pass
        st.session_state["_data_loaded"] = True
    agent = PersonalExplorerAgent(storage_dir=_storage_dir)
else:
    agent = _get_agent()
    _user_id = ""
    _token = ""
    _storage_dir = ""


# ---- 首次画像初始化 ---------------------------------------------------
if not agent.ltm.profile_initialized():
    st.title("🧠 欢迎使用外脑伙伴")
    st.markdown("先花 30 秒让我认识你，之后我会越用越懂你。")
    answers: dict[str, str] = {}
    for q in agent.profile.init_questions():
        answers[q["id"]] = st.radio(q["question"], q["options"], key=q["id"])
    if st.button("开始", type="primary"):
        agent.profile.apply_initial_answers(answers, llm=agent.llm)
        agent.evolution.save_profile(agent.profile, mark_initialized=True)
        if _auth_enabled:
            try:
                db.upload_user_data(_user_id, _token, _storage_dir)
            except Exception:
                pass
        st.rerun()
    st.stop()


# ---- 重置确认对话框 ----------------------------------------------------
@st.dialog("确认重置全部记忆？")
def _confirm_reset() -> None:
    st.warning("这会删除画像、长期记忆、情景记忆和全部对话，且无法恢复。")
    c1, c2 = st.columns(2)
    if c1.button("取消", use_container_width=True):
        st.rerun()
    if c2.button("确认重置", type="primary", use_container_width=True):
        _keep_auth = st.session_state.get("_authed", False)
        _keep_user = st.session_state.get("auth_user")
        shutil.rmtree(agent.storage_dir, ignore_errors=True)
        if _auth_enabled and _keep_user:
            try:
                db.clear_user_data(_keep_user["id"], _keep_user["access_token"])
            except Exception:
                pass
        st.session_state.clear()
        if _keep_auth:
            st.session_state["_authed"] = True
        if _keep_user:
            st.session_state["auth_user"] = _keep_user
            st.session_state.pop("_data_loaded", None)
        st.rerun()


# ---- 侧边栏 ----------------------------------------------------------
with st.sidebar:
    st.title("🧠 外脑伙伴")
    st.caption(
        f"LLM：{agent.llm.provider} / {agent.llm.model}"
        if agent.llm.enabled
        else "LLM：未配置（规则引擎）"
    )

    with st.expander("👤 我的画像", expanded=True):
        _p = agent.profile.snapshot()
        _cog, _exp, _dom, _col = (
            _p["cognition"],
            _p["expression"],
            _p["domain"],
            _p["collaboration"],
        )
        st.markdown(f"**主领域**：{_dom['domain_primary']}")
        st.markdown(f"**次领域**：{_dom['domain_secondary']}")
        st.markdown(f"**语气**：{_exp['output_tone']}")
        st.caption("宏观优先")
        st.progress(_cog["thinking_macro_first"])
        st.caption("结构化程度")
        st.progress(_exp["structure_density"])
        st.caption("举例偏好")
        st.progress(_exp["example_preference"])
        st.markdown("**红线**：" + "、".join(_p["value_red_lines"]))
        st.divider()
        st.caption("关于你 · 个人画像（对话构建）")
        _portrait_enabled = getattr(agent.profile, "portrait_enabled", True)
        _portrait_text = getattr(agent.profile, "portrait", "")
        _pt = st.toggle("启用个人画像", value=_portrait_enabled, key="portrait_enabled")
        if _pt != _portrait_enabled and hasattr(agent.profile, "portrait_enabled"):
            agent.profile.portrait_enabled = _pt
            if hasattr(agent, "_save_portrait"):
                agent._save_portrait()
            st.rerun()
        _new_pt = st.text_area(
            "画像内容（可直接修改）",
            value=_portrait_text,
            key="portrait_text",
            height=160,
            placeholder="聊几句之后，这里会慢慢长出只属于你的画像…",
        )
        if _new_pt != _portrait_text and hasattr(agent.profile, "set_portrait"):
            agent.profile.set_portrait(_new_pt)
            if hasattr(agent, "_save_portrait"):
                agent._save_portrait()

    st.divider()
    _sb1, _sb2 = st.columns(2)
    if _sb1.button("🗑 清空对话", key="clear_side", use_container_width=True):
        agent.archive_current_session()
        agent.history = []
        agent._save_history()
        st.session_state.messages = []
        if _auth_enabled:
            try:
                db.upload_user_data(_user_id, _token, _storage_dir)
            except Exception:
                pass
        st.rerun()
    if _sb2.button("🔄 重置", key="reset_side", use_container_width=True):
        _confirm_reset()

    if _auth_enabled:
        st.caption("👤 " + st.session_state["auth_user"].get("email", ""))
        if st.button("🚪 退出登录", use_container_width=True):
            st.session_state.pop("auth_user", None)
            st.session_state.pop("_data_loaded", None)
            st.rerun()

    st.caption(
        "· 联网、文件、历史、学习见右侧页签\n"
        "· 支持中/英/日/韩/西/法等语言"
    )


# ---- 顶部品牌栏 --------------------------------------------------------
_net_on = bool(os.environ.get("TAVILY_API_KEY"))
_model_txt = f"{agent.llm.provider}/{agent.llm.model}" if agent.llm.enabled else "未配置"
_net_badge = "🔍 联网搜索：已开启" if _net_on else "🔍 联网搜索：未配置"
_account_badge = "🔐 账号已登录" if _auth_enabled else "🌐 访客模式"
st.markdown(
    f"""
<div class="waibao-hero">
  <h1>🧠 外脑伙伴 <span class="sub">越用越懂你</span></h1>
  <div class="badges">
    <span class="waibao-badge">🤖 {_model_txt}</span>
    <span class="waibao-badge">{_net_badge}</span>
    <span class="waibao-badge">{_account_badge}</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ---- 主操作栏（清空对话放在最显眼位置） -------------------------------
_top1, _top2, _top3 = st.columns([1.4, 1.4, 3.2])
with _top1:
    _clear_top = st.button("🗑 清空对话", key="clear_top", use_container_width=True, type="primary")
with _top2:
    _reset_top = st.button("🔄 重置全部", key="reset_top", use_container_width=True)
if _clear_top:
    agent.archive_current_session()
    agent.history = []
    agent._save_history()
    st.session_state.messages = []
    if _auth_enabled:
        try:
            db.upload_user_data(_user_id, _token, _storage_dir)
        except Exception:
            pass
    st.rerun()
if _reset_top:
    _confirm_reset()


# ---- 功能区页签 --------------------------------------------------------
_tab_search, _tab_history, _tab_learn, _tab_tools = st.tabs(
    ["🔍 联网搜索", "📜 历史对话", "📚 学习记录", "📁 文件工具"]
)

with _tab_search:
    _q = st.text_input("搜索关键词", key="web_q", placeholder="例如：2026 音乐产业趋势")
    if st.button("搜索", key="web_go", use_container_width=True):
        if not _q.strip():
            st.warning("请输入关键词")
        else:
            with st.spinner("正在搜索…"):
                _r = tools.web_search_structured(_q.strip())
            _r["query"] = _q.strip()
            st.session_state["search_result"] = _r
    if st.session_state.get("search_result"):
        _r = st.session_state["search_result"]
        st.subheader(f"🔍 搜索结果：{_r.get('query', '')}")
        if not _r.get("ok"):
            st.info(_r.get("message", "未配置联网搜索。"))
        else:
            if _r.get("answer"):
                st.markdown("**摘要**")
                st.markdown(_r["answer"])
            if _r.get("results"):
                st.markdown("**来源**")
                for _it in _r["results"]:
                    st.markdown(f"- [{_it['title']}]({_it['url']})")
                    if _it.get("content"):
                        st.caption(_it["content"][:200])
            else:
                st.info("没有搜到结果")

with _tab_history:
    _sessions = agent.list_sessions()
    if not _sessions:
        st.info("还没有归档的对话。点「清空对话」会把当前对话自动保存到这里。")
    else:
        _rev = list(reversed(_sessions))
        _labels = [f"{s.get('title', '未命名')}" for s in _rev]
        _pick = st.selectbox("选择一段对话", _labels, key="hist_pick")
        for _s in _rev:
            if _s.get("title", "未命名") == _pick:
                st.caption(f"{_s.get('created_at', '')} · {_s.get('message_count', 0)} 条消息")
                st.markdown("**总结**\n" + _s.get("summary", ""))
                with st.expander("查看完整对话"):
                    for _m in _s.get("messages", []):
                        _role = "你" if _m.get("role") == "user" else "外脑伙伴"
                        st.markdown(f"**{_role}**：{_m.get('content', '')}")
                break

with _tab_learn:
    _log = agent.profile.update_log
    if not _log:
        st.info("还没有学习记录。聊几句之后，这里会显示它从你的对话中学到了什么。")
    else:
        _rows = []
        for _r in reversed(_log[-50:]):
            _f = _r.get("field", "")
            _name = _FIELD_CN.get(_f, _f)
            _b, _a = _r.get("before"), _r.get("after")
            if isinstance(_b, (int, float)) and isinstance(_a, (int, float)):
                _d = round(_a - _b, 2)
                _change = ("+" if _d > 0 else "") + str(_d)
            else:
                _change = f"{_b} → {_a}"
            _rows.append({
                "时间": (_r.get("ts", "")[:16]).replace("T", " "),
                "画像": _name,
                "变化": _change,
                "原因": str(_r.get("reason", ""))[:40],
            })
        st.dataframe(_rows, use_container_width=True, hide_index=True)
        st.caption("这是它从你的对话中自动观察并记录的画像变化。")

with _tab_tools:
    st.caption("允许访问的范围")
    _root_fn = getattr(tools, "allowed_root_description", None)
    st.code(_root_fn() if _root_fn else "（项目目录）", language=None)
    st.markdown(
        "**直接发在聊天里即可**\n\n"
        "· `搜索文件 关键词` —— 按文件名找\n"
        "· `搜索内容 关键词` —— 按内容找\n"
        "· `读文件 路径` —— 读取内容\n"
        "· `列出文件` —— 看当前目录\n"
        "· `搜索 xxx` —— 联网搜索\n"
        "· `运行 xxx` —— 执行命令（本机需开启）"
    )


st.divider()


# ---- 主聊天区（输入框固定底部） --------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = list(agent.history)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if agent.llm.supports_vision:
    st.file_uploader("上传图片（视觉模型）", type=["png", "jpg", "jpeg"], key="upload_img")
else:
    st.caption("💡 当前模型不支持图片，切换到 OpenAI 视觉模型后即可上传。")

prompt = st.chat_input("跟外脑伙伴说点什么…（可写：搜索 xxx / 搜索文件 / 读文件 / 运行命令）")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        placeholder = st.empty()
        parts: list[str] = []
        for delta in agent.converse_stream(prompt):
            parts.append(delta)
            placeholder.markdown("".join(parts))
        reply = "".join(parts).strip()
    st.session_state.messages.append({"role": "assistant", "content": reply})
    if _auth_enabled:
        try:
            db.upload_user_data(_user_id, _token, _storage_dir)
        except Exception:
            st.toast("云端保存失败，请稍后再试。")
