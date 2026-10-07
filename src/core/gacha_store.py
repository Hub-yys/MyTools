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
FORMAT_VERSION = 2

#: ★★★ 多账号：老数据（没有 ``playerId``）归到哪个账号名下
#:
#: ## 背景（用户 2026-10-06："我要是换个账户了呢"）
#:
#: 原来身份键只有 ``(池子, 物品, 时间, resourceId)`` —— **没有账号**。
#: 后果：
#:
#: * 换账号后**旧记录不会清掉** → 两个号的抽卡**混在一起统计**；
#: * A / B 两号有**一样的抽卡**（同池同物品同秒）→ 被去重成一条，**少算**。
#:
#: 用户选了「方案 A：按账号分开存」——
#: ``playerId`` 进身份键，换号自动切到那个号的数据，
#: 切回来还能看到旧号历史。
#:
#: ## ⚠⚠ 老数据怎么办
#:
#: 已经存下的那些**没有 ``playerId``**。这里用 ``__legacy__`` 当它们的
#: 账号名 —— **不猜**成"当前账号"（那会把老数据错误地认领给新号）。
#:
#: 首次用新版本拉取时 :meth:`GachaHistory.claim_legacy` 会把老数据
#: **认领给当前账号** —— 但只在"这个账号还没有任何自己的数据"时做一次。
_LEGACY_PLAYER = "__legacy__"


def normalize_player(player_id: str) -> str:
    """统一账号标识（去空白；空的就是 :data:`_LEGACY_PLAYER`）。

    ⚠ 空值**不能**当成"当前账号" —— 老数据没有这个字段，
    当成当前账号会把别的号的数据错误认领过来。
    """
    text = str(player_id or "").strip()
    return text or _LEGACY_PLAYER

#: 最多保留多少个"拉取时间点"快照 —— 够回看，又不至于把文件撑大
MAX_SNAPSHOTS = 200


def record_key(record: dict) -> str:
    """一条记录的身份键（去重靠它）。

    ## ⚠⚠ 这里修过两个 bug —— 第二个是我修第一个时引入的

    ### bug ①（2026-10-05 用户报"统计不准"）：**吞记录**

    原来的键是 ``(池子, 物品名, 时间, resourceId)`` —— **没有"第几次"**。
    十连是**同一秒**入账的，一抽里出两个**同名同 id** 的 3★ 武器
    （实测「源能长刃·测壹」一抽出现两次）→ 键完全相同 →
    后面那条被当成重复**丢掉**。

    实测后果::

        每秒条数:  6 条×6 秒  7 条×16 秒  8 条×35 秒  9 条×19 秒  10 条×3 秒
                   ↑ 十连该是 10 条 → 丢了约 161 条
        工具显示 629 抽，实际 **790** —— 每段抽数都偏小

    ### bug ②（2026-10-05 当晚用户又报"越来越不对"）：**复制记录**

    修 ① 时我给键尾加了 ``_nth``。但**旧记录没有这个字段**，
    ``str(None or "")`` 是空串 → 旧键尾 ``|``、新键尾 ``|0`` →
    **两个键不一样** → 同一条被当成两条存进去::

        旧的 629 条 + 新的 790 条 = **1419 条**（库里真被翻了一倍）

    → 修法：``_nth`` 为 0 时**不加到键尾**，让老数据和新数据对上。

    ### bug ③（2026-10-06 用户问"换个账户了呢"）：**不区分账号**

    键里没有账号 → 换号后两个号的记录**混在一起**，而且两个号
    **相同的抽卡**（同池同物品同秒）会互相吞掉、**少算**。

    → 修法：键**最前面**加 ``playerId``（见 :func:`normalize_player`）。

    ## 最终形态

    ::

        <账号>|<池子>|<物品>|<时间>|<resourceId>[|<第几次>]

    ⚠ ``_nth`` 为 0 时**不加**最后那一段（向后兼容，见 bug ②）。

    ⚠ 传进来不是 dict（``None`` / 字符串）时不抛异常 —— 这条被
    ``tests/test_gacha_store.py`` 钉着。去重是**批量**跑的，为一条脏数据
    把整次合并搞崩不值得。
    """
    if not isinstance(record, dict):
        return f"|junk|{record!r}"
    who = normalize_player(record.get("playerId"))
    pool = str(record.get("pool_type") or record.get("cardPoolType") or "")
    name = str(record.get("name") or "")
    when = str(record.get("time") or "")
    rid = str(record.get("resourceId") or "")
    #: ★ 同秒同名的"第几次" —— 十连里两个同名武器靠它区分
    #:
    #: ⚠ **0 不加到键尾**（见 bug ②）：老数据没这个字段，
    #: 加了就会和新的 ``_nth=0`` 对不上、把整份历史复制一遍。
    try:
        nth = int(record.get("_nth") or 0)
    except (TypeError, ValueError):
        nth = 0
    if nth > 0:
        return f"{who}|{pool}|{name}|{when}|{rid}|{nth}"
    return f"{who}|{pool}|{name}|{when}|{rid}"


