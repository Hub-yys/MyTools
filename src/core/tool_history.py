# -*- coding: utf-8 -*-
"""通用的「工具运行历史」本地存储（声骸自动强化 / 以后别的工具共用）。

## 用户 2026-10-28

> 结果报告 … 也加上历史记录

## 为什么不复用 4C 那个 history.py

``auto_combat/history.py`` 的字段是固定的（battles / echoes / locked /
team / echo），声骸强化要存的是完全不同的东西（判定数 / 保留 / 弃置 /
满属性 / 弃置原因分布）。

所以这里做成**通用的键值记录**：:

    RunRecord(
        started_at=...,  ended_at=...,  duration=...,
        extra={"checked": 120, "kept": 8, "dropped": 112, "perfect": 2},
    )

``extra`` 里的字段由各工具自己定义，界面自己渲染。
这样以后「声骸批量调频」「扫荡残像聚落」想加历史都能直接复用。

## 存哪

``paths.user_data_dir() / "<namespace>_history.json"``

每个工具一个文件，互不干扰。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 每个工具最多留多少条（一条 ≈ 200 字节，1000 条 200KB 可接受）
MAX_RECORDS = 1000

#: 存盘格式版本
FORMAT_VERSION = 1


@dataclass(frozen=True)
class ToolRunRecord:
    """一次「运行 → 停止」的统计快照（字段由工具自定义）。"""

    started_at: float = 0.0
    ended_at: float = 0.0
    duration: float = 0.0
    #: 工具自定义的统计（int / str / list / dict 都行，要能 json 序列化）
    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------ 展示
    @property
    def when_text(self) -> str:
        """``10-28 14:30``。"""
        if not self.started_at:
            return "—"
        try:
            return datetime.fromtimestamp(self.started_at).strftime("%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return "—"

    @property
    def duration_text(self) -> str:
        sec = max(0, int(round(self.duration)))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def get(self, key: str, default=0):
        return (self.extra or {}).get(key, default)

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "started_at": round(float(self.started_at), 3),
            "ended_at": round(float(self.ended_at), 3),
            "duration": round(float(self.duration), 3),
            "extra": _jsonable(self.extra or {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolRunRecord":
        def _f(key: str) -> float:
            try:
                return float(data.get(key, 0.0))
            except (TypeError, ValueError):
                return 0.0

        extra = data.get("extra")
        return cls(
            started_at=_f("started_at"),
            ended_at=_f("ended_at"),
            duration=_f("duration"),
            extra=extra if isinstance(extra, dict) else {},
        )


def _jsonable(value):
    """把 extra 里的值转成能 json 存的形式（坏值不抛异常）。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class ToolHistoryStore:
    """某个工具的历史文件读写。**异常全吞** —— 历史坏了不能影响主功能。"""

    def __init__(self, namespace: str, path: Path | None = None):
        self.namespace = str(namespace or "tool")
        self.path = (Path(path) if path is not None
                     else paths.user_data_dir()
                     / f"{self.namespace}_history.json")
        self._records: list[ToolRunRecord] = []
        self._loaded = False

    # ------------------------------------------------------------ 读写
    def load(self) -> list[ToolRunRecord]:
        if self._loaded:
            return list(self._records)
        self._loaded = True
        try:
            if not self.path.exists():
                self._records = []
                return []
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 历史读取失败（按空处理）：%s",
                           self.namespace, exc)
            self._records = []
            return []

        raw = data.get("records") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            self._records = []
            return []

        out: list[ToolRunRecord] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    out.append(ToolRunRecord.from_dict(item))
                except Exception:  # noqa: BLE001 - 单条坏掉跳过
                    continue
        out.sort(key=lambda r: r.started_at, reverse=True)
        self._records = out[:MAX_RECORDS]
        return list(self._records)

    def add(self, record: ToolRunRecord | None) -> bool:
        if record is None:
            return False
        self.load()
        self._records.insert(0, record)
        del self._records[MAX_RECORDS:]
        self.save()
        return True

    def save(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": FORMAT_VERSION,
                "namespace": self.namespace,
                "records": [r.to_dict() for r in self._records],
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 历史存盘失败：%s", self.namespace, exc)
            return False

    def records(self, limit: int = 0) -> list[ToolRunRecord]:
        items = self.load()
        return items[:limit] if limit > 0 else items

    def clear(self) -> None:
        self._records = []
        self._loaded = True
        self.save()
