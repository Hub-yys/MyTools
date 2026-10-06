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

    → **修法：``_nth`` 为 0 时不加到键尾**。这样::

        旧记录（无 _nth）      → ``p|n|t|r``      ✓
        新的 _nth=0           → ``p|n|t|r``      ✓ 同一个键，正确去重
        新的 _nth=1（真孪生）  → ``p|n|t|r|1``    ✓ 不同的键，两条都留

    ⚠ **向后兼容是这里的关键**：老数据没有 ``_nth``，
    新逻辑必须把它和 ``_nth=0`` 认成同一条。

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
    #: ★ 同秒同名的"第几次" —— 十连里两个同名武器靠它区分
    #:
    #: ⚠ **0 不加到键尾**（见上面 bug ②）：老数据没这个字段，
    #: 加了就会和新的 ``_nth=0`` 对不上、把整份历史复制一遍。
    try:
        nth = int(record.get("_nth") or 0)
    except (TypeError, ValueError):
        nth = 0
    if nth > 0:
        return f"{pool}|{name}|{when}|{rid}|{nth}"
    return f"{pool}|{name}|{when}|{rid}"


def _seq_of(record: dict) -> int:
    """``_seq``（接口列表下标）—— 越小越新；拿不到就是 0。

    ⚠ 拿不到时返回 **0 而不是大数**：``all_records`` 靠**稳定排序**
    保住"没有 _seq 的老数据"的 dict 顺序，只要这个值**一致**就行。
    """
    try:
        return int((record or {}).get("_seq") or 0)
    except (TypeError, ValueError):
        return 0


def _identity_without_nth(record: dict) -> str:
    """身份（**不含** ``_nth``）—— 清理重复时按它分组。

    ⚠ 跟 :func:`record_key` 的区别：这里故意**丢掉** ``_nth``，
    这样"同一条的两个版本"（一个有 ``_nth`` 一个没有）会分到同一组。
    """
    if not isinstance(record, dict):
        return f"|junk|{record!r}"
    pool = str(record.get("pool_type") or record.get("cardPoolType") or "")
    name = str(record.get("name") or "")
    when = str(record.get("time") or "")
    rid = str(record.get("resourceId") or "")
    return f"{pool}|{name}|{when}|{rid}"


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
        seen: dict[tuple, int] = {}
        for seq, raw in enumerate(incoming):
            if not isinstance(raw, dict):
                continue
            record = dict(raw)
            record["pool_type"] = pool_type
            record["pool"] = pool_name
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

    def add_snapshot(self, snapshot: PullSnapshot) -> None:
        self.snapshots.insert(0, snapshot)      # 最新的在前
        del self.snapshots[MAX_SNAPSHOTS:]

    def all_records(self) -> list[dict]:
        """按时间**倒序**（最新在前）—— 和接口给的方向一致，方便直接喂 Pull。

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
        history = GachaHistory.from_dict(raw)

        #: ★ **自愈**：把"旧键 + 新键"并存造成的重复清掉（见
        #: :meth:`GachaHistory.dedupe_legacy_keys` 的说明）。
        #: ⚠ 只在真的删了东西时才回写 —— 免得每次读都写盘。
        removed = history.dedupe_legacy_keys()
        if removed:
            logger.info("抽卡历史里有 %d 条重复（旧版去重键的遗留），已清理",
                        removed)
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
