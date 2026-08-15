"""LLM 连通性自检脚本

用法：
  export LLM_PROVIDER=deepseek
  export LLM_API_KEY=sk-xxx
  python3 llm_test.py

未配置 Key 也能运行，会提示当前走规则引擎。退出码 0=正常，1=调用失败。
"""

from __future__ import annotations

import sys

from waibao.llm import LLMAdapter


def main() -> int:
    llm = LLMAdapter()
    print(f"provider : {llm.provider}")
    print(f"model    : {llm.model}")
    print(f"endpoint : {llm.base_url}/chat/completions")
    print(f"enabled  : {'是（已配置密钥）' if llm.enabled else '否（未配置，走规则引擎）'}")

    if not llm.enabled:
        print("\n提示：设置 LLM_PROVIDER 和 LLM_API_KEY 环境变量即可启用真实大模型。")
        return 0

    print("\n正在发起一次最小调用测试……")
    try:
        reply = llm.ping()
        print("✅ 连接成功，模型回复：")
        print("   " + reply)
        return 0
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要兜住所有错误
        print("❌ 调用失败：")
        print("   " + str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())

