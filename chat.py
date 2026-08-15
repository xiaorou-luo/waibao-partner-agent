"""交互模式：直接和 Agent 对话（记忆持久化到 waibao_data/）

运行：python3 chat.py
支持命令：查看画像 / 调整画像 / 查看历史 / 接着做
"""

from __future__ import annotations

try:
    import readline  # noqa: F401  # 启用上下键历史与更顺的行内编辑
except ImportError:
    pass

from waibao.agent import PersonalExplorerAgent


def main() -> None:
    agent = PersonalExplorerAgent(storage_dir="waibao_data")
    if agent.llm.enabled:
        print(f"已启用真实 LLM：{agent.llm.provider} / {agent.llm.model}（像聊天一样直接说，它会记住你）")
    else:
        print("未配置 LLM API Key，当前使用内置规则引擎（设置 LLM_API_KEY 环境变量即可启用）")
    agent.ensure_profile_initialized()
    print("\n现在可以像聊天一样跟我说话了（输入 exit 退出；支持 查看画像 / 调整画像 / 查看历史 / 接着做）：")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"exit", "quit", "退出"}:
            break
        if text:
            agent.handle(text)


if __name__ == "__main__":
    main()