def _seq_of(record: dict) -> int:
    """``_seq``（接口列表下标）—— 越小越新；拿不到就是 0。

    ⚠ 拿不到时返回 **0 而不是大数**：``all_records`` 靠**稳定排序**
    保住"没有 _seq 的老数据"的 dict 顺序，只要这个值**一致**就行。
    """
    try:
        return int((record or {}).get("_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _occurrence(record: dict, seen: dict[tuple, int]) -> int:
    """这条记录在**本次拉取**里是"同秒同名"的第几次（从 0 开始）。

    ``seen`` 是本次拉取的计数器（键 = ``(时间, 名字, resourceId)``）。

    ⚠ 这个计数**只在本次拉取内有效** —— 它用来在同一次返回里
    区分"同一秒抽到的两个同名东西"。跨批次比对时，同一个东西
    在两次拉取里算出的序号**是一样的**（都是从 0 数起），
    所以键能稳定对上去重。
    """
    key = (str(record.get("time") or ""),
           str(record.get("name") or ""),
           str(record.get("resourceId") or ""))
    n = seen.get(key, 0)
    seen[key] = n + 1
    return n


@dataclass
class PullSnapshot:
    """一次拉取的时间点摘要（界面上列历史用）。"""

    at: str = ""
    total: int = 0
    five: int = 0
    #: 这次**新增**了多少条（合并去重后）
    added: int = 0
    #: ★ 这次拉的是**哪个账号**（多账号要分开列历史）
    player_id: str = ""

    def to_dict(self) -> dict:
        return {"at": self.at, "total": self.total,
                "five": self.five, "added": self.added,
                "playerId": self.player_id}

    @classmethod
    def from_dict(cls, data: dict) -> "PullSnapshot":
        data = data if isinstance(data, dict) else {}
        return cls(
            at=str(data.get("at") or ""),
            total=_int(data.get("total")),
            five=_int(data.get("five")),
            added=_int(data.get("added")),
            #: ⚠ 老快照没有这个字段 → 空串（= 未知账号）
            player_id=str(data.get("playerId") or ""),
        )

    def describe(self) -> str:
        """界面上那一行，例如 ``2026-09-30 21:40 · 共 850 抽 / 20 金（新增 12）``。"""
        text = f"{self.at} · 共 {self.total} 抽 / {self.five} 金"
        if self.added:
            text += f"（新增 {self.added}）"
        return text


def account_label(player_id: str) -> str:
    """把 ``playerId`` 显示成人看得懂的短名。

    ``playerId`` 是一串长数字（实测 9 位），界面上直接铺一长串不好看，
    所以只显示**后 6 位**，前面加省略号 —— 足够区分不同账号。

    ⚠ 空值 / ``__legacy__`` 要显示成「未知账号」而不是空白：
    用户得知道"这些数据不知道是谁的"。
    """
    who = str(player_id or "").strip()
    if not who or who == _LEGACY_PLAYER:
        return "未知账号"
    return f"…{who[-6:]}" if len(who) > 6 else who


@dataclass
class GachaHistory:
    """累积的全部记录 + 拉取时间点。"""

    #: 身份键 → 记录本身（原始字段，够重建 Pull）
    records: dict[str, dict] = field(default_factory=dict)
    #: 拉取时间点（最新的在前）
    snapshots: list[PullSnapshot] = field(default_factory=list)

    def merge(self, incoming: list[dict], *, pool_type: str,
              pool_name: str, at: str = "", player_id: str = "") -> int:
        """把一次拉取的结果并进来，返回**新增**条数。

        ``incoming`` 是接口原始记录；这里统一补上 ``pool_type`` / ``pool``
        两个字段（接口给的是中文池名，历史里要留稳定的类型编号）。

        ``player_id`` 是**哪个账号**的抽卡（见 :func:`record_key` 的 bug ③）——
        它进身份键，所以换号后两个号的数据**分开存、不会互相吞**。

        ## ⚠⚠ ``_nth`` 是修"吞记录"的关键（2026-10-05）

        十连是**同一秒**入账，一抽里可能出**两个同名同 id** 的 3★ 武器。
        原来的身份键没有"第几次"→ 第二条被当重复丢掉（用户报"统计不准"，
        实测少了约 161 条）。

        → 先扫一遍、给每条标上"同秒同名的第几次"（``_nth``），
        身份键里带上它，两条就都留得下来。

        ⚠ ``_nth`` **每次拉取都重算**（不能沿用旧的）：两次拉取的列表
        长度不同，但"同秒同名的第几次"都是从 0 数起，所以**稳定**——
        同一抽在两次拉取里算出的序号一致，去重仍然正确、不会重复入库。

        ## ⚠⚠ ``_nth`` 怎么存（这是修"复制记录"那个 bug 的关键）

        ``_nth=0`` 的**不写进 record** —— 让老的（无 ``_nth``）和新的
        （第一次出现）算出**同一个键**。否则整份历史会被复制一遍
        （实测 629 → 1419）。见 :func:`record_key` 的 bug ②。
        """
        stamp = at or _now()
        added = 0
        #: ★★★ 认领老数据（只在这个账号还没有自己的数据时做一次）
        #:
        #: 升级到多账号版本时，库里那几百条**都没有 ``playerId``**。
        #: 首次用新版本拉取的时候把它们认领给**当前这个账号**
        #: （合理推断：这些就是他自己之前抽的）。
        #: 见 :meth:`claim_legacy` 的说明。
        if player_id:
            self.claim_legacy(player_id)
        seen: dict[tuple, int] = {}
        for seq, raw in enumerate(incoming):
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            record["pool_type"] = pool_type
            record["pool"] = pool_name
            #: ★★ 账号 —— 身份键的第一段（用户 2026-10-06："换个账户了呢"）
            #:
            #: ⚠ ``player_id`` 为空时**不覆盖**记录里已有的值：
            #: 调用方偶尔拿不到（老链接 / 测试），但记录本身可能是
            #: 之前带着账号存进来的。
            who = str(player_id or "").strip()
            if who:
                record["playerId"] = who
            elif not record.get("playerId"):
                record.pop("playerId", None)
            #: ★★ ``_seq`` = 这条在**接口返回列表**里的下标
            #:
            #: ## ⚠⚠ 为什么必须有它（2026-10-05 第三次修这个统计）
            #:
            #: 接口把**一次十连的 10 条放在同一秒**，而且**列表是有序的**。
            #: 抽数的段边界（"这个金花了几抽"）**依赖同秒内的先后**。
            #:
            #: 但原来只存了 ``time``（精确到秒）→ 同秒的 10 条**顺序全丢**，
            #: 后来 ``sorted(time)`` 排出来是**任意顺序** → 五星在十连里的
            #: 位置错了 → 每段差 2~3 抽（实测对不上用户截图）。
            #:
            #: ``_seq`` 把接口的顺序留下来，排序时用它做**第二关键字**。
            record["_seq"] = seq
            #: 同秒同名的"第几次" —— 只用来算身份键（见 :func:`record_key`）
            nth = _occurrence(record, seen)
            if nth > 0:
                record["_nth"] = nth
            else:
                #: ⚠ 0 就**不写这个字段** —— 老数据没有它，
                #: 写了会算出不同的键、把历史复制一遍
                record.pop("_nth", None)
            key = record_key(record)
            if key in self.records:
                #: ★★★ 已存在也要**刷新 `_seq`** —— 用**这一批**的顺序。
                #:
                #: ## ⚠⚠ 这里踩过坑（2026-10-05）
                #:
                #: 第一版我写的是 ``if seq < 已有值`` —— **只在新值更小时更新**。
                #: 结果：第二批把同一抽排到了不同位置（接口每次顺序可能不同），
                #: 老值更小就**永远刷不掉** → 同秒顺序一直是第一批的（可能过时）。
                #:
                #: 实测表现：``test_same_second_order_survives_reinsertion``
                #: 报 ``'物品0' != '物品4'``。
                #:
                #: → 直接**用这次的值覆盖**：最新拉取到的顺序最可信。
                self.records[key]["_seq"] = seq
                continue
            record.setdefault("_first_seen", stamp)
            self.records[key] = record
            added += 1
        return added

    def repair(self) -> int:
        """把历史遗留问题一次修干净，返回**改动条数**（0 = 不用动）。

        ## 现在修三件事

        1. **重复**：旧版去重键留下的"同一条存两份"
           （见 :meth:`dedupe_legacy_keys`，实测 629 → 1419）；
        2. **身份键过期**：记录改了 ``playerId`` / ``_nth`` 之后，
           dict 的键还是旧的字符串，得按 :func:`record_key` 重算
           （见 :meth:`rekey_all`）；
        3. **未知账号的快照**：升级前的旧快照没有 ``player_id``
           （见 :meth:`drop_unknown_snapshots`，用户 2026-10-06：
           "未知账号的干掉"）。

        ⚠ 这个方法**会改内存**，落盘由调用方决定
        （``GachaHistoryStore.load_and_repair``）—— 这样测试能单独验逻辑，
        不会碰真实文件。
        """
        return (self.dedupe_legacy_keys() + self.rekey_all()
                + self.drop_unknown_snapshots())

    def rekey_all(self) -> int:
        """按当前字段**重算所有身份键**，返回需要挪位置的条数。

        ## 为什么需要它

        ``records`` 是 ``{身份键: 记录}``。但记录里的 ``playerId`` /
        ``_nth`` 变了之后（认领老数据、或者修 ``_nth`` 规则），
        **键还是旧的** —— 下次 ``merge`` 就会算出"新键不在库里"，
        把同一条**再存一份**。

        → 按 :func:`record_key` 重算一遍，键变了就把记录挪到新键下。

        ⚠ 两条撞到同一个新键时**只留一条**（它们本来就是同一条，
        只是键算出来重了）。
        """
        rebuilt: dict[str, dict] = {}
        moved = 0
        for old_key, rec in self.records.items():
            new_key = record_key(rec)
            if new_key != old_key:
                moved += 1
            if new_key in rebuilt:
                continue                    #: 撞车 → 丢掉多余的
            rebuilt[new_key] = rec
        if moved:
            self.records = rebuilt
        return moved

    def dedupe_legacy_keys(self) -> int:
        """★ 清理"旧键 + 新键"并存造成的重复，返回删掉的条数。

        ## 为什么需要它（2026-10-05 我修 bug 时又引入的）

        修"吞记录"时给身份键加了 ``_nth``，但**旧记录没这个字段** ——
        结果同一条在库里存了两份（实测 629 → **1419**，用户的五星数
        也从 18 变成 36）。

        新键规则（:func:`record_key`）已经让 ``_nth=0`` 和"没有 _nth"
        算出同一个键，但**已经存进去的重复不会自己消失** ——
        这个方法负责把它们合并掉。

        ## ⚠⚠ 做法：**按新规则重新算键**，同键的只留一条

        第一版我按"不含 ``_nth`` 的身份"分组、留 ``_first_seen`` 最早的 ——
        **删过头了**（790 条被删回 629）：因为"真孪生"（``_nth=1``）
        和"第一条"（``_nth=0``）的**身份是相同的**（只差 ``_nth``），
        分组时被塞进同一组，然后当成重复删掉了。

        → 正确做法：对每条**用新的 :func:`record_key` 重算键**，按新键归并。
        这样::

            老的（无 _nth）    → ``p|n|t|r``      ┐ 同键 → 只留一条
            新的 _nth=0        → ``p|n|t|r``      ┘
            新的 _nth=1        → ``p|n|t|r|1``    ← 不同键，**留下来**

        同键时优先留**带 ``_nth`` 的那条**：它来自"记录完整"的那一批
        （新拉的那次），而且字段更全。
        """
        rebuilt: dict[str, dict] = {}
        removed = 0
        for _old_key, rec in self.records.items():
            new_key = record_key(rec)
            if new_key not in rebuilt:
                rebuilt[new_key] = rec
                continue
            removed += 1
            #: 同键 → 留带 _nth 的那条（记录完整的那一批）
            if "_nth" in rec and "_nth" not in rebuilt[new_key]:
                rebuilt[new_key] = rec

        if removed:
            self.records = rebuilt
        return removed

    def drop_unknown_snapshots(self) -> int:
        """★★ 删掉「未知账号」的历史快照，返回删了几条。

        ## 用户 2026-10-06（截图圈出那三行）

            "未知账号的干掉"

        ## 这些是什么

        它们是**升级到多账号版本之前**留下的快照 —— 那时 ``PullSnapshot``
        还没有 ``player_id`` 字段，读回来就是空串，界面显示成「未知账号」。

        ⚠ 其中还夹着**错误数据**：``total=2018`` 那条是我修"复制记录"
        bug 之前拍的快照（当时库里真有 2018 条重复记录）。留着会让用户
        以为"我曾经抽了 2018 抽"。

        ## ⚠ 为什么不"猜"它属于当前账号

        猜的话就是把 2018 那个错数字认领给用户 —— 比显示「未知账号」更糟。
        **直接删掉**：记录（``records``）本身一条不少，只是少了几行
        "某次拉取时累计到多少"的流水。
        """
        before = len(self.snapshots)
        self.snapshots = [s for s in self.snapshots if s.player_id]
        return before - len(self.snapshots)

    # ---------------------------------------------------------------- 多账号
    def players(self) -> list[str]:
        """库里有哪些账号（按记录数**从多到少**）。

        ⚠ :data:`_LEGACY_PLAYER`（老数据）也算一个 ——
        界面上要能看见它、并让用户决定认领给谁。
        """
        counts: dict[str, int] = {}
        for rec in self.records.values():
            who = normalize_player(rec.get("playerId"))
            counts[who] = counts.get(who, 0) + 1
        return sorted(counts, key=lambda w: (-counts[w], w))

    def player_count(self, player_id: str) -> int:
        """某个账号有多少条记录。"""
        who = normalize_player(player_id)
        return sum(1 for r in self.records.values()
                   if normalize_player(r.get("playerId")) == who)

    def claim_legacy(self, player_id: str) -> int:
        """把**老数据**（没有账号的）认领给 ``player_id``，返回认领条数。

        ## ⚠⚠ 只在这个账号"还没有自己的数据"时才认领

        否则会把老数据硬塞给一个已经有很多记录的号（可能是误操作）。

        ## 为什么要认领而不是"直接留着不分账号"

        用户升级到多账号版本时，库里那几百条记录**都没有 ``playerId``**。
        如果一直挂在 ``__legacy__`` 名下，界面就得同时显示"未知账号"
        和真账号两份数据 —— 很怪。

        → 首次拉取时把这些老数据认领给**当前正在拉的账号**（合理推断：
        这些就是他自己抽的），之后就是干净的单账号数据。
        """
        who = str(player_id or "").strip()
        if not who:
            return 0
        #: 这个账号已经有自己的数据 → 不认领（避免把别人的塞过来）
        if self.player_count(who):
            return 0

        claimed = 0
        for rec in self.records.values():
            if rec.get("playerId"):
                continue
            rec["playerId"] = who
            claimed += 1
        if claimed:
            #: ⚠ 认领改了 ``playerId`` → **身份键必须重算**
            #: （键的第一段就是账号）。不重算的话下次 merge 会算出
            #: "新键不在库里"，把同一条**再存一份** —— 就是我修过的
            #: "复制记录"那个 bug 的翻版。
            self.rekey_all()
        return claimed

    def add_snapshot(self, snapshot: PullSnapshot) -> None:
        self.snapshots.insert(0, snapshot)      # 最新的在前
        del self.snapshots[MAX_SNAPSHOTS:]

    def all_records(self, player_id: str = "") -> list[dict]:
        """按时间**倒序**（最新在前）—— 和接口给的方向一致，方便直接喂 Pull。

        ``player_id`` 给了就**只返回那个账号的**（多账号隔离，见
        :func:`record_key` 的 bug ③）；不给就返回全部（含"未知账号"）。

        ## ⚠⚠ 同一秒内必须保住**接口原顺序**（2026-10-05 修了三轮）

        接口把**一次十连的 10 条放在同一秒**，且**列表有序**。
        抽数的段边界（"这个金花了几抽"）依赖**同秒内的先后**。

        只按 ``time`` 排的话，同一秒的 10 条变成**任意顺序** →
        五星在十连里的位置错 → 每段差 2~3 抽。

        ## 实测三种排法（拿用户游戏截图当真值对照）

        ::

            真值      50  25  24  28  71  14  43  21 ...
            A 现状    50  15  36  12  69  26  37  19 ...  差 90
            B 稳定    50  23  26  25  71  17  43  21 ...  差 **14**
            C 反转    50  17  34  15  69  23  37  19 ...  差 76

        **B 最好** —— 而且累计差回零（前面偏、后面补回来），
        说明**记录一条不缺**，只是同秒顺序还有局部偏差。

        ## 做法

        1. **有 ``_seq`` 就按它排**（重新拉过的数据，顺序最准）；
        2. **没有就靠 dict 的插入顺序** —— ``merge`` 是按接口顺序插的，
           Python 3.7+ 的 dict 保证插入顺序，所以这**就是接口原顺序**；
        3. 用 ``sorted`` 的**稳定性**：先给每条一个"原始下标"当兜底键，
           这样同秒内不会被重排。

        ⚠ 关键是**别用不带兜底的 ``sorted``** —— 那会把同秒的块重排掉。

        ## ⚠⚠ 兜底键别用 ``-idx``（我第一版就错在这）

        ``sorted(..., reverse=True)`` 会把**所有**键分量一起反转 ——
        包括那个兜底下标。用 ``-_idx`` 当兜底，反转后变成按 ``+idx`` 排，
        正好把插入顺序**倒过来**（实测又退回"方案 A"的差 90）。

        → 用一个**排他性**的兜底：有 ``_seq`` 就用它（越新 _seq 越小），
        没有就沿用 dict 顺序。做法是**先按 (time) 稳定排序，
        再在每次"同一秒的连续块"里保持原有先后** —— 不引入会被反转的量。
        """
        #: dict 插入顺序 = 接口返回顺序（merge 就是按那个顺序插的）
        raw = list(self.records.values())

        #: ★ 多账号：只看这个账号的（不给就全看）
        if player_id:
            who = normalize_player(player_id)
            raw = [r for r in raw
                   if normalize_player(r.get("playerId")) == who]

        #: 第一步：有 ``_seq`` 的按它升序（接口最新在前 → _seq 越小越新）。
        #: ``sorted`` 是**稳定**的，所以没有 _seq 的（老数据）保持
        #: dict 插入顺序不变。
        step1 = sorted(raw, key=_seq_of)

        #: 第二步：按时间倒序。**也是稳定排序** → 同一秒内保持 step1 的顺序
        #: （也就是"接口原顺序"或"按 _seq 排好的顺序"）。
        step1.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
        return step1

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
        """读历史 —— **纯读，绝不写盘**。

        ## ⚠⚠ 这里修过一个"读的时候偷偷写盘"的坑（2026-10-06）

        原来的 ``load()`` 里做了**自愈**：发现重复就 ``save()`` 一次。
        功能上没错，但副作用很隐蔽 —— 后果实测到了::

            我跑 tests/smoke_gui.py（它会真的建 GachaWidget）
            → GachaWidget 打开时 _render_from_history() → load()
            → 自愈触发 → **偷偷把用户的 data/gacha_history.json 改了**
            （用户的 1131 条老数据被写上了 playerId）

        用户看到的是"我没点过分析，数据怎么变了"。

        → **读就是读**：迁移/自愈挪到**写路径**（:meth:`merge` 之后由
        调用方 ``save``），那条路上用户本来就在改数据，不突兀。

        要"读顺便修一下"的话显式调 :meth:`load_and_repair`。
        """
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

    def load_and_repair(self) -> GachaHistory:
        """读 + **把历史遗留问题修掉并落盘**（会写）。

        ⚠ 只在**明确要改数据**的地方调（比如用户点了「分析」）。
        普通的读界面走 :meth:`load`，别用这个 —— 见那里的说明。
        """
        history = self.load()
        if history.repair():
            self.save(history)
        return history

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
