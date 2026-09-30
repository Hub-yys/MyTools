"""抽卡记录的**本地累积存储**（历史记录）。

## 为什么必须累积

库洛接口**只返回最近一段记录**（实测：角色池只给到 590 抽 / 约 3 周），
而玩家的真实抽数远不止 —— 鸣潮工坊能显示 4393 抽，是因为它**每次拉取
都存下来并合并**。

不累积的话，用户永远只能看到"最近这一段"，数字对不上、也没法回顾历史。

## 合并规则（★ 去重是核心）

一次拉取回来的记录**可能和已有的重叠**（接口给的是"最近 N 条"，
窗口滑动必然重叠）。所以按**记录身份**去重，而不是按数量或时间戳整体替换：

    身份 = (卡池类型, 物品名, 时间, resourceId)

* 用 ``(pool_type, name, time)`` 做键 —— 同一秒十连出两个同名物品是可能的，
  所以**再加 resourceId**（接口给了）；没有 resourceId 时退回前三项。
* ⚠ **不能用"时间 > 上次最新时间"来过滤**：十连里 10 条时间戳完全相同，
  用严格大于会把同一次十连的后半截丢掉（实测踩过同类问题）。

## 存什么

``gacha_history.json``（用户数据目录）::

    {
      "version": 1,
      "records": {"<身份键>": {卡池/名字/星级/类型/时间}},
      "snapshots": [ {"at": "2026-09-30 21:40", "total": 850, "five": 20} ]
    }

``snapshots`` 是**每次拉取的时间点**（用户要"按时间保存为历史记录"），
用来在界面上列出"哪次拉的时候是什么样"。

**纯逻辑**：不依赖 Qt（见 ``tests/test_gacha_store.py``）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 默认存放位置（用户数据目录）
DEFAULT_STORE_PATH = paths.user_data_dir() / "gacha_history.json"

#: 存盘格式版本
FORMAT_VERSION = 1

#: 最多保留多少个"拉取时间点"快照 —— 够回看，又不至于把文件撑大
MAX_SNAPSHOTS = 200


def record_key(record: dict) -> str:
    """一条记录的身份键（去重靠它）。

    ``(卡池, 物品名, 时间, resourceId)`` —— **带上 resourceId**：
    同一秒十连出两个同名物品时，前三个字段会撞车，光靠它们会把其中一条丢掉。

    ⚠ 传进来不是 dict（``None`` / 字符串）时不抛异常 —— 这条被
    ``tests/test_gacha_store.py`` 钉着。去重是**批量**跑的，为一条脏数据
    把整次合并搞崩不值得。
    """
    if not isinstance(record, dict):
        return f"|junk|{record!r}"
    pool = str(record.get("pool_type") or record.get("cardPoolType") or "")
    name = str(record.get("name") or "")
    when = str(record.get("time") or "")
    rid = str(record.get("resourceId") or "")
    return f"{pool}|{name}|{when}|{rid}"


@dataclass
class PullSnapshot:
    """一次拉取的时间点摘要（界面上列历史用）。"""

    at: str = ""
    total: int = 0
    five: int = 0
    #: 这次**新增**了多少条（合并去重后）
    added: int = 0

    def to_dict(self) -> dict:
        return {"at": self.at, "total": self.total,
                "five": self.five, "added": self.added}

    @classmethod
    def from_dict(cls, data: dict) -> "PullSnapshot":
        data = data if isinstance(data, dict) else {}
        return cls(
            at=str(data.get("at") or ""),
            total=_int(data.get("total")),
            five=_int(data.get("five")),
            added=_int(data.get("added")),
        )

    def describe(self) -> str:
        """界面上那一行，例如 ``2026-09-30 21:40 · 共 850 抽 / 20 金（新增 12）``。"""
        text = f"{self.at} · 共 {self.total} 抽 / {self.five} 金"
        if self.added:
            text += f"（新增 {self.added}）"
        return text


@dataclass
class GachaHistory:
    """累积的全部记录 + 拉取时间点。"""

    #: 身份键 → 记录本身（原始字段，够重建 Pull）
    records: dict[str, dict] = field(default_factory=dict)
    #: 拉取时间点（最新的在前）
    snapshots: list[PullSnapshot] = field(default_factory=list)

    def merge(self, incoming: list[dict], *, pool_type: str,
              pool_name: str, at: str = "") -> int:
        """把一次拉取的结果并进来，返回**新增**条数。

        ``incoming`` 是接口原始记录；这里统一补上 ``pool_type`` / ``pool``
        两个字段（接口给的是中文池名，历史里要留稳定的类型编号）。
        """
        stamp = at or _now()
        added = 0
        for raw in incoming:
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            record["pool_type"] = pool_type
            record["pool"] = pool_name
            key = record_key(record)
            if key in self.records:
                continue
            record.setdefault("_first_seen", stamp)
            self.records[key] = record
            added += 1
        return added

    def add_snapshot(self, snapshot: PullSnapshot) -> None:
        self.snapshots.insert(0, snapshot)      # 最新的在前
        del self.snapshots[MAX_SNAPSHOTS:]

    def all_records(self) -> list[dict]:
        """按时间**倒序**（最新在前）—— 和接口给的方向一致，方便直接喂 Pull。"""
        return sorted(self.records.values(),
                      key=lambda r: str(r.get("time") or ""), reverse=True)

    def __len__(self) -> int:
        return len(self.records)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        return {
            "version": FORMAT_VERSION,
            "records": self.records,
            "snapshots": [s.to_dict() for s in self.snapshots],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GachaHistory":
        data = data if isinstance(data, dict) else {}
        records = data.get("records")
        snaps = data.get("snapshots")
        return cls(
            records={str(k): v for k, v in records.items()
                     if isinstance(v, dict)} if isinstance(records, dict) else {},
            snapshots=[PullSnapshot.from_dict(s) for s in snaps]
            if isinstance(snaps, list) else [],
        )


class GachaHistoryStore:
    """历史记录的本地 JSON 读写。

    读不出来 / 写不进去都**不让功能不可用**（和 ``tool_settings`` 一个态度）：
    历史是锦上添花，坏了也不该把工具页搞崩。
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path is not None else None

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else DEFAULT_STORE_PATH

    def load(self) -> GachaHistory:
        path = self.path
        if not path.exists():
            return GachaHistory()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("抽卡历史读不出来（%s）：%s —— 当作空的", path, exc)
            return GachaHistory()
        if not isinstance(raw, dict):
            return GachaHistory()
        return GachaHistory.from_dict(raw)

    def save(self, history: GachaHistory) -> None:
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(history.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            tmp.replace(path)          # 原子替换：写一半断电也不会毁掉旧文件
        except OSError as exc:
            logger.warning("抽卡历史写不进去（%s）：%s", path, exc)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
