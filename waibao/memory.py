"""记忆与进化系统（模块三）

三类记忆，互不干扰：
- LongTermMemory  长期记忆：画像字段 JSON 持久化（value + last_updated）
- WorkingMemory   短期工作记忆：仅服务当前任务，内存字典
- EpisodicMemory  情景记忆库：任务快照 JSON 持久化 + 语义相似检索（规格 4.2）

MemoryEvolutionSystem：画像同步、任务计数、5 任务或 7 天触发校准。
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokenize(text: str) -> set[str]:
    """轻量特征：英文按单词，中文按二元组（bigram）。"""
    tokens: set[str] = set()
    for word in re.findall(r"[a-zA-Z0-9]+", text or ""):
        if len(word) >= 2:
            tokens.add(word.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        if len(run) <= 2:
            tokens.add(run)
        else:
            for i in range(len(run) - 1):
                tokens.add(run[i : i + 2])
    return tokens


def _cosine(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


class LongTermMemory:
    """长期记忆：JSON 键值存储，键 = 画像字段名。"""

    FILE = "long_term_memory.json"

    def __init__(self, storage_dir: str | Path) -> None:
        self.path = Path(storage_dir) / self.FILE
        self._data: dict[str, Any] = {"fields": {}, "meta": {}}

    def load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def all_fields(self) -> dict[str, dict[str, Any]]:
        return self._data["fields"]

    def get_field(self, key: str) -> Optional[dict[str, Any]]:
        return self._data["fields"].get(key)

    def set_field(self, key: str, value: Any, ts: Optional[str] = None) -> None:
        self._data["fields"][key] = {"value": value, "last_updated": ts or _now()}

    def sync_profile(self, flat: dict[str, dict[str, Any]]) -> None:
        for key, rec in flat.items():
            self.set_field(key, rec["value"], rec.get("last_updated"))

    def profile_initialized(self) -> bool:
        return bool(self._data.get("meta", {}).get("profile_initialized", False))

    def mark_profile_initialized(self) -> None:
        self._data["meta"]["profile_initialized"] = True


class WorkingMemory:
    """短期工作记忆：仅存当前任务，不持久化。"""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.data: dict[str, Any] = {
            "task_id": None,
            "intent": None,
            "spec": None,
            "turns": 0,
            "details": {},
            "temp": {},
        }

    def start(self, task_id: str, intent: Any) -> None:
        self.reset()
        self.data["task_id"] = task_id
        self.data["intent"] = intent

    def set_spec(self, spec: Any) -> None:
        self.data["spec"] = spec


class EpisodicMemory:
    """情景记忆库：任务快照 + 语义相似检索（规格 4.2）。"""

    FILE = "episodic_memory.json"

    def __init__(self, storage_dir: str | Path) -> None:
        self.path = Path(storage_dir) / self.FILE
        self._data: dict[str, Any] = {"episodes": []}

    def load(self) -> None:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, episode: dict[str, Any]) -> str:
        episode.setdefault("task_id", uuid.uuid4().hex[:8])
        self._data["episodes"].append(episode)
        self.save()
        return episode["task_id"]

    def all_episodes(self) -> list[dict[str, Any]]:
        return list(self._data["episodes"])

    def update_episode(self, task_id: str, **fields: Any) -> bool:
        for ep in self._data["episodes"]:
            if ep.get("task_id") == task_id:
                ep.update(fields)
                self.save()
                return True
        return False

    # ---- 语义检索（规格 4.2） ------------------------------------------
    def retrieve_similar(
        self,
        goal: str = "",
        intent: str = "",
        domain: str = "",
        top_k: int = 3,
    ) -> list[tuple[dict[str, Any], float]]:
        """返回 top_k 个相似历史任务 (episode, score)。

        原型阶段用“领域匹配 + 意图匹配 + bigram 余弦”组合近似语义相似度：
        score = 0.4*领域 + 0.4*意图 + 0.2*文本余弦。
        接入真实 embedding（Chroma/FAISS）时替换本函数即可。
        """
        scored: list[tuple[dict[str, Any], float]] = []
        qvec = _tokenize(goal)
        for ep in self._data["episodes"]:
            if ep.get("status") not in ("completed", "paused"):
                continue
            d = 1.0 if (domain and ep.get("domain") == domain) else 0.0
            i = 1.0 if (intent and ep.get("intent_type") == intent) else 0.0
            t = _cosine(qvec, _tokenize(ep.get("task_goal", "")))
            score = round(0.4 * d + 0.4 * i + 0.2 * t, 4)
            scored.append((ep, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def similar(
        self,
        goal: str = "",
        intent: str = "",
        domain: str = "",
        threshold: float = 0.8,
    ) -> Optional[tuple[dict[str, Any], float]]:
        """相似度 > 阈值（规格 4.2 默认 0.8）视为同类任务。"""
        for ep, score in self.retrieve_similar(goal=goal, intent=intent, domain=domain, top_k=3):
            if score >= threshold:
                return ep, score
        return None

    # ---- 放弃点 / 断点续传（规格 4.4） ---------------------------------
    def find_unfinished(self) -> Optional[dict[str, Any]]:
        for ep in reversed(self._data["episodes"]):
            if ep.get("status") == "paused":
                return ep
        return None


class MemoryEvolutionSystem:
    """进化系统：画像同步、任务计数、校准时机。"""

    STATE_FILE = "evolution_state.json"
    CALIBRATION_TASKS = 5
    CALIBRATION_DAYS = 7

    def __init__(self, ltm: LongTermMemory, episodic: EpisodicMemory, storage_dir: str | Path) -> None:
        self.ltm = ltm
        self.episodic = episodic
        self.state_path = Path(storage_dir) / self.STATE_FILE
        self._state = {"tasks_since_calibration": 0, "last_calibration_ts": None}
        if self.state_path.exists():
            self._state.update(json.loads(self.state_path.read_text(encoding="utf-8")))

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_profile(self, profile: Any, mark_initialized: bool = False) -> None:
        self.ltm.sync_profile(profile.to_flat())
        if mark_initialized:
            self.ltm.mark_profile_initialized()
        self.ltm.save()

    def task_completed(self) -> None:
        self._state["tasks_since_calibration"] += 1
        self._save_state()

    def needs_calibration(self) -> bool:
        if self._state["tasks_since_calibration"] >= self.CALIBRATION_TASKS:
            return True
        last = self._state.get("last_calibration_ts")
        if not last:
            return False
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days >= self.CALIBRATION_DAYS
        except ValueError:
            return False

    def after_calibration(self) -> None:
        self._state["tasks_since_calibration"] = 0
        self._state["last_calibration_ts"] = _now()
        self._save_state()
