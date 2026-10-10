# -*- coding: utf-8 -*-
"""消息通知的**存储**（侧栏「消息」页的数据层）。

用户 2026-10-10 要求::

    "左侧边栏增加消息通知功能，用来储存最近发的通知，最多储存10条，
     每天自动清理，也可手动清理，每个任务完成/失败都要进行通知，
     声骸批量调频、声骸自动强化等工具完成/失败时也要通知"

## 四条规则（都在这个文件里实现，界面只管画）

1. **最多 10 条** —— 超了就从**最旧的**丢（新消息永远进得来）。
2. **每天自动清理** —— 只留**今天**的（用户口径："每天自动清理"）。
3. **可手动清理** —— :meth:`NotificationStore.clear`。
4. **未读数** —— 侧栏要显示"几条没看过"，:meth:`mark_all_read` 清零。

## 为什么"每天清理"用**日期比较**而不是"删 24 小时前的"

用户说的是"**每天**自动清理"，不是"保留 24 小时"。差别在观感上：

* 按日期：早上打开，昨天的一律没了 —— 一眼干净，"这是今天的消息"。
* 按 24 小时：昨晚 23:50 那条今早 9 点还在，混在今天的消息里，
  用户分不清哪条是新的。

所以判据是 ``stamp[:10] == 今天``（``stamp`` 是 ``YYYY-MM-DD HH:MM:SS``）。

## ⚠ 清理只在**读的时候**做，不挂定时器

``load()`` 里就顺手清一次 —— 程序启动会读、打开消息页也会读，
那两个时刻正好覆盖用户"会看到消息"的全部场景。
挂个午夜定时器当然也行，但那是**多一个常驻线程去解决一个已经解决的问题**
（本仓刚因为"测试里偷偷起后台线程"踩过坑，见 main_window 的自动更新那段）。

⚠ 本模块**纯逻辑**：不依赖 Qt，可以单测。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .registry import logger

#: 存储位置（和 ui_state.json / tasks.json 同一层）
DEFAULT_STORE_PATH = paths.user_data_dir() / "notifications.json"

#: 最多留几条（用户明确要求 10）
MAX_ITEMS = 10

#: 三种级别（决定图标和颜色）
LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_ERROR = "error"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


@dataclass
class Notice:
    """一条消息。"""

    #: 标题（一行说清是什么事，如「声骸自动强化 · 完成」）
    title: str = ""
    #: 正文（详情 / 统计，可为空）
    body: str = ""
    #: :data:`LEVEL_INFO` / :data:`LEVEL_SUCCESS` / :data:`LEVEL_ERROR`
    level: str = LEVEL_INFO
    #: 产生时间 ``YYYY-MM-DD HH:MM:SS``（也是"每天清理"的判据）
    stamp: str = field(default_factory=_now)
    #: 唯一 id（界面删除单条 / 测试定位用；不用时间戳是因为同一秒可能来两条）
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "title": str(self.title or ""),
            "body": str(self.body or ""),
            "level": self.level if self.level in _LEVELS else LEVEL_INFO,
            "stamp": str(self.stamp or ""),
            "uid": str(self.uid or ""),
        }

    @classmethod
    def from_dict(cls, raw) -> "Notice | None":
        """容错地从盘上读回来 —— 读不出来返回 ``None``（调用方丢掉它）。

        ⚠ **不猜**：字段类型不对就返回 ``None``，不硬转。
        一个坏条目不该让整个消息历史消失。
        """
        if not isinstance(raw, dict):
            return None
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            return None            #: 没标题的条目没有展示价值
        body = raw.get("body")
        stamp = raw.get("stamp")
        level = raw.get("level")
        return cls(
            title=title,
            body=body if isinstance(body, str) else "",
            level=level if level in _LEVELS else LEVEL_INFO,
            stamp=stamp if isinstance(stamp, str) else "",
            uid=str(raw.get("uid") or uuid.uuid4().hex[:12]),
        )

    @property
    def day(self) -> str:
        """这条消息属于哪一天（``YYYY-MM-DD``）；时间戳坏了返回空串。"""
        return self.stamp[:10] if len(self.stamp) >= 10 else ""

    def time_text(self) -> str:
        """给界面看的时间（``HH:MM``；不是今天的话带日期）。"""
        if len(self.stamp) < 16:
            return self.stamp or ""
        clock = self.stamp[11:16]
        return clock if self.day == _today() else f"{self.day[5:]} {clock}"


_LEVELS = (LEVEL_INFO, LEVEL_SUCCESS, LEVEL_ERROR)


class NotificationStore:
    """消息列表的读写 + 那四条规则。

    :param path: 存储文件；测试传临时路径就不碰用户真实的
        ``notifications.json``。
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH
        self._items: list[Notice] = []
        #: 已读到哪个 id（未读数靠它算 —— 比"每条一个已读标志"简单，
        #: 也比"存一个未读计数"可靠：计数会在清理/删单条时对不上）
        self._read_upto: str = ""
        self.load()

    # ------------------------------------------------------------ 磁盘
    def load(self) -> list[Notice]:
        """读盘 + **顺手做每日清理**（见模块文档：不挂定时器）。

        :return: 清理后的列表
        """
        self._items = []
        self._read_upto = ""
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("消息存储读不出来：%s（当作空的）", self.path)
                raw = None
            if isinstance(raw, dict):
                items = raw.get("items")
                if isinstance(items, list):
                    for entry in items:
                        notice = Notice.from_dict(entry)
                        if notice is not None:
                            self._items.append(notice)
                upto = raw.get("read_upto")
                self._read_upto = upto if isinstance(upto, str) else ""

        before = len(self._items)
        dropped = self._prune()
        if dropped:
            logger.info("消息自动清理：删掉 %d 条（跨天 %d，超上限 %d）",
                        dropped, dropped, dropped)
            self._save()
        elif before != len(self._items):        # pragma: no cover - 防呆
            self._save()
        return list(self._items)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({
                    "items": [n.to_dict() for n in self._items],
                    "read_upto": self._read_upto,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            logger.warning("消息存储写不进去：%s", self.path, exc_info=True)

    # ------------------------------------------------------------ 规则
    def _prune(self) -> int:
        """裁到合法状态：**昨天的丢掉** + 只留最新 :data:`MAX_ITEMS` 条。

        列表按"新的在前"存（``add`` 时插到头部），所以超上限是从**尾部**丢。

        :return: 丢掉了几条
        """
        today = _today()
        before = len(self._items)

        #: ① 每天清理：只留今天的。没时间戳的保守留着（宁可多留也不误删）
        self._items = [n for n in self._items
                       if not n.day or n.day == today]
        #: ② 只留最新 MAX_ITEMS 条（新的在前 → 砍尾巴）
        if len(self._items) > MAX_ITEMS:
            self._items = self._items[:MAX_ITEMS]
        return before - len(self._items)

    def add(self, title: str, body: str = "", *,
            level: str = LEVEL_INFO) -> Notice:
        """记一条消息（**新的在最前**），并落盘。

        ⚠ 每次都重新 ``_prune`` —— 光是"限制 10 条"不够，
        跨天之后第一条新消息也得先把昨天的清掉（否则昨天的会占着名额）。
        """
        notice = Notice(title=str(title or "").strip() or "（无标题）",
                        body=str(body or ""),
                        level=level if level in _LEVELS else LEVEL_INFO)
        self._items.insert(0, notice)
        self._prune()
        self._save()
        return notice

    def clear(self) -> int:
        """手动清理：全清掉。返回删了几条。

        ⚠ 手动清理**也清掉未读**（``_read_upto``）——
        不清的话侧栏会顶着一个"3 条未读"的角标却一条都点不出来。
        """
        n = len(self._items)
        self._items = []
        self._read_upto = ""
        self._save()
        return n

    def remove(self, uid: str) -> bool:
        """删掉某一条（界面上的单条删除）。"""
        for i, n in enumerate(self._items):
            if n.uid == uid:
                del self._items[i]
                self._save()
                return True
        return False

    # ------------------------------------------------------------ 读接口
    def items(self) -> list[Notice]:
        """当前所有消息（新的在前）。**会先做一次每日清理**。"""
        self._prune()
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def unread_count(self) -> int:
        """未读数（侧栏角标用）。

        ⚠ 用的是"已读到哪个 id"而不是下标：下标会在**插入新消息**时整体
        后移，于是"已读 3 条"会突然变成"还有 1 条未读"（假未读）。
        id 不受插入影响。
        """
        if not self._read_upto:
            return len(self._items)
        for i, n in enumerate(self._items):
            if n.uid == self._read_upto:
                return i              #: 它前面那些都是之后新增的
        #: 那条"已读标记"自己已经被清理掉了（跨天 / 超上限）→ 全算未读
        return len(self._items)

    def mark_all_read(self) -> None:
        """全部标为已读（页面被打开时调）。"""
        self._read_upto = self._items[0].uid if self._items else ""
        self._save()
