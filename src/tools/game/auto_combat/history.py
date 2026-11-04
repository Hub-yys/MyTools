# -*- coding: utf-8 -*-
"""4C 自动战斗的**历史记录**本地存储。

## 用户 2026-10-28

> 这里的使用说明删掉，改成历史记录

## 存什么

每次「启动 → 停止」产生一条记录::

    {
      "started_at": 1730000000.0,      # 开始时间戳
      "ended_at":   1730003600.0,      # 结束时间戳
      "duration":   3600.0,            # 秒
      "battles":    235,               # 战斗次数
      "echoes":     238,               # 声骸数量
      "locked":     12,                # 锁定声骸
      "team":       ["清宵", "达妮娅", "莫宁"],
      "echo":       "千傀重楼",         # 战斗声骸（可能为空）
    }

## 为什么不直接存 BattleReport

``BattleReport`` 是 ``frozen dataclass``，里面还有 ``TeamMember`` /
``EchoTarget`` / ``PickupTally`` 这些嵌套对象，JSON 存不了。
这里只在**落盘那一刻**拍平成基本类型（str/int/float/list），
读回来时再拼成 :class:`RunRecord`。

## 存哪

``paths.user_data_dir() / "auto_combat_history.json"``

跟 ``gacha_history.json`` 同一个目录，随用户数据走。

## 为什么不存日志路径

日志按日期轮转、31 天自动清理，存了也早晚失效。
用户在界面上要看的是「跑了多少」，不是「日志在哪」。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ....core import paths

logger = logging.getLogger(__name__)

#: 历史文件（用户数据目录）
DEFAULT_STORE_PATH = paths.user_data_dir() / "auto_combat_history.json"

#: 存盘格式版本 —— 以后字段变了靠它做迁移
FORMAT_VERSION = 1

#: 最多保留多少条（用户要"历史记录"，但没必要无限长；
#: 一条 ≈ 200 字节，1000 条也就 200KB）
MAX_RECORDS = 1000


@dataclass(frozen=True)
class RunRecord:
    """一次「启动 → 停止」的统计快照。"""

    started_at: float = 0.0
    ended_at: float = 0.0
    duration: float = 0.0          #: 秒
    battles: int = 0
    echoes: int = 0
    locked: int = 0
    team: tuple[str, ...] = field(default_factory=tuple)
    echo: str = ""

    # ------------------------------------------------------------ 展示
    @property
    def when_text(self) -> str:
        """``10-28 14:30`` —— 只到分钟，够看。"""
        if not self.started_at:
            return "—"
        try:
            return datetime.fromtimestamp(self.started_at).strftime("%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return "—"

    @property
    def duration_text(self) -> str:
        """``1:02:03`` / ``05:20``。"""
        sec = max(0, int(round(self.duration)))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def team_text(self) -> str:
        return " / ".join(self.team) if self.team else "—"

    @property
    def echo_text(self) -> str:
        return self.echo or "未识别"

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "started_at": round(float(self.started_at), 3),
            "ended_at": round(float(self.ended_at), 3),
            "duration": round(float(self.duration), 3),
            "battles": int(self.battles),
            "echoes": int(self.echoes),
            "locked": int(self.locked),
            "team": list(self.team),
            "echo": str(self.echo),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        """**容错到底** —— 历史文件坏了不能让它把界面搞崩。"""

        def _f(key: str, default: float = 0.0) -> float:
            try:
                return float(data.get(key, default))
            except (TypeError, ValueError):
                return default

        def _i(key: str) -> int:
            try:
                return int(data.get(key, 0))
            except (TypeError, ValueError):
                return 0

        raw_team = data.get("team")
        team: tuple[str, ...] = ()
        if isinstance(raw_team, (list, tuple)):
            team = tuple(str(x) for x in raw_team if x)

        return cls(
            started_at=_f("started_at"),
            ended_at=_f("ended_at"),
            duration=_f("duration"),
            battles=_i("battles"),
            echoes=_i("echoes"),
            locked=_i("locked"),
            team=team,
            echo=str(data.get("echo") or ""),
        )


def record_from_report(report, *, started_at: float = 0.0,
                       ended_at: float = 0.0) -> RunRecord | None:
    """把 :class:`report.BattleReport` 拍平成一条历史记录。

    返回 ``None`` 表示「这次没跑起来」（没有开始时间 / 没有报告），
    不该往历史里塞一条空记录。
    """
    if report is None or not started_at:
        return None
    team = tuple(getattr(m, "name", "") for m in (report.team or ())
                 if getattr(m, "name", ""))
    echo = getattr(report.echo, "name", "") if report.echo else ""
    pickups = getattr(report, "pickups", None)
    return RunRecord(
        started_at=float(started_at),
        ended_at=float(ended_at or started_at),
        duration=float(getattr(report, "seconds", 0.0)),
        battles=int(getattr(report, "battles", 0)),
        echoes=int(getattr(report, "echo_count", 0)),
        locked=int(getattr(pickups, "locked", 0)) if pickups else 0,
        team=team,
        echo=str(echo or ""),
    )


class HistoryStore:
    """历史文件的读写。**任何异常都不外抛** —— 历史只是附加功能。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH
        self._records: list[RunRecord] = []
        self._loaded = False

    # ------------------------------------------------------------ 读写
    def load(self) -> list[RunRecord]:
        """读盘（只读一次，之后走内存）。"""
        if self._loaded:
            return list(self._records)
        self._loaded = True
        try:
            if not self.path.exists():
                self._records = []
                return []
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - 文件坏了当空历史
            logger.warning("历史记录读取失败（按空处理）：%s", exc)
            self._records = []
            return []

        raw = data.get("records") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            self._records = []
            return []

        out: list[RunRecord] = []
        for item in raw:
            if isinstance(item, dict):
                try:
                    out.append(RunRecord.from_dict(item))
                except Exception:  # noqa: BLE001 - 单条坏掉跳过
                    continue
        #: 新的在前
        out.sort(key=lambda r: r.started_at, reverse=True)
        self._records = out[:MAX_RECORDS]
        return list(self._records)

    def add(self, record: RunRecord | None) -> bool:
        """追加一条（自动存盘）。返回是否真的加了。"""
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
                "records": [r.to_dict() for r in self._records],
            }
            #: 先写临时文件再替换 —— 断电/崩溃时不会留下半截 JSON
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception as exc:  # noqa: BLE001 - 存不动不该影响刷本
            logger.warning("历史记录存盘失败：%s", exc)
            return False

    def records(self, limit: int = 0) -> list[RunRecord]:
        """取最近的记录（``limit=0`` = 全部）。"""
        items = self.load()
        return items[:limit] if limit > 0 else items

    def clear(self) -> None:
        self._records = []
        self._loaded = True
        self.save()

    def total_text(self) -> str:
        """累计汇总，卡片底部显示用。"""
        items = self.load()
        if not items:
            return ""
        n = len(items)
        battles = sum(r.battles for r in items)
        echoes = sum(r.echoes for r in items)
        locked = sum(r.locked for r in items)
        seconds = sum(r.duration for r in items)
        h, rem = divmod(int(seconds), 3600)
        m = rem // 60
        return (f"共 {n} 次 · 战斗 {battles} 次 · 声骸 {echoes} 个 · "
                f"锁定 {locked} 个 · 累计 {h} 小时 {m} 分")
