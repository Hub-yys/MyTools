# -*- coding: utf-8 -*-
"""★★★ 抽卡历史的「按账号 + 时间」聚合逻辑（纯函数，好单测）。

## 用户 2026-10-28

> 这里历史记录按时间和账号维度统计，同一账号，不同时间内，
> 如果抽卡记录数据是一样的，则直接使用最新时间的，
> 如果不一样，则进行合并，时间显示格式为 xxxx年xx月

## 要解决什么

现在 ``reload_history`` 是**逐条列快照**：::

    · [.856011] 2026-10-14 21:07:33 · 共 960 抽 / 21 金（新增 960）
    · [.152489] 2026-10-06 20:09:03 · 共 1131 抽 / 24 金

问题：
  * 同一账号一个月里拉了 20 次 → 列 20 行，全是同一个号，噪音
  * 时间精确到秒，看不出"哪个月抽了多少"
  * 账号混着排，不是按账号分组

## 目标形态

按 **（账号, 年月）** 分组，每组一行::

    · [.856011] 2026年10月 · 960 抽 / 21 金
    · [.856011] 2026年09月 · 720 抽 / 15 金
    · [.152489] 2026年10月 · 1131 抽 / 24 金

## 组内怎么合并

用户原话：「同一账号，不同时间内，如果抽卡记录数据是一样的，
则直接使用最新时间的，如果不一样，则进行合并」

关键：快照里的 ``total`` / ``five`` **是累计值**（不是"这一次抽了多少"）。
所以同一账号在同一月里的多次快照::

    10-01  total=850   five=18
    10-14  total=960   five=21     ← 比上一条大 → 有新增

  * 数据**一样**（``total``/``five`` 都没变）→ 说明这几次是重复拉取，
    只保留**最新时间**那一条（时间用最新的，数字不变）
  * 数据**不一样** → 说明中间有新抽卡 → 合并成一条：
    数字取**最大值**（累计值取 max 才对），时间取**最新**

⚠ 为什么数字取 max 而不是 sum：
``total`` 是"这个号一共抽了多少"，累计值相加会变成天文数字。
同一个号同一月的两次快照 total=850 和 total=960，
真相是"到 960 为止"，不是 1810。

## 「不一样」但要合并不是相加 —— 那 merge 什么？

真正要 merge 的是**「这个月有没有抽过卡」这个事实**：
  * 全月只有 1 次快照 → 有数据
  * 多次快照数字都一样 → 只算 1 次（去重），取最新时间
  * 多次快照数字递增 → 也是 1 条，取最大值 + 最新时间

所以「合并」的结果就是：**每条 (账号, 年月) 只留一条**，
数字取该月最大，时间取该月最晚。这样既不会漏，也不会重复列。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MonthlyHistory:
    """一个账号在某个月的抽卡汇总（界面上列一行）。"""

    player_id: str = ""
    #: 年月，``"2026-10"`` 这种内部格式（排序用）
    year_month: str = ""
    total: int = 0
    five: int = 0
    #: 这个月里最新一次拉取的时间（原始字符串，可能是 ``2026-10-14 21:07:33``）
    latest_at: str = ""
    #: 这个月里有几次快照（诊断用，界面上不显示）
    snapshots: int = 0

    @property
    def month_text(self) -> str:
        """用户要的格式：``2026年10月``。"""
        return format_month(self.year_month)


def parse_year_month(at: str) -> str:
    """从 ``2026-10-14 21:07:33`` 抠出 ``2026-10``。解析不了返回空串。"""
    text = str(at or "").strip()
    if len(text) < 7:
        return ""
    head = text[:7]
    #: 必须是 ``YYYY-MM`` 形状
    if len(head) == 7 and head[4] == "-" and head[:4].isdigit() \
            and head[5:].isdigit():
        month = int(head[5:])
        if 1 <= month <= 12:
            return head
    return ""


def format_month(year_month: str) -> str:
    """``2026-10`` → ``2026年10月``。空的 → ``「未知月份」``。"""
    ym = str(year_month or "")
    if len(ym) == 7 and ym[4] == "-":
        try:
            return f"{ym[:4]}年{int(ym[5:])}月"
        except ValueError:
            pass
    return "未知月份"


def group_by_account_month(snapshots) -> list[MonthlyHistory]:
    """把快照列表按 (账号, 年月) 聚合，返回**账号优先、时间倒序**的列表。

    ## 排序规则

    1. **账号**按"最近有活动的在前" —— 用户在意的通常是刚抽的那个号
    2. 同一账号内**年月倒序** —— 最新的月份在最上面

    ## 丢弃什么

    * ``player_id`` 为空的（升级前的旧快照，用户明确要求"未知账号的干掉"）
    * 时间解析不出年月的（数据坏了，列出来也是噪音）
    """
    buckets: dict[tuple[str, str], MonthlyHistory] = {}

    for snap in snapshots or ():
        player = str(getattr(snap, "player_id", "") or "")
        if not player:
            continue
        at = str(getattr(snap, "at", "") or "")
        ym = parse_year_month(at)
        if not ym:
            continue
        total = int(getattr(snap, "total", 0) or 0)
        five = int(getattr(snap, "five", 0) or 0)
        key = (player, ym)

        current = buckets.get(key)
        if current is None:
            buckets[key] = MonthlyHistory(
                player_id=player, year_month=ym, total=total, five=five,
                latest_at=at, snapshots=1)
            continue

        #: 累计值取 max —— 见模块文档「为什么数字取 max 而不是 sum」
        buckets[key] = MonthlyHistory(
            player_id=player,
            year_month=ym,
            total=max(current.total, total),
            five=max(current.five, five),
            #: 时间取更晚的那次（字符串比较对 ``YYYY-MM-DD HH:MM:SS`` 成立）
            latest_at=at if at > current.latest_at else current.latest_at,
            snapshots=current.snapshots + 1,
        )

    #: 每个账号的"最近活动月份" —— 决定账号的排列顺序
    newest: dict[str, str] = {}
    for item in buckets.values():
        best = newest.get(item.player_id, "")
        if item.year_month > best:
            newest[item.player_id] = item.year_month

    #: ⚠ 必须**先按账号分组、再组内按月份倒序**。
    #:
    #: 一开始写的是 ``key=(账号最近月份, 该行月份)`` 一起倒序 —— 结果
    #: 两个账号的同月份会交叉排列::
    #:
    #:     [.856011] 2026年10月
    #:     [.152489] 2026年10月     ← 插在中间了
    #:     [.856011] 2026年9月
    #:
    #: 用户要的是「按账号维度」—— 一个号的所有月份要挨在一起。
    by_account: dict[str, list[MonthlyHistory]] = {}
    for item in buckets.values():
        by_account.setdefault(item.player_id, []).append(item)
    for items in by_account.values():
        items.sort(key=lambda x: x.year_month, reverse=True)

    #: 账号之间：最近有活动的在前
    ordered_players = sorted(
        by_account,
        key=lambda p: (newest.get(p, ""), p),
        reverse=True,
    )
    out: list[MonthlyHistory] = []
    for player in ordered_players:
        out.extend(by_account[player])
    return out


def is_same_data(a, b) -> bool:
    """两次快照的数字是不是完全一样（判断"要不要合并"用）。

    用户原话：「如果抽卡记录数据是一样的，则直接使用最新时间的」。
    """
    return (int(getattr(a, "total", 0) or 0) == int(getattr(b, "total", 0) or 0)
            and int(getattr(a, "five", 0) or 0)
            == int(getattr(b, "five", 0) or 0))
