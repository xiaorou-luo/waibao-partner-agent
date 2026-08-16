"""外脑伙伴 —— Streamlit 网页版

运行：
  pip install streamlit
  streamlit run app.py

功能：自然对话（流式）、画像初始化、跨重启对话历史、侧边栏画像/重置、
联网搜索（需 TAVILY_API_KEY）、读文件/列目录工具。
"""

from __future__ import annotations

import os
import shutil

import streamlit as st

from waibao import tools
from waibao.agent import PersonalExplorerAgent


st.set_page_config(page_title="外脑伙伴", page_icon="🧠", layout="wide")

# 部署到 Streamlit Cloud 时，从平台 Secrets 读取密钥（本地则用 .env）
try:
    for _key in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "TAVILY_API_KEY", "ACCESS_PASSWORD"):
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass

# 可选访问密码：公开部署时防止陌生人滥用你的额度
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


# ---- 侧边栏 ----------------------------------------------------------
with st.sidebar:
    st.title("🧠 外脑伙伴")
    st.caption(
        f"LLM：{agent.llm.provider} / {agent.llm.model}"
        if agent.llm.enabled
        else "LLM：未配置（规则引擎）"
    )
    st.subheader("我的画像")
    _p = agent.profile.snapshot()
    _cog, _exp, _dom, _col = _p["cognition"], _p["expression"], _p["domain"], _p["collaboration"]
    st.markdown(f"**主领域**：{_dom['domain_primary']}　**次领域**：{_dom['domain_secondary']}")
    st.markdown(f"**语气**：{_exp['output_tone']}")
    st.caption("宏观优先")
    st.progress(_cog["thinking_macro_first"])
    st.caption("结构化程度")
    st.progress(_exp["structure_density"])
    st.caption("举例偏好")
    st.progress(_exp["example_preference"])
    st.caption("红线：" + "、".join(_p["value_red_lines"]))
    st.divider()
    st.subheader("🔍 联网搜索")
    _q = st.text_input("搜索关键词", key="web_q", placeholder="例如：2026 音乐产业趋势")
    if st.button("搜索", key="web_go", use_container_width=True):
        if not _q.strip():
            st.warning("请输入关键词")
        else:
            with st.spinner("正在搜索…"):
                _r = tools.web_search_structured(_q.strip())
            _r["query"] = _q.strip()
            st.session_state["search_result"] = _r
    st.divider()
    if st.button("清空对话记录"):
        agent.history = []
        agent._save_history()
        st.session_state.pop("messages", None)
        st.rerun()
    if st.button("重置全部记忆", type="secondary"):
        shutil.rmtree(agent.storage_dir, ignore_errors=True)
        st.cache_resource.clear()
        st.rerun()
    st.caption(
        "联网搜索：用上面的搜索框，或直接在聊天里写「搜索 xxx」。\n"
        "读文件：写「读文件 路径」或「列出文件」。\n"
        "图片理解：需视觉模型（如 OpenAI gpt-4o），当前 DeepSeek-chat 不支持。"
    )


# ---- 主聊天区 --------------------------------------------------------
st.title("外脑伙伴")

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

if "messages" not in st.session_state:
    st.session_state.messages = list(agent.history)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if agent.llm.supports_vision:
    st.file_uploader("上传图片（视觉模型）", type=["png", "jpg", "jpeg"], key="upload_img")
else:
    st.caption("💡 提示：当前模型不支持图片，切换到 OpenAI 视觉模型后即可上传。")

prompt = st.chat_input("跟外脑伙伴说点什么…（可写：搜索 xxx / 读文件 路径 / 列出文件）")

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
