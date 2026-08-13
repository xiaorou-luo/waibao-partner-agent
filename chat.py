"""交互模式：直接和 Agent 对话（记忆持久化到 waibao_data/）

运行：python3 chat.py
支持命令：查看画像 / 调整画像 / 查看历史 / 接着做
"""

from __future__ import annotations

from waibao.agent import PersonalExplorerAgent


def main() -> None:
    agent = PersonalExplorerAgent(storage_dir="waibao_data")
    agent.ensure_profile_initialized()
    print("\n可以告诉我你想做什么了（输入 exit 退出；支持 查看画像 / 调整画像 / 查看历史 / 接着做）：")
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

