"""声骸强化的**运行报告**：本轮结果 + 所有任务的累计统计。

用户 2026-09-28 的批注（任务页截图）：

    增加本轮报告，统计本轮声骸符合条件锁定的、弃置的声骸数量，总结报告，
    统计所有任务的声骸符合条件锁定的、弃置的声骸数量

拆成两件事：

* **本轮报告** —— 刚刚跑完的那一轮流程，**每条流程**（每个工具步骤）各多少
  锁定 / 弃置，外加一个合计。只活在内存里（每次运行重新开始），
  它回答的是"我刚点的那下发生了什么"。
* **累计统计** —— **所有任务**（所有流程、所有轮次）加起来的锁定 / 弃置总数。
  这个**必须持久化**（用户明确要求重启不丢），落在用户数据目录的
  ``echo_run_stats.json``。

## 数字从哪来

锁定 = ok-ww 引擎 ``info["成功声骸数量"]``，弃置 = ``info["失败声骸数量"]``
（见 ``echo_enhance/tool.py`` 的 ``_snapshot_task_stats``）。
**不自己重算判定** —— 引擎报的就是真跑出来的结果。

⚠ 本模块**纯逻辑**：不依赖 Qt，可以单测（见 ``tests/test_run_report.py``）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .registry import logger

#: 默认存放位置：用户数据目录下的 echo_run_stats.json（和 tasks.json 同目录）
DEFAULT_STORE_PATH = paths.user_data_dir() / "echo_run_stats.json"


@dataclass
class FlowRunResult:
    """一条流程（一个工具步骤）跑完的结果。"""

    #: 流程名 / 步骤名 —— 报告里给人看的那一行
    name: str = ""
    #: 符合条件、被锁定的声骸数
    locked: int = 0
    #: 不符合条件、被弃置的声骸数
    dropped: int = 0
    #: 判定总数（引擎给的 checked，可能为 0）
    checked: int = 0
    #: 这一步有没有跑成功（失败时锁定/弃置照样留着，但报告要标出来）
    ok: bool = True
    #: 失败原因 / 跳过原因（``ok`` 为 False 时有意义）
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "locked": int(self.locked),
            "dropped": int(self.dropped),
            "checked": int(self.checked),
            "ok": bool(self.ok),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FlowRunResult":
        data = data if isinstance(data, dict) else {}
        return cls(
            name=str(data.get("name") or ""),
            locked=_int(data.get("locked")),
            dropped=_int(data.get("dropped")),
            checked=_int(data.get("checked")),
            ok=bool(data.get("ok", True)),
            note=str(data.get("note") or ""),
        )


@dataclass
class RoundReport:
    """**本轮**报告：这一轮跑过的每条流程 + 合计。

    一轮 = 用户点一次「运行」。同一轮里可能有好几个工具步骤（比如
    爱弥斯声骸筛选 → 声骸强化），每个步骤一条 :class:`FlowRunResult`。
    """

    #: 这一轮属于哪条流程（用户点的那条）
    flow_name: str = ""
    #: 开始 / 结束时间（给人看的字符串）
    started_at: str = ""
    finished_at: str = ""
    #: 每条工具步骤的结果（按执行顺序）
    items: list[FlowRunResult] = field(default_factory=list)
    #: 这一轮是不是正常跑完的（停止 / 出错时为 False）
    ok: bool = True
    #: 停止 / 出错的原因
    note: str = ""

    # ---------------------------------------------------------------- 汇总
    @property
    def locked(self) -> int:
        return sum(item.locked for item in self.items)

    @property
    def dropped(self) -> int:
        return sum(item.dropped for item in self.items)

    @property
    def checked(self) -> int:
        return sum(item.checked for item in self.items)

    def is_empty(self) -> bool:
        """这一轮什么都没统计到（没有强化类工具 / 都是跳过）。"""
        return not self.items

    def summary(self) -> str:
        """一行合计：``符合条件锁定 N · 弃置 M``。"""
        return f"符合条件锁定 {self.locked} · 弃置 {self.dropped}"

    def lines(self) -> list[str]:
        """给人看的逐条明细（每条流程一行）。"""
        rows: list[str] = []
        for item in self.items:
            text = f"{item.name}：锁定 {item.locked} · 弃置 {item.dropped}"
            if not item.ok:
                text += f"（{item.note or '未成功'}）"
            rows.append(text)
        return rows

    def to_dict(self) -> dict:
        return {
            "flow_name": self.flow_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": bool(self.ok),
            "note": self.note,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RoundReport":
        data = data if isinstance(data, dict) else {}
        items = data.get("items")
        return cls(
            flow_name=str(data.get("flow_name") or ""),
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
            ok=bool(data.get("ok", True)),
            note=str(data.get("note") or ""),
            items=[FlowRunResult.from_dict(x) for x in items]
            if isinstance(items, list) else [],
        )


@dataclass
class TotalStats:
    """**所有任务**的累计统计（跨轮次、跨流程，持久化）。"""

    locked: int = 0
    dropped: int = 0
    checked: int = 0
    #: 一共跑过多少轮（用来给报告一个"资历"）
    rounds: int = 0
    #: 最后一次跑完的时间
    updated_at: str = ""

    def add(self, report: RoundReport) -> None:
        """把一轮的结果累加进来。"""
        self.locked += report.locked
        self.dropped += report.dropped
        self.checked += report.checked
        self.rounds += 1
        self.updated_at = report.finished_at or _now()

    def reset(self) -> None:
        """清零 —— 界面上给一个「清零」入口时用。"""
        self.locked = 0
        self.dropped = 0
        self.checked = 0
        self.rounds = 0
        self.updated_at = ""

    def summary(self) -> str:
        return f"符合条件锁定 {self.locked} · 弃置 {self.dropped}"

    def to_dict(self) -> dict:
        return {
            "locked": int(self.locked),
            "dropped": int(self.dropped),
            "checked": int(self.checked),
            "rounds": int(self.rounds),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TotalStats":
        data = data if isinstance(data, dict) else {}
        return cls(
            locked=_int(data.get("locked")),
            dropped=_int(data.get("dropped")),
            checked=_int(data.get("checked")),
            rounds=_int(data.get("rounds")),
            updated_at=str(data.get("updated_at") or ""),
        )


class RunReportStore:
    """累计统计的本地 JSON 存储（读写都在这里，界面只管拿结果）。

    文件结构（``echo_run_stats.json``）::

        {"total": {"locked": 12, "dropped": 30, "checked": 42,
                   "rounds": 3, "updated_at": "2026-09-28 12:00:00"}}

    读不出来 / 写不进去都**不让功能不可用** —— 和 ``tool_settings`` 一个态度：
    报告是锦上添花，坏了也不该把任务页搞崩。
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path is not None else None

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else DEFAULT_STORE_PATH

    # ------------------------------------------------------------------ 读写
    def load(self) -> TotalStats:
        path = self.path
        if not path.exists():
            return TotalStats()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("累计统计读不出来（%s）：%s —— 当作从零开始", path, exc)
            return TotalStats()
        if not isinstance(raw, dict):
            return TotalStats()
        return TotalStats.from_dict(raw.get("total"))

    def save(self, stats: TotalStats) -> None:
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"total": stats.to_dict()}
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            # 写不下来不该让功能不可用
            logger.warning("累计统计写不进去（%s）：%s", path, exc)

    # ------------------------------------------------------------------ 组合
    def add_round(self, report: RoundReport) -> TotalStats:
        """累加一轮并落盘，返回累加后的总数。"""
        stats = self.load()
        stats.add(report)
        self.save(stats)
        return stats

    def reset(self) -> TotalStats:
        """清零并落盘。"""
        stats = TotalStats()
        self.save(stats)
        return stats


