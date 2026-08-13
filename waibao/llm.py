"""可选 LLM 适配器（stub）

最小原型默认零依赖、规则引擎驱动，保证开箱可运行。
接入 LangChain / OpenAI 时，实现 generate() 并用 prompt 模板替换
SolutionGenerator 的规则渲染即可（README 有步骤）。
"""

from __future__ import annotations

from typing import Any, Optional


class LangChainAdapter:
    """LangChain 接入点。enabled=False 时 Agent 使用内置规则引擎。"""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        enabled: bool = False,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.enabled = enabled

    def generate(self, spec: Any, profile: Any, stage: str) -> str:
        """用 LangChain 生成方案。默认抛错，回退规则引擎。"""
        raise NotImplementedError(
            "LangChain 适配器尚未配置。请先安装依赖并实现 prompt 模板，"
            "或保持 enabled=False 使用内置规则引擎。"
        )

