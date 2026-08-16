"""外脑伙伴 Agent 主控编排

数据流（规格一）：用户输入 → 任务-框架生成引擎 →（画像 + 记忆上下文）
→ 提问/方案 → 交互界面 → 反馈 → 记忆与进化系统。

规格 4.4：四阶段切分（需求澄清/框架草案/内容填充/成品交付），
阶段结束暂停询问；放弃点记录；断点续传；动力保鲜。
规格 5.2：每次方案后收集 1-5 分评分反馈。
规格 5.3：查看画像 / 调整画像命令。
规格 5.4：模糊输入、连续拒绝、冲突提醒、历史任务查看。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import tools
from .interaction import ConsoleInterface
from .llm import LLMAdapter, load_dotenv
from .memory import EpisodicMemory, LongTermMemory, MemoryEvolutionSystem, WorkingMemory
from .profile import ProfileSystem
from .task_engine import INTENT_LABELS, TaskFrameworkEngine, TaskSpec


STAGE_LABELS = ("需求澄清", "框架草案", "内容填充", "成品交付")
STAGE_PLAN = (("框架草案", "framework"), ("内容填充", "full"), ("成品交付", "final"))
QUICK_ACCEPT = {"好", "行", "可以", "不错", "ok", "OK", "Ok"}
CONFIRM_WORDS = {"对", "是", "确认", "嗯", "对呀"}
QUICK_ACCEPT_FIELDS = [
    ("cognition", "thinking_macro_first"),
    ("cognition", "detail_assist_needed"),
    ("expression", "structure_density"),
    ("expression", "abstraction_level"),
    ("expression", "example_preference"),
    ("collaboration", "abandon_after_first_draft"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PersonalExplorerAgent:
    def __init__(
        self,
        storage_dir: str = "waibao_data",
        interface: ConsoleInterface | None = None,
        llm: LLMAdapter | None = None,
    ) -> None:
        load_dotenv()  # 无论从哪启动，都自动读取项目里的 .env
        self.storage_dir = Path(storage_dir)
        self.llm = llm or LLMAdapter()
        self.interface = interface or ConsoleInterface()

        self.profile = ProfileSystem()
        self.ltm = LongTermMemory(self.storage_dir)
        self.wm = WorkingMemory()
        self.episodic = EpisodicMemory(self.storage_dir)
        self.evolution = MemoryEvolutionSystem(self.ltm, self.episodic, self.storage_dir)
        self.resume_offered_for: str | None = None
        self.history: list[dict[str, str]] = []
        self.history_file = self.storage_dir / "conversation_history.json"
        self.summary: str = ""
        self.summary_file = self.storage_dir / "conversation_summary.txt"

        self._load_persistent_state()
        self.interface.profile_provider = lambda: self.profile.profile
        self.engine = TaskFrameworkEngine(
            profile=self.profile,
            episodic=self.episodic,
            interface=self.interface,
            llm=self.llm,
        )

    # ---- 持久化 -------------------------------------------------------
    def _load_persistent_state(self) -> None:
        self.ltm.load()
        if self.ltm.get_field("cognition.thinking_macro_first"):
            self.profile.from_flat(self.ltm.all_fields())
            # 规格 4.3：时间衰减（>30 天未更新的字段回退 10%）
            if self.profile.apply_time_decay():
                self.evolution.save_profile(self.profile)
        self.episodic.load()
        # 恢复跨重启的对话历史
        if self.history_file.exists():
            try:
                self.history = json.loads(self.history_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.history = []
        if self.summary_file.exists():
            self.summary = self.summary_file.read_text(encoding="utf-8").strip()

    # ---- 命令入口（规格 5.3 / 5.4） ------------------------------------
    def handle(self, text: str) -> None:
        t = text.strip()
        if t == "查看画像":
            self.interface.show(self.profile.summary())
        elif t == "查看历史":
            self._show_history()
        elif t == "调整画像":
            self._adjust_profile()
        elif t == "接着做":
            unfinished = self.episodic.find_unfinished()
            if unfinished:
                self._resume_last_task(unfinished)
            else:
                self.interface.show("没有找到暂停中的任务。")
        else:
            if self.llm.enabled:
                self.converse(t)
            else:
                self.start_new_task(t)

    # ---- 自然对话模式（ChatGPT 式） ------------------------------------
    def converse(self, text: str) -> str:
        """像 ChatGPT 一样多轮自然对话：带画像、带历史、流式回复，并默默学习。"""
        # 1) 从这句话里学习（显式 + 隐式信号，静默）
        self._learn(text)

        # 2) 组装上下文：系统人设 + 画像 + 最近对话
        messages = self._prepare_messages(text)

        # 3) 流式回复
        parts: list[str] = []
        try:
            for delta in self.llm.chat_stream(messages):
                self.interface.stream(delta)
                parts.append(delta)
        except Exception as exc:  # noqa: BLE001
            self.interface.stream(f"\n（生成出错：{exc}）")
        self.interface.stream("\n")
        reply = "".join(parts).strip()

        # 4) 记住本轮 + 持久化
        self._commit_history(text, reply)
        return reply

    def converse_stream(self, text: str):
        """网页版用：逐段产出回复（生成器），同时更新历史与画像。"""
        self._learn(text)
        if not self.llm.enabled:
            yield "（未配置 LLM API Key，请先设置再试。）"
            return
        messages = self._prepare_messages(text)
        parts: list[str] = []
        try:
            for delta in self.llm.chat_stream(messages):
                parts.append(delta)
                yield delta
        except Exception as exc:  # noqa: BLE001
            yield f"\n（生成出错：{exc}）"
        self._commit_history(text, "".join(parts).strip())

    def _prepare_messages(self, text: str) -> list[dict[str, str]]:
        """组装发给 LLM 的消息：系统人设 + 画像 + 最近对话 +（可选）工具结果。"""
        tool_note = self._run_tools(text)
        user_content = (tool_note + "\n\n用户原始消息：" + text) if tool_note else text
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()}
        ]
        if self.summary:
            messages.append({"role": "system", "content": "以下是更早对话的要点摘要（已压缩，供你衔接上下文）：\n" + self.summary})
        memory = self._retrieve_memory(text)
        if memory:
            messages.append({"role": "system", "content": memory})
        messages.extend(self.history[-24:])
        messages.append({"role": "user", "content": user_content})
        return messages

    def _learn(self, text: str) -> None:
        """静默学习：显式信号 + 隐式信号（快速确认 / 重复提问）。"""
        self.profile.apply_explicit_rules(text)
        t = text.strip()
        if t in QUICK_ACCEPT:
            self.profile.apply_implicit("quick_acceptance", fields=QUICK_ACCEPT_FIELDS)
        elif any(w in text for w in ("又", "还是", "重复", "上次")):
            self.profile.apply_implicit("repeated_question", note=text[:40])

    def _retrieve_memory(self, text: str) -> str:
        """检索与当前话题相关的历史情景记忆，注入上下文。"""
        intent = self.engine.parse(text)
        hits = self.episodic.retrieve_similar(
            goal=text,
            intent=intent.intent_type,
            domain=intent.domain_hint,
            top_k=3,
        )
        lines: list[str] = []
        for ep, score in hits:
            if score < 0.03:
                continue
            lines.append(
                f"- 之前做过：{ep.get('task_goal','')[:60]}"
                f"（领域 {ep.get('domain','')}，意图 {ep.get('intent_type','')}，状态 {ep.get('status','')}）"
            )
        if not lines:
            return ""
        return (
            "以下是你和这位用户相关的历史记忆，回答时可自然参考、不要生硬复述：\n"
            + "\n".join(lines)
        )

    def _run_tools(self, text: str) -> str:
        """识别「搜索 / 读文件 / 列目录」请求并执行，返回工具结果（无则空串）。"""
        m = re.search(r"(?:^|\s)(?:/搜|/search|搜索|搜一下|帮我搜|查一下)\s*(.+)", text)
        if m:
            return "[联网搜索结果]\n" + tools.web_search(m.group(1).strip())
        m = re.search(r"(?:^|\s)(?:/读|读文件|打开文件)\s*(.+)", text)
        if m:
            return "[文件内容]\n" + tools.read_file(m.group(1).strip())
        m = re.search(r"(?:^|\s)(?:/列|列出文件|看看目录)\s*(.*)", text)
        if m:
            return "[目录列表]\n" + tools.list_dir(m.group(1).strip() or ".")
        return ""

    def _commit_history(self, user_text: str, reply: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        if reply:
            self.history.append({"role": "assistant", "content": reply})
        self._remember_turn(user_text, reply)
        self._maybe_summarize()
        self._save_history()
        self.evolution.save_profile(self.profile)

    def _maybe_summarize(self) -> None:
        """历史过长时，把更早的对话压缩成摘要，避免丢上下文。"""
        if len(self.history) <= 40:
            return
        old = self.history[:-40]
        self.history = self.history[-40:]
        new_summary = self._summarize(old)
        if new_summary:
            self.summary = new_summary
            self._save_summary()

    def _summarize(self, messages: list[dict[str, str]]) -> str:
        if not self.llm.enabled:
            return "；".join(m.get("content", "")[:40] for m in messages[:3])
        convo = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}：{m['content'][:200]}" for m in messages
        )
        try:
            return self.llm.chat([
                {
                    "role": "system",
                    "content": "你是对话摘要器。把下面的历史对话压缩成 3-5 条要点，"
                               "保留用户偏好、已讨论的主题、未完成事项。只输出要点。",
                },
                {"role": "user", "content": convo},
            ]).strip()
        except Exception:
            return ""

    def _save_summary(self) -> None:
        if self.summary:
            self.summary_file.parent.mkdir(parents=True, exist_ok=True)
            self.summary_file.write_text(self.summary, encoding="utf-8")

    def _remember_turn(self, text: str, reply: str) -> None:
        """把有价值的对话轮次记入情景记忆，供以后检索（过滤掉「好/继续」等噪音）。"""
        if len(text.strip()) < 8:
            return
        intent = self.engine.parse(text)
        self.episodic.add({
            "task_id": uuid4().hex[:8],
            "task_goal": text[:120],
            "intent_type": intent.intent_type,
            "domain": intent.domain_hint or self.profile.get("domain", "domain_primary"),
            "start_time": _now(),
            "end_time": _now(),
            "status": "completed",
            "abandon_point": None,
            "interaction_log": [text, reply[:400]],
            "user_feedback": [],
            "used_framework": None,
            "user_satisfaction": None,
            "confirmed_details": {},
            "full_delivered": False,
            "kind": "chat",
        })
        self.episodic.trim(200)

    def _save_history(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_file.write_text(
            json.dumps(self.history[-200:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _system_prompt(self) -> str:
        p = self.profile.snapshot()
        cog, exp, dom, col = p["cognition"], p["expression"], p["domain"], p["collaboration"]
        return (
            "你是「外脑伙伴」，用户的私人 AI 伙伴，像一个既懂 ta 又专业的朋友。"
            "你善于理解 ta 没说透的需求，主动补全、温和追问，但绝不啰嗦、不说教、不堆套话。"
            "\n\n你对这位用户的了解（画像，随对话持续更新）：\n"
            f"- 思维认知：宏观优先 {cog['thinking_macro_first']}、需要细节辅助 {cog['detail_assist_needed']}、"
            f"逻辑vs直觉 {cog['logic_over_intuition']}、深度优先 {cog['depth_first']}\n"
            f"- 表达风格：语气 {exp['output_tone']}、结构密度 {exp['structure_density']}、"
            f"举例偏好 {exp['example_preference']}、抽象程度 {exp['abstraction_level']}\n"
            f"- 领域：主{dom['domain_primary']}（深度 {dom['domain_depth_primary']}）、"
            f"次{dom['domain_secondary']}（深度 {dom['domain_depth_secondary']}）\n"
            f"- 协作习惯：决策速度 {col['decision_speed']}、追问耐受 {col['followup_tolerance']}、"
            f"初稿后放弃概率 {col['abandon_after_first_draft']}\n"
            f"- 红线（务必避免）：{'、'.join(p['value_red_lines'])}"
            "\n\n回答规则：中文为主；用户偏好宏观就先给框架；需要细节就展开；"
            "如果用户想要完整方案但容易半途而废，就分小段给、每段问一下要不要继续。"
            "遇到模糊需求，只补一个最关键的缺口，不要一次性问一堆。"
        )

    # ---- 画像初始化（规格 2.2） ----------------------------------------
    def ensure_profile_initialized(self) -> bool:
        if self.ltm.profile_initialized():
            return False
        answers = self.interface.ask_initial(self.profile.init_questions())
        self.profile.apply_initial_answers(answers, llm=self.llm)
        self.evolution.save_profile(self.profile, mark_initialized=True)
        self.interface.show("画像初始化完成，说说你想做什么吧。")
        return True

    # ---- 新任务主流程（规格 4.4 阶段切分） ------------------------------
    def start_new_task(self, raw_input: str) -> str:
        unfinished = self.episodic.find_unfinished()
        if unfinished and self.resume_offered_for != unfinished.get("task_id"):
            self.resume_offered_for = unfinished.get("task_id")
            reply = self.interface.ask_resume(self._resume_message(unfinished))
            if reply == "接着做":
                self._resume_last_task(unfinished)
                return "resumed"
            # 用户选择开启新任务 → 旧任务标记为 abandoned（规格 4.4）
            self._archive_abandoned(unfinished, "用户选择开启新任务")

        intent = self.engine.parse(raw_input)
        task_id = uuid4().hex[:8]
        self.wm.start(task_id, intent)
        self.wm.data["start_time"] = _now()

        # 需求澄清 + 规格确认（阶段一）
        spec = self.engine.run_confirmation(intent)
        self.wm.set_spec(spec)

        # 冲突提醒（规格 5.4）
        conflict_choice = self._check_conflict(spec)

        satisfaction: int | None = None
        for stage_label, stage_key in STAGE_PLAN:
            text = self.engine.generate(spec, stage_key, conflict_choice)
            self._show_solution(text)
            fb = self.interface.collect_feedback()
            self._handle_feedback(fb, spec)
            score = self._parse_score(fb)
            if score:
                satisfaction = score
            if self._is_pause(fb):
                return self._pause_task(spec, stage_label, fb, text)
            if self._is_done(fb):
                return self._complete_task(spec, satisfaction)
            if stage_label != "成品交付" and not self._wants_continue(fb):
                return self._pause_task(spec, stage_label, fb, text)
        return self._complete_task(spec, satisfaction)

    # ---- 断点续传（规格 4.4） ------------------------------------------
    def _resume_message(self, ep: dict) -> str:
        stage = ep.get("paused_at_stage", "需求澄清")
        last_user = (ep.get("abandon_point") or {}).get("last_user_message", "没有记录")
        suggestion = self._resume_suggestion()
        return (
            f"我们上次在「{stage}」阶段停下来了，你当时觉得「{last_user}」。要接着做吗？\n"
            f"我可以从那里继续，并且我建议这次用「{suggestion}」方式避免同样的问题。\n"
            "回复「接着做」继续，回复「新任务」重新开始。"
        )

    def _resume_suggestion(self) -> str:
        p = self.profile.profile
        if p["collaboration"]["abandon_after_first_draft"] > 0.7:
            return "短小预览版，逐段确认"
        if p["collaboration"]["followup_tolerance"] < 0.5:
            return "尽量少提问，直接给草案"
        return "保持分段节奏，每阶段只推进一小步"

    def _resume_last_task(self, ep: dict) -> None:
        details = dict(ep.get("confirmed_details", {}))
        spec = TaskSpec(
            goal=ep["task_goal"],
            intent_type=ep["intent_type"],
            domain=ep["domain"],
            confirmed_details=details,
            assumptions=["断点续传：从上次暂停处继续"],
            output_format=details.get("output_format", "框架/大纲"),
        )
        self.wm.start(ep["task_id"], None)
        self.wm.data["start_time"] = _now()
        self.wm.set_spec(spec)

        paused = ep.get("paused_at_stage", "框架草案")
        try:
            start_index = STAGE_LABELS.index(paused)
        except ValueError:
            start_index = 1
        satisfaction: int | None = None
        for stage_label, stage_key in STAGE_PLAN[start_index:]:
            text = self.engine.generate(spec, stage_key)
            self._show_solution(text)
            fb = self.interface.collect_feedback()
            self._handle_feedback(fb, spec)
            score = self._parse_score(fb)
            if score:
                satisfaction = score
            if self._is_pause(fb):
                self.episodic.update_episode(
                    ep["task_id"],
                    paused_at_stage=stage_label,
                    abandon_point={
                        "stage": stage_label,
                        "last_user_message": fb,
                        "last_ai_message": text[:200],
                        "inferred_reason": self._infer_abandon_reason(fb),
                    },
                )
                return
            if self._is_done(fb) or (stage_label != "成品交付" and not self._wants_continue(fb)):
                self.episodic.update_episode(ep["task_id"], status="completed", end_time=_now(), user_satisfaction=satisfaction)
                self.interface.show("任务已完成 ✅")
                self.evolution.task_completed()
                self.evolution.save_profile(self.profile)
                return

        self.episodic.update_episode(
            ep["task_id"],
            status="completed",
            end_time=_now(),
            user_satisfaction=satisfaction,
            full_delivered=True,
            used_framework=self.engine.last_framework,
            confirmed_details=spec.confirmed_details,
        )
        self.evolution.task_completed()
        self.evolution.save_profile(self.profile)
        self._maybe_calibrate()
        self.interface.show("任务已完成 ✅")

    # ---- 反馈处理（规格 4.3 / 5.2） ------------------------------------
    def _handle_feedback(self, text: str, spec: TaskSpec) -> None:
        if not text:
            return
        records = self.profile.apply_explicit_rules(text)
        changed = False
        for rec in records:
            if rec.get("before") == rec.get("after"):
                continue
            changed = True
            self.interface.show(f"已记住：{rec['reason']}（{rec['field']} {rec['before']} → {rec['after']}）")
            if self.profile.needs_anomaly_confirmation(rec):
                reply = self.interface.ask_anomaly(
                    f"我注意到你最近似乎更偏向调整「{rec['field']}」了，对吗？\n"
                    "回复「对」确认，否则我会回退这次调整。"
                )
                if reply.strip() not in CONFIRM_WORDS:
                    reverted = self.profile.revert_record(rec)
                    self.interface.show(f"已回退：{reverted['field']} → {reverted['after']}")
        if changed:
            self.evolution.save_profile(self.profile)
            return

        # 隐式信号
        score = self._parse_score(text)
        if text.strip() in QUICK_ACCEPT or (score is not None and score >= 4):
            relevant = [
                ("cognition", "thinking_macro_first"),
                ("cognition", "detail_assist_needed"),
                ("expression", "structure_density"),
                ("expression", "abstraction_level"),
                ("expression", "example_preference"),
                ("collaboration", "abandon_after_first_draft"),
            ]
            self.profile.apply_implicit("quick_acceptance", fields=relevant)
            self.evolution.save_profile(self.profile)
        elif "又" in text or "重复" in text:
            self.profile.apply_implicit("repeated_question", note=text[:40])
            self.evolution.save_profile(self.profile)

    @staticmethod
    def _parse_score(text: str) -> int | None:
        m = re.search(r"([1-5])\s*分", text)
        if m:
            return int(m.group(1))
        if text.strip() in {"1", "2", "3", "4", "5"}:
            return int(text.strip())
        return None

    @staticmethod
    def _is_pause(text: str) -> bool:
        return any(w in text for w in ["先这样", "暂停", "先到这", "不做了", "算了", "先放着"])

    @staticmethod
    def _is_done(text: str) -> bool:
        return any(w in text for w in ["完成", "够了", "不用了", "就这些", "可以了"])

    @staticmethod
    def _wants_continue(text: str) -> bool:
        return (
            "继续" in text
            or text.strip() in QUICK_ACCEPT
            or PersonalExplorerAgent._parse_score(text) is not None
        )

    # ---- 阶段收尾 -----------------------------------------------------
    def _show_solution(self, text: str) -> None:
        text = text + "\n\n此方案匹配度如何？可直接回复：1-5 分，或指出需要调整的地方。"
        self.interface.show(self.interface.style(text))

    def _pause_task(self, spec: TaskSpec, stage_label: str, last_user: str, last_ai: str) -> str:
        episode = self._base_episode(spec, status="paused")
        episode.update({
            "paused_at_stage": stage_label,
            "abandon_point": {
                "stage": stage_label,
                "last_user_message": last_user,
                "last_ai_message": last_ai[:200],
                "inferred_reason": self._infer_abandon_reason(last_user),
            },
            "end_time": _now(),
        })
        self.episodic.add(episode)
        self.evolution.save_profile(self.profile)
        self.interface.show(f"好的，任务已暂停在「{stage_label}」阶段。下次说「接着做」，我会从这里继续。")
        return "paused"

    def _complete_task(self, spec: TaskSpec, satisfaction: int | None) -> str:
        episode = self._base_episode(spec, status="completed")
        episode.update({
            "end_time": _now(),
            "user_satisfaction": satisfaction,
            "full_delivered": True,
            "used_framework": self.engine.last_framework,
        })
        self.episodic.add(episode)
        self.evolution.task_completed()
        self.evolution.save_profile(self.profile)
        self._maybe_calibrate()
        self.interface.show("任务已完成 ✅")
        return "completed"

    def _base_episode(self, spec: TaskSpec, status: str) -> dict:
        return {
            "task_id": self.wm.data.get("task_id") or uuid4().hex[:8],
            "task_goal": spec.goal[:120],
            "intent_type": spec.intent_type,
            "domain": spec.domain,
            "start_time": self.wm.data.get("start_time") or _now(),
            "end_time": None,
            "status": status,
            "abandon_point": None,
            "interaction_log": [],
            "user_feedback": [],
            "used_framework": self.engine.last_framework,
            "user_satisfaction": None,
            "confirmed_details": spec.confirmed_details,
            "full_delivered": False,
        }

    @staticmethod
    def _infer_abandon_reason(last_user: str) -> str:
        if any(w in last_user for w in ["先这样", "算了", "不做了"]):
            return "动力不足/中途暂停"
        if "不知道" in last_user or "随便" in last_user:
            return "信息不足，难以继续"
        return "用户主动暂停"

    def _archive_abandoned(self, ep: dict, reason: str) -> None:
        self.episodic.update_episode(
            ep["task_id"],
            status="abandoned",
            end_time=_now(),
            abandon_point={
                "stage": ep.get("paused_at_stage", "需求澄清"),
                "last_user_message": (ep.get("abandon_point") or {}).get("last_user_message", ""),
                "last_ai_message": (ep.get("abandon_point") or {}).get("last_ai_message", ""),
                "inferred_reason": reason,
            },
        )

    # ---- 冲突提醒（规格 5.4） ------------------------------------------
    def _check_conflict(self, spec: TaskSpec) -> str:
        conflict_kw = ["营销", "广告", "推广", "带货", "卖点"]
        red_lines = self.profile.profile.get("value_red_lines", [])
        if any(k in spec.goal for k in conflict_kw) and any(("套话" in rl) or ("营销" in rl) for rl in red_lines):
            reply = self.interface.ask_conflict(
                "⚠️ 我注意到你要的内容（营销/广告类）和你画像里「讨厌套话、营销味」有冲突。\n"
                "1) 按你的要求写营销内容\n"
                "2) 按你的画像优化：保持直接、具体、不用套话"
            )
            if "2" in reply or "画像" in reply:
                return "按画像优化"
            return "按你的要求"
        return ""

    # ---- 画像查看/调整（规格 5.3） -------------------------------------
    def _adjust_profile(self) -> None:
        self.interface.show(
            "可调整字段示例：expression.output_tone（formal/casual/neutral）、"
            "expression.structure_density、cognition.thinking_macro_first、"
            "collaboration.followup_tolerance 等。"
        )
        field = self.interface.ask_raw("字段名：")
        value_text = self.interface.ask_raw("新值：")
        value = self._coerce(value_text)
        rec = self.profile.update_field(field, value)
        if rec:
            self.interface.show(f"已更新：{rec['field']} → {rec['after']}")
            self.evolution.save_profile(self.profile)
        else:
            self.interface.show("没找到这个字段，请用「维度.字段」格式再试一次。")

    @staticmethod
    def _coerce(text: str):
        low = text.strip().lower()
        if low in {"true", "false"}:
            return low == "true"
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text

    def _show_history(self) -> None:
        episodes = self.episodic.all_episodes()
        if not episodes:
            self.interface.show("还没有历史任务。")
            return
        lines = ["📚 历史任务"]
        for ep in reversed(episodes[-10:]):
            satisfaction = ep.get("user_satisfaction")
            sat = f" | 评分 {satisfaction}" if satisfaction else ""
            lines.append(
                f"- #{ep['task_id']} [{ep.get('status')}] "
                f"{INTENT_LABELS.get(ep.get('intent_type'), ep.get('intent_type'))} / {ep.get('domain')}："
                f"{ep.get('task_goal', '')[:36]}{sat}"
            )
        self.interface.show("\n".join(lines))

    # ---- 主动校准（规格 2.3） ------------------------------------------
    def _maybe_calibrate(self) -> None:
        if not self.evolution.needs_calibration():
            return
        report = self.profile.calibration_report()
        reply = self.interface.ask_calibration(report)
        accepted = reply.strip() in QUICK_ACCEPT or reply.strip() in {"确认", "没问题"}
        self.interface.show(self.profile.confirm_calibration(accepted))
        if accepted:
            self.evolution.after_calibration()
        self.evolution.save_profile(self.profile)
