"""外脑伙伴 —— Streamlit 网页版

运行：
  pip install streamlit
  streamlit run app.py

功能：自然对话（流式）、画像初始化、跨重启对话历史、侧边栏画像/重置、
联网搜索（需 TAVILY_API_KEY）、读文件/列目录工具。
"""

from __future__ import annotations

import shutil

import streamlit as st

from waibao.agent import PersonalExplorerAgent


st.set_page_config(page_title="外脑伙伴", page_icon="🧠", layout="wide")


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
    st.text(agent.profile.summary())
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
        "联网搜索：在输入框写「搜索 xxx」，需设置 TAVILY_API_KEY。\n"
        "读文件：写「读文件 路径」或「列出文件」。\n"
        "图片理解：需视觉模型（如 OpenAI gpt-4o），当前 DeepSeek-chat 不支持。"
    )


# ---- 主聊天区 --------------------------------------------------------
st.title("外脑伙伴")

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

