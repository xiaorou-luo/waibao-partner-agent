"""交互与反馈界面（模块四）

规格 5.1-5.4：按画像语气渲染输出、收集封闭式回答、阶段暂停询问、
断点续传询问、冲突提醒、异常确认、画像查看/调整。
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class ConsoleInterface:
    def __init__(
        self,
        profile_provider: Optional[Callable[[], dict[str, Any]]] = None,
        show_fn: Callable[[str], None] = print,
        input_fn: Callable[[str], str] = input,
    ) -> None:
        self.profile_provider = profile_provider
        self._show_fn = show_fn
        self._input_fn = input_fn

    # ---- 输出（规格 5.1） ---------------------------------------------
    def show(self, text: str) -> None:
        self._show_fn(text)

    def style(self, text: str) -> str:
        """按画像语气给方案正文加前缀（规格 5.1）。"""
        tone = self._tone()
        if tone == "formal":
            return "您好，以下内容供参考：\n\n" + text
        if tone == "casual":
            return "来，给你：\n\n" + text
        return "接下来我们可以这样处理：\n\n" + text

    def _tone(self) -> str:
        if self.profile_provider:
            return self.profile_provider().get("expression", {}).get("output_tone", "neutral")
        return "neutral"

    # ---- 输入 ---------------------------------------------------------
    def ask_raw(self, prompt: str = "> ") -> str:
        return self._input_fn(prompt).strip()

    def ask_initial(self, questions: list[dict[str, Any]]) -> dict[str, str]:
        answers: dict[str, str] = {}
        for q in questions:
            self._show_fn(f"{q['question']}\n选项：{' / '.join(q['options'])}")
            answers[q["id"]] = self._input_fn("> ").strip()
        return answers

    def ask_closed(self, questions: list[dict[str, Any]]) -> dict[str, str]:
        answers: dict[str, str] = {}
        for q in questions:
            self._show_fn(f"{q['question']}\n选项：{' / '.join(q['options'])}")
            answers[q["id"]] = self._input_fn("> ").strip()
        return answers

    def confirm_spec(self, spec_text: str) -> str:
        self._show_fn(spec_text)
        return self._input_fn("> ").strip()

    def collect_feedback(self) -> str:
        return self._input_fn("继续则回复「继续」，暂停回复「先这样」，或直接给评分/修改意见：\n> ").strip()

    def ask_resume(self, message: str) -> str:
        self._show_fn(message)
        return self._input_fn("> ").strip()

    def ask_conflict(self, message: str) -> str:
        self._show_fn(message)
        return self._input_fn("> ").strip()

    def ask_anomaly(self, message: str) -> str:
        self._show_fn(message)
        return self._input_fn("> ").strip()

    def ask_calibration(self, report: str) -> str:
        self._show_fn(report)
        return self._input_fn("> ").strip()