# ------------------------------------------------------------------ 从结果里取数


def flow_result_from_summary(name: str, summary: str, *,
                             ok: bool = True, note: str = "") -> FlowRunResult:
    """从工具 ``.summary()`` 的那行文本里抠出锁定 / 弃置数量。

    工具的报告走 :func:`~src.tools.game.echo_enhance.stats.format_result_report`，
    格式是 ``判定 N 个 · 符合条件 K · 弃置 D``（可能还带换行和"弃置原因"）。

    ⚠ 为什么要解析文本而不是拿结构化数据：``create_task_runner`` 的契约就是
    ``run() -> 有 summary() 的东西``，流程线程只看得见那行字。
    解析不到就记 0（**不猜**），并在 ``note`` 里说明 —— 宁可报告少一行，
    也不要编一个错的数字出来。

    ★ 用户口径（已确认）：**锁定 = 引擎的"成功声骸数量"，弃置 = "失败声骸数量"**。
    """
    from ..tools.game.echo_enhance.stats import parse_result_counts  # noqa: PLC0415

    counts = parse_result_counts(summary or "")
    return FlowRunResult(
        name=name,
        locked=counts.get("kept", 0),
        dropped=counts.get("dropped", 0),
        checked=counts.get("checked", 0),
        ok=ok,
        note=note,
    )


def _int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
