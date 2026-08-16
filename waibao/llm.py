"""真实 LLM 适配器（OpenAI 兼容接口：支持 OpenAI / DeepSeek 等）

零第三方依赖：用标准库直接调用 POST /chat/completions。
通过环境变量或构造参数配置；未提供 API Key 时自动退回内置规则引擎。

环境变量：
  LLM_PROVIDER    openai | deepseek（默认 deepseek）
  LLM_API_KEY     你的密钥（也可用 OPENAI_API_KEY / DEEPSEEK_API_KEY）
  LLM_BASE_URL    可选，自定义兼容端点
  LLM_MODEL       可选，覆盖默认模型
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "usegoodai": {"base_url": "https://api.usegoodai.com/v1", "model": "claude-3-7-sonnet-20250219"},
}

_INTENT_LABELS = {
    "explore": "探索研究",
    "generate": "生成内容",
    "organize": "整理信息",
    "decide": "决策辅助",
    "custom": "其他",
}


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load_dotenv(path: Optional[str] = None) -> None:
    """从 .env 加载 KEY=VALUE（不覆盖已存在的环境变量）。

    默认依次查找：项目根目录（waibao 包的上一级）、当前目录。
    这样无论用 run.sh、chat.py 还是 streamlit 启动，都能读到密钥。
    """
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.append(Path(__file__).resolve().parent.parent / ".env")
        candidates.append(Path.cwd() / ".env")
    for fp in candidates:
        if fp.exists():
            for line in fp.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
            break


class LLMAdapter:
    """真实 LLM 调用。enabled=True 时走大模型，否则回退规则引擎。"""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        enabled: Optional[bool] = None,
        timeout: int = 120,
    ) -> None:
        self.provider = (provider or _env("LLM_PROVIDER", "deepseek")).lower()
        cfg = PROVIDERS.get(self.provider, PROVIDERS["deepseek"])
        self.base_url = (base_url or _env("LLM_BASE_URL", cfg["base_url"])).rstrip("/")
        self.model = model or _env("LLM_MODEL", cfg["model"])
        self.api_key = (
            api_key
            or _env("LLM_API_KEY")
            or _env("OPENAI_API_KEY")
            or _env("DEEPSEEK_API_KEY")
            or _env("ANTHROPIC_AUTH_TOKEN")
            or _env("ANTHROPIC_API_KEY")
        )
        self.temperature = temperature
        self.timeout = timeout
        self.enabled = bool(self.api_key) if enabled is None else enabled

    # ---- 对外入口 -----------------------------------------------------
    def generate(
        self,
        spec: Any,
        profile: Any,
        stage: str = "full",
        conflict_choice: str = "",
    ) -> str:
        if not self.enabled:
            raise NotImplementedError("未配置 LLM API Key，使用内置规则引擎。")
        messages = self._build_messages(spec, profile, stage, conflict_choice)
        return self._chat(messages)

    def ping(self) -> str:
        """最小连通性自检：发起一次极小的真实调用并返回模型回复。"""
        return self._chat([{"role": "user", "content": "请只回复两个字：正常"}])

    def interpret_choice(self, question: str, answer: str, choices: list[str]) -> str:
        """把用户的自由回答映射到最贴近的候选值（用于画像初始化/澄清）。"""
        if not self.enabled:
            return ""
        prompt = (
            f"问题：{question}\n"
            f"用户回答：{answer}\n"
            f"候选值：{' / '.join(choices)}\n"
            f"请从候选值里选出最贴合用户意思的一项，只回复该候选值的原文，不要任何解释。"
        )
        try:
            return self._chat([{"role": "user", "content": prompt}]).strip()
        except Exception:
            return ""

    @property
    def supports_vision(self) -> bool:
        """是否支持图片输入（目前仅部分 OpenAI 视觉模型；DeepSeek-chat 不支持）。"""
        return self.provider == "openai" and any(
            k in self.model for k in ("gpt-4o", "gpt-4-vision", "gpt-4.1", "gpt-4.5", "o1", "o3")
        )

    # ---- HTTP 调用 ----------------------------------------------------
    def _chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"LLM 调用失败（HTTP {exc.code}）：{detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 LLM 服务：{exc.reason}") from exc
        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"LLM 返回格式异常：{body}") from exc

    def chat(self, messages: list[dict[str, str]]) -> str:
        """非流式完整回复（用于摘要等内部任务）。"""
        if not self.enabled:
            raise NotImplementedError("未配置 LLM API Key。")
        return self._chat(messages)

    def chat_stream(self, messages: list[dict[str, str]]):
        """流式调用：逐段产出文本（ChatGPT 式打字效果）。"""
        if not self.enabled:
            raise NotImplementedError("未配置 LLM API Key。")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": True,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"LLM 调用失败（HTTP {exc.code}）：{detail[:400]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 LLM 服务：{exc.reason}") from exc
        with resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content") or ""
                except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                    continue
                if delta:
                    yield delta

    # ---- Prompt 组装（把画像 + 规格 + 阶段 + 约束注入） ----------------
    def _build_messages(
        self,
        spec: Any,
        profile: Any,
        stage: str,
        conflict_choice: str,
    ) -> list[dict[str, str]]:
        p = profile.snapshot()
        system = (
            "你是一位世界级的 AI 系统架构师与资深领域顾问，正在为一位特定用户生成高度个性化的成果。"
            "你必须严格遵循用户的画像偏好与红线，不得违背。"
            "输出语言：中文为主，专业术语可保留英文；使用 Markdown；"
            "只输出方案正文，不要任何寒暄或解释。"
        )
        user = (
            "【用户画像】\n"
            + self._format_profile(p)
            + "\n\n【当前任务】\n"
            + self._format_spec(spec)
            + "\n\n【本阶段要求】\n"
            + self._stage_instruction(stage)
            + "\n\n【输出约束】\n"
            + self._format_constraints(p, conflict_choice)
            + "\n\n请直接输出内容。"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _format_profile(p: dict[str, Any]) -> str:
        cog, exp, dom, col = p["cognition"], p["expression"], p["domain"], p["collaboration"]
        return (
            f"- 思维认知：宏观优先 {cog['thinking_macro_first']}、需要细节辅助 {cog['detail_assist_needed']}、"
            f"逻辑vs直觉 {cog['logic_over_intuition']}、深度优先 {cog['depth_first']}\n"
            f"- 表达风格：语气 {exp['output_tone']}、结构密度 {exp['structure_density']}、"
            f"举例偏好 {exp['example_preference']}、抽象程度 {exp['abstraction_level']}\n"
            f"- 领域：主{dom['domain_primary']}(深度 {dom['domain_depth_primary']})、"
            f"次{dom['domain_secondary']}(深度 {dom['domain_depth_secondary']})、"
            f"不熟悉领域 {dom['unfamiliar_topics'] or '无'}\n"
            f"- 协作习惯：决策速度 {col['decision_speed']}、追问耐受 {col['followup_tolerance']}、"
            f"初稿后放弃概率 {col['abandon_after_first_draft']}、需要里程碑 {col['need_progress_milestones']}\n"
            f"- 价值观红线：{'、'.join(p['value_red_lines'])}"
        )

    @staticmethod
    def _format_spec(spec: Any) -> str:
        details = "；".join(f"{k}={v}" for k, v in spec.confirmed_details.items()) or "无"
        assumptions = "；".join(spec.assumptions) or "无"
        return (
            f"- 目标：{spec.goal}\n"
            f"- 意图类型：{_INTENT_LABELS.get(spec.intent_type, spec.intent_type)}\n"
            f"- 领域：{spec.domain}\n"
            f"- 已确认信息：{details}\n"
            f"- 输出形式：{spec.output_format}\n"
            f"- 假设：{assumptions}"
        )

    @staticmethod
    def _stage_instruction(stage: str) -> str:
        if stage == "framework":
            return "这是「框架草案」阶段：只输出整体框架（3-6 个部分，每部分一行要点），不要填充细节，保持短小便于用户快速确认。"
        if stage == "full":
            return "这是「内容填充」阶段：在框架基础上逐段展开，给出具体、可执行的内容。"
        return "这是「成品交付」阶段：输出可直接使用的成品，先一句话说明成果，再给结构化摘要（可用表格），简洁。"

    @staticmethod
    def _format_constraints(p: dict[str, Any], conflict_choice: str) -> str:
        rules: list[str] = []
        tone = p["expression"]["output_tone"]
        rules.append({
            "formal": "语气正式、专业。",
            "casual": "语气轻松、自然、口语化。",
            "neutral": "语气中立、带一点鼓励性。",
        }.get(tone, "语气中立、带一点鼓励性。"))
        if p["cognition"]["thinking_macro_first"] > 0.7:
            rules.append("先给整体框架再逐层展开，首屏只显示高层级。")
        if p["expression"]["structure_density"] > 0.7:
            rules.append("大量使用标题、分点、表格。")
        elif p["expression"]["structure_density"] > 0.6:
            rules.append("使用标题和分点。")
        if p["expression"]["abstraction_level"] > 0.7:
            rules.append("多用概念和理论，少用具体案例。")
        if p["expression"]["example_preference"] < 0.5:
            rules.append("不要主动举例，除非用户明确要求。")
        if p["collaboration"]["abandon_after_first_draft"] > 0.6:
            rules.append("用户易在初稿后失去动力：本阶段只给一小段，不要一次性给全部内容。")
        if p["value_red_lines"]:
            rules.append("红线（务必避免）：「" + "」「".join(p["value_red_lines"]) + "」。")
        if conflict_choice == "按画像优化":
            rules.append("当前需求与画像冲突：按画像优化，保持直接、具体、不用套话。")
        elif conflict_choice == "按你的要求":
            rules.append("用户已确认按原要求执行，可忽略套话相关红线。")
        return "\n".join(f"- {r}" for r in rules)
