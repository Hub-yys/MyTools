"""鸣潮「唤取记录」（抽卡记录）的拉取与统计。

用户在游戏里打开「唤取记录」页面并复制链接，粘贴到工具里，本模块解析出
参数 → 调库洛官方接口拉全部卡池 → 汇总成统计报告。

**纯逻辑**：不依赖 Qt，可以单测（见 ``tests/test_gacha.py``）。
网络请求单独抽成 :func:`fetch_pool`，测试里喂假响应。

## 接口（2026-09-30 实测可用）

    用户复制的链接形如：
    https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?
        svr_id=xxx&player_id=xxx&lang=zh-Hans&record_id=xxx&resources_id=xxx

    接口：
    POST https://gmserver-api.aki-game2.com/gacha/record/query?<原查询串>&cardPoolType=N
    Body(JSON): {serverId, playerId, languageCode, recordId, cardPoolId, cardPoolType}

    ⚠ 链接里的参数名和**接口要的名字不一样**，要做这层映射（见 :data:`PARAM_ALIASES`）：
    ``svr_id``→``serverId``、``player_id``→``playerId``、``lang``→``languageCode``、
    ``record_id``→``recordId``、``resources_id``→``cardPoolId``。

    返回：``{"code": 0, "message": "success", "data": [...]}``
    ``code == -1`` 通常表示"记录过期/没打开唤取记录页"，不是网络问题。

## 卡池

7 个池子（:data:`POOLS`），逐个请求（接口一次只返回一个池）。
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

#: 接口地址
QUERY_URL = "https://gmserver-api.aki-game2.com/gacha/record/query"

#: 用户复制出来的链接前缀（用来识别"这是不是唤取记录链接"）
LINK_HOST = "aki-gm-resources.aki-game.com"

#: 链接参数名 → 接口参数名。
#: ⚠ 两边名字**不一样**，这是最容易踩的坑：直接拿链接的参数名去请求会 query 不到。
PARAM_ALIASES = {
    "svr_id": "serverId",
    "player_id": "playerId",
    "lang": "languageCode",
    "record_id": "recordId",
    "resources_id": "cardPoolId",
}

#: 7 个卡池：``(cardPoolType, 显示名)``。
#: ⚠ 顺序即界面顺序（和游戏里「唤取记录」的页签顺序一致）。
POOLS: tuple[tuple[str, str], ...] = (
    ("1", "角色活动唤取"),
    ("2", "武器活动唤取"),
    ("3", "角色常驻唤取"),
    ("4", "武器常驻唤取"),
    ("5", "新手唤取"),
    ("6", "新手自选唤取"),
    ("7", "新手自选唤取（感恩定向唤取）"),
)

#: 五星保底抽数（角色池 / 武器池都是 80）
PITY_FIVE = 80
#: 四星保底（10 抽必出四星及以上）
PITY_FOUR = 10

#: **常驻**五星角色 —— 用来判定"歪没歪"（见 :func:`is_limited`）。
#: ⚠ 这份名单要维护：鸣潮的常驻池会随版本**扩充**（新角色进常驻后要从限定名单里
#: 拿掉）。来源是官方公告 + 攻略站核对（2026-09-30：常驻五虎）。
#: 不在这个名单里的五星角色 = 限定（UP）。
PERMANENT_CHARACTERS: frozenset[str] = frozenset({
    "维里奈", "凌阳", "鉴心", "安可", "卡卡罗",
})

#: **常驻**五星武器。同样要维护。
#: 常驻武器池的五把五星（每类武器各一把）。
PERMANENT_WEAPONS: frozenset[str] = frozenset({
    "千古洑流", "浩境粼光", "时和岁稔", "停驻之烟", "擎渊怒涛",
})


def is_limited(name: str, kind: str = "") -> bool:
    """这个五星是**限定（UP）**还是常驻/歪的？

    参考鸣潮工坊的判定：``!常驻角色名单.includes(name) && !常驻武器名单.includes(name)``
    —— 也就是"两边常驻名单都不在"才算限定。

    ⚠ 名字取不到（接口没给）时返回 **True**：宁可当限定（不影响"歪没歪"的
    分母），也不要当成"歪"从而把不歪率算低。

    ⚠ 这份名单**必须维护**。判断错的后果：不歪率、每 UP 均值全错，
    而且**不报错**（数字看着很正常）。
    """
    text = str(name or "").strip()
    if not text:
        return True
    return text not in PERMANENT_CHARACTERS and text not in PERMANENT_WEAPONS


#: 抽数条的配色分级：``(上限, 颜色)`` —— 抽数 **小于等于** 上限就用这个颜色。
#: 阈值参考鸣潮工坊：绿(欧) / 黄(正常) / 红(非)。
#: ⚠ 顺序必须从小到大，第一个命中为准。
SPAN_COLORS: tuple[tuple[int, str], ...] = (
    (40, "#4aa96c"),      # 绿：很欧
    (60, "#7fae72"),      # 浅绿
    (73, "#c8a86a"),      # 黄：正常
    (80, "#d9705a"),      # 橙红：接近/吃到保底
    (10 ** 9, "#c0392b"),  # 红：超过保底（异常，理论上不该出现）
)


def span_color(span: int) -> str:
    """抽数 → 颜色（抽数条用）。"""
    for limit, color in SPAN_COLORS:
        if span <= limit:
            return color
    return SPAN_COLORS[-1][1]

#: 欧非评价：``(平均出货抽数下限, 称号, 颜色)`` —— 从大到小匹配。
#: 阈值参考鸣潮工坊那套（平均抽数越低越欧）。
LUCK_TIERS: tuple[tuple[float, str, str], ...] = (
    (150.0, "至尊非酋王", "#d9705a"),
    (120.0, "究极大非酋", "#c9705a"),
    (100.0, "非洲人", "#c8a86a"),
    (90.0, "亚洲人", "#b9b06a"),
    (60.0, "欧洲人", "#7fae72"),
    (30.0, "欧皇", "#5fae90"),
    (0.0, "策划亲儿子", "#5ee7ff"),
)


class GachaError(Exception):
    """拉取失败。消息是**写给用户看的**，不加异常类名前缀。"""


# --------------------------------------------------------------------- 链接解析


def parse_link(link: str) -> dict[str, str]:
    """把用户复制的唤取记录链接解析成接口参数。

    返回 ``{serverId, playerId, languageCode, recordId, cardPoolId}``。

    校验三件事（缺一不可，缺了就报清楚哪件）：
    1. 是 ``aki-gm-resources.aki-game.com`` 的链接；
    2. 带 ``player_id``（没有它就无法定位账号）；
    3. 带 ``record_id`` / ``resources_id``（没有它们接口读不到记录）。

    ⚠ 用户很可能粘错（粘成整页 HTML、或者别的站的链接），所以这里要
    给出**指明问题**的错误，而不是笼统的"链接无效"。
    """
    text = str(link or "").strip()
    if not text:
        raise GachaError("请先粘贴唤取记录链接（游戏里打开「唤取记录」页面复制）")
    if LINK_HOST not in text:
        raise GachaError(
            "这不像唤取记录链接 —— 它应该以 "
            f"https://{LINK_HOST}/ 开头。\n"
            "请在游戏里打开「唤取记录」页面，点右上角复制链接。"
        )

    # 取 ? 之后的部分（链接是 #/record?xxx 形式，问号在 # 后面）
    query = text.split("?", 1)[1] if "?" in text else ""
    if not query:
        raise GachaError("链接里没有参数 —— 请重新在游戏里复制一次")
    # 去掉可能的锚点尾巴
    query = query.split("#", 1)[0]
    raw = urllib.parse.parse_qs(query)

    def get(name: str) -> str:
        values = raw.get(name) or []
        return str(values[0]).strip() if values else ""

    params = {
        target: get(source) for source, target in PARAM_ALIASES.items()
    }
    missing = [k for k in ("playerId", "recordId", "cardPoolId") if not params[k]]
    if missing:
        raise GachaError(
            "链接不完整（缺 "
            + "、".join(missing)
            + "）—— 请重新在游戏里复制一次完整链接"
        )
    params.setdefault("languageCode", "zh-Hans")
    if not params.get("languageCode"):
        params["languageCode"] = "zh-Hans"
    return params


# --------------------------------------------------------------------- 数据模型


@dataclass
class Pull:
    """一条唤取记录（一次单抽）。"""

    #: 物品名（角色名 / 武器名）
    name: str = ""
    #: 星级：5 / 4 / 3
    star: int = 3
    #: ``"角色"`` / ``"武器"``
    kind: str = ""
    #: 时间字符串（接口原样返回）
    time: str = ""
    #: 属于哪个卡池（:data:`POOLS` 的显示名）
    pool: str = ""

    @classmethod
    def from_record(cls, record: dict, pool: str) -> "Pull":
        """从接口记录构造一次抽卡。

        ## ★ 星级字段叫 ``qualityLevel``，不是 ``rankType``

        实测（2026-09-30，真实接口返回）::

            {"cardPoolType": "角色精准调谐", "resourceId": 21040043,
             "qualityLevel": 3, "resourceType": "武器",
             "name": "远行者臂铠·破障", "count": 1, "time": "..."}

        **星级是 ``qualityLevel``**（3/4/5）。我第一版按 ``rankType`` 取，
        取不到就一律当 3 星 —— 于是界面上"850 抽 0 个五星"，统计全废。

        ⚠ 教训：**别照抄别家的字段名**，要拿真实响应核对。
        下面同时保留几个别名兜底，万一接口以后改名，不至于又整体退化成 3 星。
        """
        record = record if isinstance(record, dict) else {}
        name = str(
            record.get("name")
            or record.get("resourceName")
            or record.get("itemName")
            or ""
        ).strip()
        star = 3
        for key in ("qualityLevel", "rankType", "star", "quality"):
            value = record.get(key)
            if value is None or value == "":
                continue
            try:
                star = int(value)
            except (TypeError, ValueError):
                continue
            break
        return cls(
            name=name,
            star=star,
            kind=str(record.get("resourceType") or "").strip(),
            time=str(record.get("time") or "").strip(),
            pool=pool,
        )


@dataclass
class FiveStar:
    """一个出过的五星（含"第几抽出、歪没歪"）。"""

    name: str = ""
    time: str = ""
    kind: str = ""
    #: 这次出五星用掉多少抽（**距离上一个五星**，含它自己）。界面显示用这个
    span: int = 0
    #: 距离上一次 **UP** 的抽数（含它自己）。大保底用：歪了会累加。
    #: 「每 UP 平均多少抽」按它算。
    cumulative: int = 0
    #: 是不是 UP（限定）。常驻池一律 True
    is_up: bool = True
    #: 这个五星出自限定池吗（常驻池不参与"歪没歪"统计）
    limited_pool: bool = False
    #: 限定池里：这次是 UP（没歪）还是歪了。常驻池恒 False
    is_50: bool = False

    @property
    def is_lost(self) -> bool:
        """歪了没（限定池里出了非 UP）。"""
        return self.limited_pool and not self.is_50


@dataclass
class PoolStats:
    """一个卡池的统计。"""

    name: str = ""
    #: 卡池类型（:data:`POOLS` 里的编号）。用来判断是不是限定池
    pool_type: str = ""
    #: 该池全部记录（按接口顺序，**最新在前**）
    pulls: list[Pull] = field(default_factory=list)

    # ---------------------------------------------------------------- 基础
    @property
    def total(self) -> int:
        return len(self.pulls)

    @property
    def five_stars(self) -> list[Pull]:
        return [p for p in self.pulls if p.star == 5]

    @property
    def four_stars(self) -> list[Pull]:
        return [p for p in self.pulls if p.star == 4]

    @property
    def five_count(self) -> int:
        return len(self.five_stars)

    def rate(self) -> float:
        """五星出货率（百分比）。没抽过返回 0。"""
        return (self.five_count / self.total * 100.0) if self.total else 0.0

    def average(self) -> float:
        """平均多少抽出一个五星。没出过返回 0。"""
        return (self.total / self.five_count) if self.five_count else 0.0

    def spans(self) -> list[int]:
        """每个五星**用掉多少抽**（含它自己），按**时间顺序**返回。

        ⚠ 前提：``self.pulls`` 是**最新在前**（接口就是这个顺序，见
        :meth:`Pull.from_record` 的使用处）。所以先 ``reversed`` 成时间正序
        再累计 —— 反过来算会把"第一金用了几抽"和"最后一金用了几抽"搞混。

        最后一个五星之后还没出的那些抽**不计入**（那是"当前垫抽"，
        见 :meth:`current_pity`）。
        """
        ordered = list(reversed(self.pulls))
        result: list[int] = []
        count = 0
        for pull in ordered:
            count += 1
            if pull.star == 5:
                result.append(count)
                count = 0
        return result

    def current_pity(self) -> int:
        """当前垫了多少抽还没出五星。

        ``self.pulls`` 是**最新在前**，所以从**头部**数到第一个五星为止 ——
        那一串就是"最后一次出金之后又抽的"。不用反转（反转了会从最早那头数，
        变成"第一金之前垫了多少"，完全不是一回事）。
        """
        count = 0
        for pull in self.pulls:
            if pull.star == 5:
                break
            count += 1
        return count

    def five_star_spans(self) -> list[tuple[Pull, int]]:
        """``[(五星, 它用掉多少抽), ...]``，按**时间顺序**。

        ⚠ 这里**不管大保底** —— 单纯是"两个五星之间隔了多少抽"。
        要判断"这个五星是不是 UP、这次算不算歪"，用 :meth:`fives_analysis`。
        """
        ordered = list(reversed(self.pulls))
        result: list[tuple[Pull, int]] = []
        count = 0
        for pull in ordered:
            count += 1
            if pull.star == 5:
                result.append((pull, count))
                count = 0
        return result

    # ------------------------------------------------ 大保底 / UP 分析
    @property
    def is_limited_pool(self) -> bool:
        """这个池子是不是**限定池**（角色活动 / 武器活动）。

        只有限定池才有"歪没歪""大保底"的概念；常驻池一律不算。
        """
        return self.pool_type in ("1", "2")

    def fives_analysis(self) -> list["FiveStar"]:
        """把五星逐个分析出来：抽数、是不是 UP、是否歪。

        ## 两个**不同**的计数（★ 这是最容易算错的地方）

        参考鸣潮工坊的实现，这里要同时维护两个计数：

        ==============  ==========================  ==========================
        字段            含义                        什么时候重置
        ==============  ==========================  ==========================
        ``span``        距离上一个**五星**           每个五星都重置
                        （界面上"这个金花了几抽"）
        ``cumulative``  距离上一次 **UP**            只有出 UP 才重置
                        （大保底用：歪了会累加）     歪了继续累加
        ==============  ==========================  ==========================

        ## 为什么必须分开

        我第一版只写了"距离上一个五星"，然后照抄参考实现的
        ``a = t ? 1 : a + 1``（只有 UP 才重置）——**把两个口径混成了一个**，
        结果界面上"第几抽"的数字会变成累计值（124 抽这种），明显不对。

        而"每 UP 平均多少抽"用的**是** ``cumulative`` 那个口径
        （大保底的抽数也算在这一次 UP 头上）。

        常驻池没有 UP 概念，``is_up`` 一律 True、``is_50`` 恒 False
        （不参与"歪没歪"统计）。
        """
        ordered = list(reversed(self.pulls))
        result: list[FiveStar] = []
        span = 0            # 距离上一个五星
        cumulative = 0      # 距离上一次 UP（大保底）
        for pull in ordered:
            span += 1
            cumulative += 1
            if pull.star != 5:
                continue
            limited = self.is_limited_pool
            is_up = True if not limited else is_limited(pull.name, pull.kind)
            result.append(FiveStar(
                name=pull.name,
                time=pull.time,
                kind=pull.kind,
                span=span,
                cumulative=cumulative,
                is_up=is_up,
                limited_pool=limited,
                is_50=is_up if limited else False,
            ))
            span = 0                          # 每个五星都重置
            # ★ 大保底：UP 才重置 cumulative；歪了继续累加（下一个必 UP）
            cumulative = 0 if is_up or not limited else cumulative
        return result

    def up_count(self) -> int:
        """限定池里出了几个 UP（没歪的五星）。"""
        return sum(1 for f in self.fives_analysis() if f.is_50)

    def not_up_rate(self) -> float | None:
        """**不歪率**（小保底不歪的百分比）。

        口径：限定池里所有五星中，**UP 占的比例**。
        没抽过限定池返回 ``None``（而不是 0 —— 0 会被误读成"每次都歪"）。
        """
        fives = self.fives_analysis()
        if not self.is_limited_pool or not fives:
            return None
        return sum(1 for f in fives if f.is_50) / len(fives) * 100.0

    def average_per_up(self) -> float | None:
        """**每出一个 UP 平均要多少抽**。

        = 该池总抽数 / UP 个数。没出过 UP 返回 ``None``。

        ⚠ 口径说明：工坊的「每UP角色需 74.6 抽」就是这个 —— **总抽数除以 UP 数**
        （歪掉的那些抽也算在里面，因为为了拿到 UP 你**确实**花了那些抽）。
        **不是** ``cumulative`` 的平均值。

        举例：3255 抽 / 63 金 = 51.7（平均出金）；而每 UP 是
        ``3255 / UP数``，因为常驻池的抽、歪掉的抽都摊在 UP 头上。
        """
        ups = self.up_count()
        if not self.is_limited_pool or not ups:
            return None
        return self.total / ups

    def _tier(self, average: float) -> tuple[str, str]:
        """按平均出货抽数取评价 —— 阈值从大到小匹配，第一个命中的就是。

        ``LUCK_TIERS`` 最后一项的阈值是 0.0，所以**任何**正的平均抽数都会命中
        某一档，不需要额外的兜底分支。
        """
        for threshold, title, color in LUCK_TIERS:
            if average >= threshold:
                return title, color
        return LUCK_TIERS[-1][1], LUCK_TIERS[-1][2]   # pragma: no cover - 不可达

    def luck(self) -> tuple[str, str] | None:
        """欧非评价 ``(称号, 颜色)``；没出过五星返回 ``None``。

        按**平均出货抽数**评级（越低越欧），阈值见 :data:`LUCK_TIERS`。
        """
        average = self.average()
        if not average:
            return None
        return self._tier(average)


@dataclass
class GachaReport:
    """全部卡池的统计报告。"""

    player_id: str = ""
    pools: list[PoolStats] = field(default_factory=list)

    # ---------------------------------------------------------------- 汇总
    @property
    def total(self) -> int:
        return sum(p.total for p in self.pools)

    @property
    def five_count(self) -> int:
        return sum(p.five_count for p in self.pools)

    @property
    def four_count(self) -> int:
        return sum(len(p.four_stars) for p in self.pools)

    def rate(self) -> float:
        return (self.five_count / self.total * 100.0) if self.total else 0.0

    def average(self) -> float:
        return (self.total / self.five_count) if self.five_count else 0.0

    def all_five_stars(self) -> list[Pull]:
        """所有五星，按时间倒序（最新在前）。"""
        items = [p for pool in self.pools for p in pool.five_stars]
        return sorted(items, key=lambda p: p.time, reverse=True)

    def all_fives_analysis(self) -> list[FiveStar]:
        """所有五星的逐条分析（含歪没歪），按时间倒序。"""
        items = [f for pool in self.pools for f in pool.fives_analysis()]
        return sorted(items, key=lambda f: f.time, reverse=True)

    def limited_fives(self) -> list[FiveStar]:
        """**获得过的限定角色**（去重按名字）。

        对应工坊那句「共获得限定五星 44 个，常驻五星 19 个」。

        ⚠ **只算角色，不算武器**。反推验证（用户截图，2026-09-30）：
        ``44 + 19 = 63 = 五星数``，两个数加起来正好等于总五星数 ——
        说明这两类统计的都是**角色**（武器在工坊里另有「每UP武器需」那一栏）。
        把武器混进来会让两个数加起来超过总五星数。
        """
        seen: dict[str, FiveStar] = {}
        for f in self.all_fives_analysis():
            if f.kind == "武器":
                continue
            if f.limited_pool and f.is_50 and f.name:
                seen.setdefault(f.name, f)
        return list(seen.values())

    def permanent_fives(self) -> list[str]:
        """**获得过的常驻角色**名字（去重）。

        口径与 :meth:`limited_fives` 对称：**只算角色**（见那里的说明）。
        判定用 :func:`is_limited`（名字不在常驻名单里才算限定）。
        """
        names: list[str] = []
        for f in self.all_fives_analysis():
            if not f.name or f.kind == "武器":
                continue
            if not is_limited(f.name, f.kind) and f.name not in names:
                names.append(f.name)
        return names

    def not_up_rate(self) -> float | None:
        """整体**不歪率**（只看限定池）。没抽过限定池返回 ``None``。"""
        fives = [
            f for pool in self.pools if pool.is_limited_pool
            for f in pool.fives_analysis()
        ]
        if not fives:
            return None
        return sum(1 for f in fives if f.is_50) / len(fives) * 100.0

    def average_per_up(self, kind: str = "角色") -> float | None:
        """**每 UP 角色 / 每 UP 武器**平均多少抽。

        ``kind`` 传 ``"角色"`` 或 ``"武器"`` —— 对应工坊那两栏。
        角色看池 1（角色活动），武器看池 2（武器活动）。
        """
        want = "1" if kind == "角色" else "2"
        for pool in self.pools:
            if pool.pool_type == want:
                return pool.average_per_up()
        return None

    def active_pools(self) -> list[PoolStats]:
        """抽过的池子（没抽过的不显示，免得界面一排全 0）。"""
        return [p for p in self.pools if p.total]

    def pool_by_type(self, pool_type: str) -> PoolStats | None:
        for pool in self.pools:
            if pool.pool_type == pool_type:
                return pool
        return None

    def luck(self) -> tuple[str, str] | None:
        """整体欧非评价（按全部卡池合计的平均出货抽数）。

        ⚠ 复用 :meth:`PoolStats._tier`，别在这里再抄一遍阈值循环 ——
        两处各写一份，改阈值时必然漏掉一处。
        """
        if not self.five_count:
            return None
        return PoolStats._tier(self, self.average())


# --------------------------------------------------------------------- 拉取


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_pool(params: dict[str, str], pool_type: str,
               timeout: int = 30) -> list[dict]:
    """拉一个卡池的原始记录。失败抛 :class:`GachaError`（消息给用户看）。"""
    body = {
        "serverId": params.get("serverId", ""),
        "playerId": params.get("playerId", ""),
        "languageCode": params.get("languageCode", "zh-Hans"),
        "recordId": params.get("recordId", ""),
        "cardPoolId": params.get("cardPoolId", ""),
        "cardPoolType": str(pool_type),
    }
    # 查询串用**接口要的参数名**（不是链接里的原名）
    query = urllib.parse.urlencode({**body, "cardPoolType": str(pool_type)})
    request = urllib.request.Request(
        f"{QUERY_URL}?{query}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 网络问题要变成给用户看的话
        raise GachaError(f"请求失败：{exc}") from exc

    if not isinstance(payload, dict):
        raise GachaError("接口返回了看不懂的内容")
    code = payload.get("code")
    if code == -1:
        # ⚠ 这是**最常见**的失败，而且原因不在我们这边：
        #   抽卡记录链接是**有时效的**，游戏侧要"打开过唤取记录页"才认。
        #   实测（2026-09-30）：从游戏日志里扒出来的旧链接直接报
        #   「请求游戏获取日志异常!」—— 所以提示必须说清**怎么办**。
        raise GachaError(
            (str(payload.get("message") or "读取失败")).strip()
            + "\n\n这通常是**链接过期**了。请回游戏里："
            "唤取 → 唤取记录 → **打开页面并多翻几页** → 重新复制链接。"
        )
    if code not in (0, None):
        raise GachaError(str(payload.get("message") or f"接口返回 code={code}"))
    data = payload.get("data")
    return list(data) if isinstance(data, list) else []


def report_from_records(records: list[dict], *,
                        player_id: str = "") -> GachaReport:
    """用**存下来的记录**重建报告（历史累积那条路走这里）。

    ``records`` 是合并后的原始记录字典（见 :mod:`src.core.gacha_store`），
    每条自带 ``pool_type`` / ``pool``。

    ⚠ 池子**按 :data:`POOLS` 的顺序**建全 7 个（哪怕某个池一条都没有）——
    这样"池编号 → 统计"的对应关系和实时拉取那条路完全一致，
    界面上不会出现"这次有角色池、上次没有"的错位。
    """
    by_pool: dict[str, list[dict]] = {pool_type: [] for pool_type, _ in POOLS}
    for record in records:
        if not isinstance(record, dict):
            continue
        pool_type = str(record.get("pool_type") or "")
        if pool_type in by_pool:
            by_pool[pool_type].append(record)

    report = GachaReport(player_id=player_id)
    for pool_type, display in POOLS:
        stats = PoolStats(name=display, pool_type=pool_type)
        rows = by_pool[pool_type]
        # 接口顺序是"最新在前"，存的时候也保持那个方向
        rows.sort(key=lambda r: str(r.get("time") or ""), reverse=True)
        stats.pulls = [Pull.from_record(r, display) for r in rows]
        report.pools.append(stats)
    return report


def report_from_raw(raw: dict[str, list[dict]], *,
                    player_id: str = "") -> GachaReport:
    """用**一次拉取的原始结果**建报告（``{pool_type: [记录]}``）。

    ⚠ 池子按 :data:`POOLS` 建全 7 个 —— 和 :func:`report_from_records`
    保持一致的"池编号 → 统计"对应关系。
    """
    report = GachaReport(player_id=player_id)
    for pool_type, display in POOLS:
        stats = PoolStats(name=display, pool_type=pool_type)
        stats.pulls = [Pull.from_record(r, display)
                       for r in (raw.get(pool_type) or [])]
        report.pools.append(stats)
    return report


def fetch_raw(params: dict[str, str],
              log=lambda _m: None) -> dict[str, list[dict]]:
    """拉全部卡池的**原始记录**：``{pool_type: [记录, ...]}``。

    ⚠ 一个池拉失败就**整体失败**（抛 :class:`GachaError`）—— 半份结果会
    让统计数字对不上，比直接报错更糟。

    返回原始记录（不转 Pull），是因为「抽卡记录分析」要先把它们
    **合并进本地历史**再统计 —— 接口只给最近一段，累计才算数。
    """
    result: dict[str, list[dict]] = {}
    for pool_type, display in POOLS:
        log(f"拉取「{display}」…")
        records = fetch_pool(params, pool_type)
        result[pool_type] = records
        log(f"  {display}：{len(records)} 抽")
    return result


def fetch_report(params: dict[str, str], log=lambda _m: None) -> GachaReport:
    """拉全部卡池并汇总成报告（**不做累计合并**，只统计这一次拉到的）。

    要累计历史请用 :func:`fetch_raw` + :mod:`src.core.gacha_store`。
    """
    return report_from_raw(fetch_raw(params, log=log),
                           player_id=params.get("playerId", ""))
