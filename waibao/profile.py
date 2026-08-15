"""用户画像系统（模块一）

规格 2.1-2.3 + 4.3：
- 四个画像维度 + 价值观红线，字段与初始值对齐规格 2.1
- 首次对话初始化：不超过 5 个封闭式问题（规格 2.2）
- 显式反馈按“指数趋近”公式更新：w = w + lr * (target - w)（规格 4.3）
- 隐式反馈按“lr * delta”更新（规格 4.3）
- learning_rate 初始 0.3，随时间衰减（规格 4.3）
- 超过 30 天未更新的字段向初始值回退 10%（时间衰减，规格 4.3）
- 异常检测：单次变化 > 0.3 需用户确认（规格 4.3，确认逻辑在 agent）
- 每 5 个任务或 7 天生成画像变化校准报告（规格 2.3）
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# ---------------------------------------------------------------------------
# 画像字段初始值（规格 2.1）
# ---------------------------------------------------------------------------
DEFAULT_PROFILE: dict[str, Any] = {
    "cognition": {
        "thinking_macro_first": 0.8,   # 宏观优先（1=完全宏观，0=完全细节优先）
        "detail_assist_needed": 0.7,   # 需要 AI 补充细节的程度
        "logic_over_intuition": 0.5,   # 逻辑 vs 直觉
        "depth_first": 0.6,            # 深度优先 vs 广度优先
    },
    "expression": {
        "output_tone": "neutral",      # formal / casual / neutral
        "structure_density": 0.6,      # 结构化输出密度
        "example_preference": 0.3,     # 举例偏好（默认低）
        "abstraction_level": 0.7,      # 抽象程度偏好
    },
    "domain": {
        "domain_primary": "music",
        "domain_secondary": "media",
        "domain_depth_primary": 0.6,
        "domain_depth_secondary": 0.5,
        "unfamiliar_topics": [],
    },
    "collaboration": {
        "decision_speed": 0.6,
        "followup_tolerance": 0.8,
        "abandon_after_first_draft": 0.75,
        "need_progress_milestones": True,
        "carryover_patterns": [],
    },
    "value_red_lines": ["厌恶空洞套话", "反感说教", "不喜欢过度营销术语"],
}


# ---------------------------------------------------------------------------
# 首次对话初始化（规格 2.2）
# ---------------------------------------------------------------------------
INIT_QUESTIONS: list[dict[str, Any]] = [
    {"id": "macro_or_detail", "question": "你更倾向于我直接给出整体框架，还是先和你讨论细节？", "options": ["直接给框架", "先讨论细节", "都可以"]},
    {"id": "music_role", "question": "你在音乐领域主要做制作、产业还是理论？", "options": ["制作", "产业", "理论"]},
    {"id": "tone", "question": "你希望我的表达语气偏正式、随意还是中性？", "options": ["正式", "随意", "中性"]},
    {"id": "draft_habit", "question": "如果我已经生成了一个完整初稿，你通常是想马上使用，还是会继续修改？", "options": ["马上使用", "继续修改", "看情况"]},
    {"id": "examples", "question": "需要我在回答中主动举例子吗？", "options": ["需要", "不需要", "偶尔"]},
]


_INIT_MAPPING: dict[str, dict[str, Tuple[str, str, Any]]] = {
    "macro_or_detail": {
        "直接给框架": ("cognition", "thinking_macro_first", 0.9),
        "先讨论细节": ("cognition", "thinking_macro_first", 0.3),
        "都可以": ("cognition", "thinking_macro_first", 0.6),
    },
    "music_role": {
        "制作": ("domain", "domain_depth_primary", 0.75),
        "产业": ("domain", "domain_depth_primary", 0.7),
        "理论": ("domain", "domain_depth_primary", 0.9),
    },
    "tone": {
        "正式": ("expression", "output_tone", "formal"),
        "随意": ("expression", "output_tone", "casual"),
        "中性": ("expression", "output_tone", "neutral"),
    },
    "draft_habit": {
        "马上使用": ("collaboration", "abandon_after_first_draft", 0.4),
        "继续修改": ("collaboration", "abandon_after_first_draft", 0.85),
        "看情况": ("collaboration", "abandon_after_first_draft", 0.6),
    },
    "examples": {
        "需要": ("expression", "example_preference", 0.7),
        "不需要": ("expression", "example_preference", 0.1),
        "偶尔": ("expression", "example_preference", 0.4),
    },
}

# 自由回答 → 选项 的关键词兜底（未启用 LLM 时使用）
_KEYWORD_HINTS: dict[str, dict[str, list[str]]] = {
    "macro_or_detail": {
        "直接给框架": ["框架", "整体", "宏观", "先给", "直接"],
        "先讨论细节": ["细节", "讨论", "先聊", "慢慢"],
        "都可以": ["都行", "随便", "你定", "看你"],
    },
    "music_role": {
        "制作": ["制作", "创作", "写歌", "编曲", "录"],
        "产业": ["产业", "行业", "经营", "厂牌", "经纪"],
        "理论": ["理论", "学术", "研究", "乐理"],
    },
    "tone": {
        "正式": ["正式", "专业", "严肃"],
        "随意": ["随意", "轻松", "口语", "聊"],
        "中性": ["中性", "都行", "正常", "平衡"],
    },
    "draft_habit": {
        "马上使用": ["马上用", "直接用", "不改", "上手"],
        "继续修改": ["修改", "继续改", "打磨", "完善"],
        "看情况": ["看情况", "不一定", "视情况"],
    },
    "examples": {
        "不需要": ["不需要", "不用", "别举", "不要例", "少举", "不举"],
        "需要": ["需要", "要例子", "给个例", "要举"],
        "偶尔": ["偶尔", "有时候", "一点"],
    },
}


# ---------------------------------------------------------------------------
# 显式反馈规则（规格 4.3）：(正则, 字段路径, target, 说明)
# 数值字段用 target 做指数趋近；字符串直接设置；红线追加。
# ---------------------------------------------------------------------------
_EXPLICIT_RULES: list[Tuple[re.Pattern, Tuple[str, ...], Any, str]] = [
    (re.compile(r"不要(再)?(举例|例子|案例)"), ("expression", "example_preference"), 0.1, "你不想被主动举例"),
    (re.compile(r"多(给|来)点?细节|详细一点|再具体点|展开一下"), ("cognition", "detail_assist_needed"), 0.9, "你需要更多细节"),
    (re.compile(r"太抽象|太概念|都是空话|太虚"), ("expression", "abstraction_level"), 0.3, "你希望更具体"),
    (re.compile(r"太(正式|严肃)了|随意一点|轻松点"), ("expression", "output_tone"), "casual", "你希望语气更随意"),
    (re.compile(r"太随意|正式一点|严肃点|专业一点"), ("expression", "output_tone"), "formal", "你希望语气更正式"),
    (re.compile(r"太(长|啰嗦|冗长)|简洁一点|少说点"), ("expression", "structure_density"), 0.35, "你希望更简洁"),
    (re.compile(r"结构(化)?一点|分点|列表|用表格|条理一点"), ("expression", "structure_density"), 0.9, "你希望更结构化"),
    (re.compile(r"套话|说教|讲大道理|空话|营销味"), ("value_red_lines",), None, "你不想看到套话"),
]


class ProfileSystem:
    """用户画像：初始化、更新（显式/隐式/手动）、时间衰减、校准、摘要。"""

    BASE_LR = 0.3            # learning_rate 初始值（规格 4.3）
    ANOMALY_THRESHOLD = 0.3  # 单次变化超过该值触发主动确认（规格 4.3）
    DECAY_DAYS = 30          # 超过该天数未更新则回退 10%（规格 4.3）

    def __init__(self) -> None:
        self.profile: dict[str, Any] = copy.deepcopy(DEFAULT_PROFILE)
        self.meta: dict[str, Any] = {}
        self.created_ts: str = _now()
        # key = "dim.fname" -> {"last_updated": str, "updated_count": int}
        self.field_meta: dict[str, dict[str, Any]] = {}
        self.last_calibration_snapshot: dict[str, Any] = copy.deepcopy(DEFAULT_PROFILE)
        self.update_log: list[dict[str, Any]] = []
        self._init_field_meta()

    # ---- 基础 ----------------------------------------------------------
    def _init_field_meta(self) -> None:
        for dim, content in self.profile.items():
            if isinstance(content, dict):
                for fname in content:
                    self.field_meta[f"{dim}.{fname}"] = {"last_updated": self.created_ts, "updated_count": 0}
            else:
                self.field_meta[dim] = {"last_updated": self.created_ts, "updated_count": 0}

    def _lr(self) -> float:
        """learning_rate：初始 0.3，每 30 天 ×0.9 衰减。"""
        try:
            days = max((datetime.now(timezone.utc) - datetime.fromisoformat(self.created_ts)).days, 0)
        except ValueError:
            days = 0
        return round(self.BASE_LR * (0.9 ** (days / 30.0)), 4)

    def get(self, dim: str, fname: str) -> Any:
        return self.profile[dim][fname]

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.profile)

    # ---- 初始化对话（规格 2.2） ----------------------------------------
    def init_questions(self) -> list[dict[str, Any]]:
        return copy.deepcopy(INIT_QUESTIONS)

    def apply_initial_answers(self, answers: dict[str, str], llm: Any = None) -> None:
        """把（可能是自由的）回答理解成画像字段。

        依次尝试：精确选项 → 包含选项 → LLM 理解 → 关键词兜底。
        """
        qmap = {q["id"]: q for q in INIT_QUESTIONS}
        for qid, answer in answers.items():
            q = qmap.get(qid)
            if not q:
                continue
            options = q["options"]
            matched = answer if answer in options else ""
            if not matched:
                for opt in options:
                    if opt in answer:
                        matched = opt
                        break
            if not matched and llm is not None and getattr(llm, "enabled", False):
                got = llm.interpret_choice(q["question"], answer, options)
                if got in options:
                    matched = got
            if not matched:
                matched = self._keyword_match(qid, answer)
            mapping = _INIT_MAPPING.get(qid, {})
            if matched in mapping:
                dim, fname, value = mapping[matched]
                self._apply((dim, fname), value, f"画像初始化问题「{qid}」", mode="direct")
                self.meta[f"init_{qid}"] = answer

    @staticmethod
    def _keyword_match(qid: str, answer: str) -> str:
        for opt, hints in _KEYWORD_HINTS.get(qid, {}).items():
            if any(h in answer for h in hints):
                return opt
        return ""

    # ---- 核心写入（规格 4.3 更新公式） ---------------------------------
    def _apply(
        self,
        path: Tuple[str, ...],
        value: Any,
        reason: str,
        mode: str = "direct",
    ) -> dict[str, Any]:
        """mode:
        - direct         直接设置（初始化 / 手动调整 / 回退）
        - explicit       w + lr * (target - w)
        - implicit_delta w + lr * delta
        """
        dim, fname = path[0], path[1]
        before = copy.deepcopy(self.profile[dim][fname])
        if isinstance(before, (int, float)) and isinstance(value, (int, float)):
            lr = self._lr()
            if mode == "explicit":
                after = before + lr * (value - before)
            elif mode == "implicit_delta":
                after = before + lr * value
            else:
                after = value
            after = round(_clamp01(after), 2)
        else:
            after = value
        self.profile[dim][fname] = after

        key = f"{dim}.{fname}"
        fmeta = self.field_meta.setdefault(key, {"last_updated": _now(), "updated_count": 0})
        fmeta["last_updated"] = _now()
        fmeta["updated_count"] = fmeta.get("updated_count", 0) + 1
        rec = {
            "field": key,
            "before": before,
            "after": after,
            "reason": reason,
            "ts": _now(),
            "mode": mode,
        }
        if before != after:
            self.update_log.append(rec)
        return rec

    # ---- 显式反馈（权重最高，规格 4.3） --------------------------------
    def apply_explicit_rules(self, text: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for pattern, path, target, label in _EXPLICIT_RULES:
            if pattern.search(text):
                if path[0] == "value_red_lines":
                    if target not in self.profile["value_red_lines"]:
                        self.profile["value_red_lines"].append(target)
                        records.append({
                            "field": "value_red_lines",
                            "before": "（未记录）",
                            "after": target,
                            "reason": f"显式反馈：{label}",
                            "ts": _now(),
                            "mode": "append",
                        })
                elif isinstance(target, str):
                    records.append(self._apply(path, target, f"显式反馈：{label}", mode="direct"))
                else:
                    records.append(self._apply(path, target, f"显式反馈：{label}", mode="explicit"))
        return records

    # ---- 隐式反馈（规格 4.3） ------------------------------------------
    def apply_implicit(self, kind: str, note: str = "", fields: Optional[list[Tuple[str, str]]] = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if kind == "stagnation":
            records.append(self._apply(("cognition", "detail_assist_needed"), 0.05, "隐式信号：停滞超过120秒", mode="implicit_delta"))
            records.append(self._apply(("collaboration", "abandon_after_first_draft"), 0.05, "隐式信号：停滞超过120秒", mode="implicit_delta"))
        elif kind == "skipped_examples":
            records.append(self._apply(("expression", "example_preference"), -0.1, "隐式信号：跳过案例", mode="implicit_delta"))
        elif kind == "repeated_edits":
            records.append(self._apply(("expression", "structure_density"), 0.1, "隐式信号：修改频率高", mode="implicit_delta"))
        elif kind == "quick_acceptance":
            for dim, fname in fields or []:
                records.append(self._apply((dim, fname), 0.02, "隐式信号：快速确认（画像吻合）", mode="implicit_delta"))
        elif kind == "repeated_question":
            self.profile["collaboration"]["carryover_patterns"].append(note or "重复询问同类问题")
        return records

    # ---- 时间衰减（规格 4.3） ------------------------------------------
    def apply_time_decay(self) -> list[dict[str, Any]]:
        """超过 30 天未更新的数值字段，向初始值回退 10%。"""
        records: list[dict[str, Any]] = []
        now_dt = datetime.now(timezone.utc)
        for key, fmeta in self.field_meta.items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            dim, fname = parts
            current = self.profile[dim][fname]
            if not isinstance(current, (int, float)):
                continue
            try:
                days = (now_dt - datetime.fromisoformat(fmeta["last_updated"])).days
            except (ValueError, KeyError):
                continue
            if days > self.DECAY_DAYS:
                initial = DEFAULT_PROFILE[dim][fname]
                records.append(self._apply(
                    (dim, fname),
                    round(_clamp01(current + 0.1 * (initial - current)), 2),
                    "时间衰减：超过30天未更新，向初始值回退10%",
                    mode="direct",
                ))
        return records

    # ---- 异常检测支持（规格 4.3） --------------------------------------
    def needs_anomaly_confirmation(self, rec: dict[str, Any]) -> bool:
        if rec.get("mode") != "explicit":
            return False
        if not isinstance(rec.get("before"), (int, float)) or not isinstance(rec.get("after"), (int, float)):
            return False
        return abs(rec["after"] - rec["before"]) > self.ANOMALY_THRESHOLD

    def revert_record(self, rec: dict[str, Any]) -> dict[str, Any]:
        """用户未确认异常调整时回退。"""
        parts = rec["field"].split(".", 1)
        if len(parts) == 2:
            reverted = self._apply((parts[0], parts[1]), rec["before"], "异常调整未获用户确认，已回退", mode="direct")
        else:
            reverted = {"field": rec["field"], "before": rec["before"], "after": rec["before"], "reason": "异常调整未获确认", "ts": _now()}
        return reverted

    # ---- 手动调整（规格 5.3，最高权重） --------------------------------
    def update_field(self, field_path: str, value: Any) -> Optional[dict[str, Any]]:
        parts = field_path.split(".", 1)
        if len(parts) == 2:
            dim, fname = parts
        else:
            fname = parts[0]
            dim = next((d for d, content in self.profile.items() if isinstance(content, dict) and fname in content), None)
            if dim is None:
                return None
        if dim not in self.profile or fname not in self.profile.get(dim, {}):
            return None
        return self._apply((dim, fname), value, "用户手动调整画像（最高权重显式反馈）", mode="direct")

    # ---- 主动校准（规格 2.3） ------------------------------------------
    def calibration_report(self) -> str:
        lines: list[str] = []
        for dim, content in self.profile.items():
            if isinstance(content, dict):
                for fname, value in content.items():
                    old = self.last_calibration_snapshot.get(dim, {}).get(fname)
                    if old != value:
                        lines.append(f"- {dim}.{fname}：{old} → {value}")
            else:
                old = self.last_calibration_snapshot.get(dim)
                if old != content:
                    added = [x for x in content if x not in old]
                    lines.append(f"- {dim}：新增 {added}" if added else f"- {dim}：{old} → {content}")
        if not lines:
            return "画像变化报告：最近没有检测到明显变化，无需校准。"
        return (
            "画像变化报告（自上次校准以来的变化）：\n"
            + "\n".join(lines)
            + "\n\n请回复「确认」，或直接指出哪一条不对。"
        )

    def confirm_calibration(self, accepted: bool) -> str:
        if accepted:
            self.last_calibration_snapshot = copy.deepcopy(self.profile)
            return "好的，画像已确认，并作为新的基准。"
        return "收到，我会继续观察，暂不更新基准。"

    # ---- 查看画像（规格 5.3） ------------------------------------------
    def summary(self) -> str:
        lines = ["📊 当前画像"]
        for dim, content in self.profile.items():
            if isinstance(content, dict):
                lines.append(f"\n【{dim}】")
                for fname, value in content.items():
                    lines.append(f"  {fname}: {value}")
            else:
                lines.append(f"\n【{dim}】{content}")
        lines.append(f"\nlearning_rate 当前值: {self._lr()}（初始 {self.BASE_LR}，随时间衰减）")
        return "\n".join(lines)

    # ---- 持久化辅助 ---------------------------------------------------
    def to_flat(self) -> dict[str, dict[str, Any]]:
        flat: dict[str, dict[str, Any]] = {}
        for dim, content in self.profile.items():
            if isinstance(content, dict):
                for fname, value in content.items():
                    key = f"{dim}.{fname}"
                    flat[key] = {
                        "value": copy.deepcopy(value),
                        "last_updated": self.field_meta.get(key, {}).get("last_updated", _now()),
                    }
            else:
                flat[dim] = {"value": copy.deepcopy(content), "last_updated": self.field_meta.get(dim, {}).get("last_updated", _now())}
        return flat

    def from_flat(self, flat: dict[str, dict[str, Any]]) -> None:
        for key, rec in flat.items():
            parts = key.split(".", 1)
            if len(parts) == 1:
                self.profile[parts[0]] = copy.deepcopy(rec["value"])
            else:
                dim, fname = parts
                self.profile.setdefault(dim, {})[fname] = copy.deepcopy(rec["value"])
            self.field_meta.setdefault(key, {"last_updated": _now(), "updated_count": 0})["last_updated"] = rec.get("last_updated", _now())
        self.last_calibration_snapshot = copy.deepcopy(self.profile)
