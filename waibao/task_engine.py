"""任务-框架生成引擎（模块二）

规格 3.1-3.5 + 4.2 + 5.4：
- InputParser        指令解析 → TaskIntent
- GapAnalyzer        缺口分析（复用高相似历史任务、画像推断、只问必要缺口）
- QuestionGenerator  提问生成（封闭式优先；追问耐受度低时合并）
- ConfirmationLoop   多轮确认闭环（≤3 轮；连续 3 次拒绝即停止；不耐烦即声明假设）
- SolutionGenerator  四阶段交付：框架草案 / 内容填充 / 成品交付（画像匹配 + 动力保鲜）
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional


INTENT_LABELS = {
    "explore": "探索研究",
    "generate": "生成内容",
    "organize": "整理信息",
    "decide": "决策辅助",
    "custom": "其他",
}

INTENT_KEYWORDS: dict[str, list[str]] = {
    "explore": ["研究", "探索", "了解", "调研", "分析", "趋势", "前景", "比较一下"],
    "generate": ["写", "生成", "做一个", "做一期", "设计", "策划", "创建", "开发", "出个方案", "出一份", "搞一个"],
    "organize": ["整理", "总结", "汇总", "梳理", "归纳", "清单", "列表"],
    "decide": ["选", "决策", "哪个", "要不要", "该不该", "选择", "对比"],
}

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "music": ["音乐", "专辑", "歌曲", "制作", "编曲", "演出", "厂牌", "独立音乐", "播客"],
    "media": ["传媒", "媒体", "传播", "内容", "流量", "视频", "公众号", "品牌"],
}

GAP_DEFS: dict[str, dict[str, Any]] = {
    "target_audience": {
        "label": "目标受众",
        "question": "这份成果主要给谁看？",
        "options": ["我自己", "团队/合作方", "公众/听众", "你来定"],
    },
    "output_format": {
        "label": "输出形式",
        "question": "你希望我输出成什么形式？",
        "options": ["框架/大纲", "完整文案", "清单/列表", "分步骤方案"],
    },
    "scope": {
        "label": "范围/深度",
        "question": "你希望先要宏观框架，还是直接深入细节？",
        "options": ["宏观框架", "先框架后细节", "直接细节"],
    },
}

IMPATIENT_WORDS = ["随便", "你定", "都可以", "你看着办", "别问了", "你来定", "按你的来", "尽快"]
ACCEPT_WORDS = {"确认", "可以", "没问题", "好", "行", "是", "ok", "OK", "Ok"}
INTENT_OPTION_MAP = {
    "探索/研究": "explore",
    "生成/创作": "generate",
    "整理/汇总": "organize",
    "决策/选择": "decide",
    "其他": "custom",
}
DOMAIN_OPTION_MAP = {"音乐": "music", "传媒": "media", "其他": "other"}


@dataclass
class TaskIntent:
    raw_input: str
    intent_type: str
    domain_hint: str
    missing_info: list[str] = field(default_factory=list)
    user_preferences_used: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskSpec:
    goal: str
    intent_type: str
    domain: str
    confirmed_details: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    output_format: str = "框架/大纲"
    similar_episodes: list[tuple[str, float]] = field(default_factory=list)


class InputParser:
    """规格 3.1：原始文本 → TaskIntent。"""

    def __init__(self, profile: Any) -> None:
        self._profile = profile

    def parse(self, raw: str) -> TaskIntent:
        intent_type = self._detect_intent(raw)
        domain_hint = self._detect_domain(raw)
        prefs = {
            "thinking_macro_first": self._profile.get("cognition", "thinking_macro_first"),
            "output_tone": self._profile.get("expression", "output_tone"),
            "structure_density": self._profile.get("expression", "structure_density"),
            "abstraction_level": self._profile.get("expression", "abstraction_level"),
            "example_preference": self._profile.get("expression", "example_preference"),
        }
        return TaskIntent(
            raw_input=raw,
            intent_type=intent_type,
            domain_hint=domain_hint,
            user_preferences_used=prefs,
        )

    def _detect_intent(self, raw: str) -> str:
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(k in raw for k in keywords):
                return intent
        return "custom"

    def _detect_domain(self, raw: str) -> str:
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(k in raw for k in keywords):
                return domain
        return ""  # 无领域关键词 → 需要澄清（规格 5.4 极其模糊输入）


class GapAnalyzer:
    """规格 3.2：缺口分析。"""

    def analyze(self, intent: TaskIntent, profile: Any, similar: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        p = profile.profile
        details = (similar or {}).get("confirmed_details", {})

        # 目标受众：无法从画像推断；高相似历史任务已有则复用（规格 4.2 跳过部分提问）
        if not details.get("target_audience"):
            gaps.append(dict(GAP_DEFS["target_audience"], id="target_audience"))

        # 输出形式：意图已暗示则不问；否则复用相似任务，否则提问
        if not self._infer_format(intent) and not details.get("output_format"):
            gaps.append(dict(GAP_DEFS["output_format"], id="output_format"))

        # 范围/深度：宏观优先 >0.7 则可推断，不提问
        if p["cognition"]["thinking_macro_first"] <= 0.7 and not details.get("scope"):
            gaps.append(dict(GAP_DEFS["scope"], id="scope"))
        return gaps

    @staticmethod
    def _infer_format(intent: TaskIntent) -> str:
        if intent.intent_type == "organize":
            return "清单/列表"
        if intent.intent_type == "decide":
            return "决策建议"
        if intent.intent_type == "explore":
            return "研究框架"
        if "清单" in intent.raw_input or "列表" in intent.raw_input:
            return "清单/列表"
        return ""


class QuestionGenerator:
    """规格 3.3：提问生成。"""

    @staticmethod
    def generate(gaps: list[dict[str, Any]], profile: Any) -> list[dict[str, Any]]:
        tolerance = profile.get("collaboration", "followup_tolerance")
        if tolerance < 0.5:
            return [{
                "id": "merged",
                "question": "为了节省你的时间，我按你的习惯推进：先出宏观框架、再逐层展开，可以吗？",
                "options": ["可以", "我来补充两点"],
            }]
        return copy.deepcopy(gaps[:3])


class ConfirmationLoop:
    """规格 3.4 + 5.4：多轮确认闭环。"""

    def __init__(self, interface: Any, profile: Any, episodic: Any, max_rounds: int = 3) -> None:
        self.interface = interface
        self.profile = profile
        self.episodic = episodic
        self.max_rounds = max_rounds

    def run(self, intent: TaskIntent) -> TaskSpec:
        # 规格 4.2：检索最相似历史任务，相似度 > 0.8 视为同类任务
        retrieved = self.episodic.retrieve_similar(
            goal=intent.raw_input,
            intent=intent.intent_type,
            domain=intent.domain_hint,
            top_k=3,
        )
        similar: Optional[dict[str, Any]] = None
        similar_score = 0.0
        for ep, score in retrieved:
            if score >= 0.8:
                similar, similar_score = ep, score
                break

        details: dict[str, Any] = dict((similar or {}).get("confirmed_details", {}))
        assumptions: list[str] = []
        if similar:
            assumptions.append(f"命中相似历史任务（相似度 {similar_score}），直接复用其框架，仅确认差异点")

        gaps = GapAnalyzer().analyze(intent, self.profile, similar)
        gaps = self._prepend_clarify_gaps(gaps, intent)  # 规格 5.4：极其模糊输入先澄清

        rounds = 0
        consecutive_rejections = 0
        while gaps and rounds < self.max_rounds:
            questions = QuestionGenerator.generate(gaps, self.profile)
            answers = self.interface.ask_closed(questions)
            rounds += 1

            if self._is_impatient(answers):
                consecutive_rejections += 1
                if consecutive_rejections >= 3:
                    assumptions.append("连续三次拒绝/放弃提问，停止追问，采用画像默认值生成初步草案")
                    break
                assumptions.append("用户表现出不耐烦，跳过本组提问，改用画像默认值补全")
                continue
            consecutive_rejections = 0

            for q in questions:
                answer = answers.get(q["id"], "")
                if not answer or self._is_impatient_value(answer):
                    continue
                if q["id"] == "intent_goal":
                    intent.intent_type = INTENT_OPTION_MAP.get(answer, intent.intent_type)
                elif q["id"] == "domain_goal":
                    details["_domain"] = DOMAIN_OPTION_MAP.get(answer, answer)
                else:
                    details[q["id"]] = answer
            gaps = [g for g in gaps if g["id"] not in answers or not answers.get(g["id"])]

        domain_override = details.pop("_domain", "")
        inferred_format = GapAnalyzer._infer_format(intent)
        if inferred_format:
            details["output_format"] = inferred_format
        self._fill_assumptions(details, assumptions, intent)

        spec = TaskSpec(
            goal=intent.raw_input,
            intent_type=intent.intent_type,
            domain=domain_override or intent.domain_hint or self.profile.get("domain", "domain_primary"),
            confirmed_details=details,
            assumptions=assumptions,
            output_format=details.get("output_format", inferred_format or "框架/大纲"),
            similar_episodes=[(ep["task_id"], score) for ep, score in retrieved],
        )

        reply = self.interface.confirm_spec(self._render_spec(spec, similar, similar_score))
        if self._is_accept(reply):
            return spec
        if reply and not self._is_impatient_value(reply):
            details["user_notes"] = reply
            spec.assumptions.append(f"用户补充说明：{reply}")
        return spec

    # ---- 内部工具 -----------------------------------------------------
    @staticmethod
    def _prepend_clarify_gaps(gaps: list[dict[str, Any]], intent: TaskIntent) -> list[dict[str, Any]]:
        """规格 5.4：输入极其模糊（无领域/无意图）时先澄清，不要直接生成。"""
        extra: list[dict[str, Any]] = []
        if not intent.domain_hint:
            extra.append({
                "id": "domain_goal",
                "label": "领域",
                "question": "这次主要在哪个领域？",
                "options": ["音乐", "传媒", "其他"],
            })
        if intent.intent_type == "custom":
            extra.append({
                "id": "intent_goal",
                "label": "任务类型",
                "question": "这次主要想做什么？",
                "options": ["探索/研究", "生成/创作", "整理/汇总", "决策/选择", "其他"],
            })
        return extra + gaps

    @staticmethod
    def _is_impatient_value(text: str) -> bool:
        return any(w in text for w in IMPATIENT_WORDS)

    @classmethod
    def _is_impatient(cls, answers: dict[str, str]) -> bool:
        return any(cls._is_impatient_value(v) for v in answers.values())

    @staticmethod
    def _is_accept(text: str) -> bool:
        return text.strip() in ACCEPT_WORDS

    @staticmethod
    def _fill_assumptions(details: dict[str, Any], assumptions: list[str], intent: TaskIntent) -> None:
        if not details.get("target_audience"):
            details["target_audience"] = "（画像推断：音乐行业从业者/爱好者）"
            assumptions.append("目标受众未指定，按画像推断为音乐行业从业者/爱好者")
        if not details.get("output_format"):
            inferred = GapAnalyzer._infer_format(intent) or "框架/大纲"
            details["output_format"] = inferred
            assumptions.append(f"输出形式未指定，按意图推断为：{inferred}")

    @staticmethod
    def _render_spec(spec: TaskSpec, similar: Optional[dict[str, Any]], similar_score: float) -> str:
        lines = ["📋 任务规格书", f"- 目标：{spec.goal}"]
        lines.append(f"- 意图：{INTENT_LABELS.get(spec.intent_type, spec.intent_type)}")
        lines.append(f"- 领域：{spec.domain}")
        lines.append("- 已确认信息：")
        if spec.confirmed_details:
            for key, value in spec.confirmed_details.items():
                label = GAP_DEFS.get(key, {}).get("label", key)
                lines.append(f"  · {label}：{value}")
        else:
            lines.append("  （无）")
        lines.append("- 假设：" + ("；".join(spec.assumptions) if spec.assumptions else "无"))
        if similar:
            lines.append(f"- 复用历史任务框架：# {similar.get('task_id')}（相似度 {similar_score}）")
        lines.append("")
        lines.append("回复「确认」即可，或直接告诉我哪里要改。")
        return "\n".join(lines)


class SolutionGenerator:
    """规格 3.5 + 4.4 动力保鲜：四阶段交付（framework/full/final）。"""

    FRAMEWORK_TEMPLATES: dict[str, dict[str, list[str]]] = {
        "generate": {
            "定位与目标": ["明确受众与价值主张"],
            "内容体系": ["栏目架构、选题逻辑、发布频次"],
            "制作流程": ["从策划到发布的环节与分工"],
            "分发与增长": ["渠道策略与反馈闭环"],
            "评估与迭代": ["核心指标与复盘节奏"],
        },
        "organize": {
            "分类维度": ["按主题/阶段/优先级切分"],
            "筛选标准": ["明确收录与剔除规则"],
            "呈现顺序": ["从高频刚需到低频补充"],
            "后续维护": ["更新节奏与责任归属"],
        },
        "explore": {
            "问题定义": ["把模糊问题收敛为可回答的问题"],
            "现状扫描": ["梳理已知事实与已有资料"],
            "关键变量": ["列出影响结论的变量"],
            "结论与下一步": ["给出初步判断与验证路径"],
        },
        "decide": {
            "选项与标准": ["列出候选方案与评判标准"],
            "权衡矩阵": ["按标准逐项对比"],
            "推荐与理由": ["给出倾向性建议"],
            "执行路径": ["落地步骤与回退方案"],
        },
    }

    DETAIL_TEMPLATES: dict[str, list[str]] = {
        "定位与目标": ["受众：{target_audience}", "价值主张：一句话说清用户获得什么", "差异化：与现有同类内容/方案的区隔"],
        "内容体系": ["栏目架构：1 个主线栏目 + 机动选题", "选题逻辑：按反馈与领域热点排序", "频次：先稳定节奏，再逐步加量"],
        "制作流程": ["策划 → 采集 → 初稿 → 审校 → 发布", "每环节明确产出物与责任人"],
        "分发与增长": ["主渠道 + 二次分发渠道", "建立评论/私信反馈闭环"],
        "评估与迭代": ["指标：完读/收听、互动、转化", "每月复盘一次，按数据调整选题"],
        "分类维度": ["按主题分组，再按优先级排序", "预留「灵感池」存放待定选题"],
        "筛选标准": ["与目标受众相关、可持续产出、有差异化"],
        "呈现顺序": ["先放高优先级，再补长尾选题"],
        "后续维护": ["每周补充新选题，每月清理失效项"],
        "问题定义": ["把「想了解什么」写成一句话问题", "明确回答到什么程度算完成"],
        "现状扫描": ["列出已掌握的信息与资料来源", "标注不确定性较高的部分"],
        "关键变量": ["影响结论的核心变量与权重", "需要验证的假设"],
        "结论与下一步": ["给出初步判断", "列出验证或补充资料的路径"],
        "选项与标准": ["候选方案 ≥ 2 个，标准 ≤ 5 条"],
        "权衡矩阵": ["逐项打分并说明理由"],
        "推荐与理由": ["给出首选及适用条件"],
        "执行路径": ["小步试点，保留回退方案"],
    }

    def __init__(self, llm: Any = None) -> None:
        self.llm = llm

    def generate(
        self,
        spec: TaskSpec,
        profile: Any,
        stage: str = "framework",
        conflict_choice: str = "",
    ) -> tuple[str, dict[str, list[str]]]:
        if self.llm and getattr(self.llm, "enabled", False):
            try:
                return self.llm.generate(spec, profile, stage, conflict_choice), self._framework(spec)
            except NotImplementedError:
                pass

        p = profile.profile
        framework = self._framework(spec)
        if stage == "framework":
            text = self._render_framework_only(framework, spec, p)
        elif stage == "full":
            text = self._render_full(framework, spec)
        else:
            text = self._render_final(framework, spec, p)

        if conflict_choice == "按画像优化":
            text = "（已按你的偏好去掉营销套话，保持直接、具体）\n\n" + text
        elif conflict_choice == "按你的要求":
            text = "（按你的要求保留营销表达）\n\n" + text

        text += "\n\n如果需要调整，直接告诉我哪里不对，我会记住。"
        return text, framework

    def _framework(self, spec: TaskSpec) -> dict[str, list[str]]:
        key = spec.intent_type if spec.intent_type in self.FRAMEWORK_TEMPLATES else "generate"
        return copy.deepcopy(self.FRAMEWORK_TEMPLATES[key])

    def _render_framework_only(self, framework: dict[str, list[str]], spec: TaskSpec, p: dict[str, Any]) -> str:
        """框架草案（预览版）：高 abandon 风险时保持短小，只给高层级（规格 4.4 动力保鲜）。"""
        lines = [f"# 方案框架（预览版）：{spec.goal}"]
        for i, (section, bullets) in enumerate(framework.items(), 1):
            lines.append(f"\n## {i}. {section}")
            for bullet in bullets:
                lines.append(f"- {bullet}")
        return "\n".join(lines)

    def _render_full(self, framework: dict[str, list[str]], spec: TaskSpec) -> str:
        lines = [f"# 完整方案：{spec.goal}"]
        details = spec.confirmed_details
        for i, section in enumerate(framework.keys(), 1):
            lines.append(f"\n## {i}. {section}")
            for tpl in self.DETAIL_TEMPLATES.get(section, []):
                try:
                    line = tpl.format(**details)
                except KeyError:
                    line = tpl
                lines.append(f"- {line}")
        return "\n".join(lines)

    def _render_final(self, framework: dict[str, list[str]], spec: TaskSpec, p: dict[str, Any]) -> str:
        """成品交付：一句话成果 + 交付摘要；structure_density > 0.7 时用表格（规格 5.1）。"""
        audience = spec.confirmed_details.get("target_audience", "目标人群")
        intent_label = INTENT_LABELS.get(spec.intent_type, spec.intent_type)
        lines = [
            f"# 成品交付：{spec.goal}",
            "",
            f"一句话成果：面向「{audience}」的{intent_label}方案，以「{spec.output_format}」形式交付。",
            "",
        ]
        if p["expression"]["structure_density"] > 0.7:
            lines.append("| 阶段 | 产出 | 要点 |")
            lines.append("| --- | --- | --- |")
            for section, bullets in framework.items():
                lines.append(f"| {section} | {bullets[0]} | {'；'.join(bullets[:2])} |")
            lines.append("")
        else:
            for section, bullets in framework.items():
                lines.append(f"- **{section}**：{'；'.join(bullets)}")
            lines.append("")
        lines.append("- 你可以直接使用，或告诉我哪里要调。")
        return "\n".join(lines)


class TaskFrameworkEngine:
    """模块二门面：解析 → 确认 → 生成。"""

    def __init__(self, profile: Any, episodic: Any, interface: Any, llm: Any = None) -> None:
        self.profile = profile
        self.episodic = episodic
        self.interface = interface
        self.llm = llm
        self.last_framework: Optional[dict[str, list[str]]] = None

    def parse(self, raw: str) -> TaskIntent:
        return InputParser(self.profile).parse(raw)

    def run_confirmation(self, intent: TaskIntent) -> TaskSpec:
        return ConfirmationLoop(self.interface, self.profile, self.episodic).run(intent)

    def generate(self, spec: TaskSpec, stage: str = "framework", conflict_choice: str = "") -> str:
        text, framework = SolutionGenerator(self.llm).generate(spec, self.profile, stage, conflict_choice)
        self.last_framework = framework
        return text
