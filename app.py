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

import streamlit as st

from waibao import tools
from waibao.agent import PersonalExplorerAgent


st.set_page_config(
    page_title="外脑伙伴",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 部署到 Streamlit Cloud 时，从平台 Secrets 读取密钥（本地则用 .env）
try:
    for _key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "TAVILY_API_KEY", "ACCESS_PASSWORD"):
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass


# ---- 商务风样式 --------------------------------------------------------
st.markdown(
    """
<style>
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Segoe UI", sans-serif;
    color: #0f172a;
}
/* 顶部品牌栏 */
.waibao-hero {
    background: linear-gradient(120deg, #0f172a 0%, #1e3a5f 55%, #2563eb 100%);
    color: #ffffff;
    padding: 1.35rem 1.6rem;
    border-radius: 16px;
    margin-bottom: 0.9rem;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
}
.waibao-hero h1 {
    color: #ffffff;
    font-size: 1.65rem;
    margin: 0 0 0.25rem 0;
    letter-spacing: 0.5px;
}
.waibao-hero .sub {
    color: #cbd5e1;
    font-size: 0.92rem;
    margin: 0;
}
.waibao-hero .badges {
    margin-top: 0.75rem;
}
.waibao-badge {
    display: inline-block;
    background: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.22);
    color: #f1f5f9;
    padding: 0.18rem 0.75rem;
    border-radius: 999px;
    font-size: 0.78rem;
    margin-right: 0.5rem;
}
/* 聊天气泡 */
[data-testid="stChatMessage"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 0.5rem 0.7rem;
    margin-bottom: 0.55rem;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}
/* 输入框 */
[data-testid="stChatInput"] {
    border-top: 1px solid #e2e8f0;
}
[data-testid="stChatInput"] textarea {
    border-radius: 12px;
}
/* 按钮 */
.stButton > button {
    border-radius: 10px;
    font-weight: 600;
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


@st.cache_resource
def get_agent() -> PersonalExplorerAgent:
    return PersonalExplorerAgent(storage_dir="waibao_data")


agent = get_agent()


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
        shutil.rmtree(agent.storage_dir, ignore_errors=True)
        st.session_state.clear()
        if _keep_auth:
            st.session_state["_authed"] = True
        st.cache_resource.clear()
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

    with st.expander("🔍 联网搜索", expanded=False):
        _q = st.text_input("搜索关键词", key="web_q", placeholder="例如：2026 音乐产业趋势")
        if st.button("搜索", key="web_go", use_container_width=True):
            if not _q.strip():
                st.warning("请输入关键词")
            else:
                with st.spinner("正在搜索…"):
                    _r = tools.web_search_structured(_q.strip())
                _r["query"] = _q.strip()
                st.session_state["search_result"] = _r

    with st.expander("📁 文件与工具", expanded=False):
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

    with st.expander("🧹 数据管理", expanded=False):
        if st.button("🗑 清空对话记录", key="clear_side", use_container_width=True):
            agent.history = []
            agent._save_history()
            st.session_state.messages = []
            st.rerun()
        if st.button("🔄 重置全部记忆", key="reset_side", use_container_width=True):
            _confirm_reset()

    st.divider()
    st.caption(
        "· 联网：写「搜索 xxx」\n"
        "· 文件：写「读文件 / 搜索文件 / 搜索内容」\n"
        "· 图片理解需视觉模型（如 gpt-4o）"
    )


# ---- 顶部品牌栏 --------------------------------------------------------
_net_on = bool(os.environ.get("TAVILY_API_KEY"))
_model_txt = f"{agent.llm.provider}/{agent.llm.model}" if agent.llm.enabled else "未配置"
_net_badge = "🔍 联网搜索：已开启" if _net_on else "🔍 联网搜索：未配置"
st.markdown(
    f"""
<div class="waibao-hero">
  <h1>🧠 外脑伙伴</h1>
  <p class="sub">你的个性化探索-生成型 AI 助手 · 越用越懂你</p>
  <div class="badges">
    <span class="waibao-badge">🤖 模型：{_model_txt}</span>
    <span class="waibao-badge">{_net_badge}</span>
    <span class="waibao-badge">🧠 画像：已建立</span>
    <span class="waibao-badge">📁 文件与工具</span>
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
    agent.history = []
    agent._save_history()
    st.session_state.messages = []
    st.rerun()
if _reset_top:
    _confirm_reset()


# ---- 搜索结果展示 ------------------------------------------------------
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
    st.divider()


# ---- 主聊天区 ----------------------------------------------------------
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
