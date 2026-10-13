# -*- coding: utf-8 -*-
"""从视频里**学出该按什么键** —— 这是原来完全没做的那一半。

## 我原来漏了什么（必须说清）

原来的实现只做两件事::

    ① 照视频画面**对齐视角**（往左/往右转）
    ② **一直按 W 往前走**

而"照视频做操作"是这样的::

    视频某一刻按了 F    →  机器走到那一刻时也按 F
    视频某一刻按了空格 →  机器也按空格（跳跃/冲刺）
    视频某一刻长按了 E  →  机器也长按 E（解谜机关）
    视频某一刻选了对话 →  机器也选那一个

**那些按键原来一个都没学到。** 所以「飞、解谜、长按机关、对话分支」
全都没实现 —— 用户的诉求只做到了"跟着画面走"，没做到"做一样的操作"。

## 怎么从视频里学按键

攻略视频里**按键会被画出来**：UP 主为了让人看懂，通常在屏幕上有个
按键提示区（"F 对话"、"（长按）离开心钥井"）。而更要紧的是 ——
**游戏自己也有提示**（实测 P4 里 23.5% 的时间有交互提示）。

所以学按键有两条路，**都要**：

============================  ==========================================
来源                           含义
============================  ==========================================
**游戏自带的提示**              游戏让我按什么（最可靠 —— 那是游戏在说话）
**UP 主的画面标注**             讲解型标注（"这里要飞"）
============================  ==========================================

## ⚠ 这个模块**不读视频像素**（那在 reader 里）

本模块只做**判定**：给一个"这一刻画面上有哪些按键提示"的观测，
加上"我在视频第几帧"，输出**该按什么键**。

拆开是因为：判定是**会算错**的部分（按错键会让机器乱动），
必须能穷举单测；而读像素是**测不了准**的部分（要真视频、要 OCR）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 按键名 → 游戏里实际的键。
#:
#: ⚠ 视频里写的是**游戏提示上的字**，要映射成机器按键。
#: 这个表只收**真正是键名**的词；不认识的原样返回
#: （宁可原样试一下，也别静默丢掉 —— 丢掉等于那个机关不解了）。
#:
#: ## ★★ 「离开 / 返回」**绝对不能**放进来（实测踩过）
#:
#: 它们看起来像键名，其实是**动作描述**。实测那条真提示::
#:
#:     [F] （长按）离开心钥井
#:      ↑ 键是 F        ↑ 这是"要做什么"
#:
#: OCR 漏掉那个 F 图标时只剩「（长按）离开心钥井」。
#: 要是"离开"映射成 ESC，机器就会**按 ESC** ——
#: 那会**打开暂停菜单**，把整条路线打断。
#:
#: → 所以它们只算**动作词**（见 :data:`_ACTION_WORDS`），
#:   不提供键。OCR 没读到键名时**宁可不按** ——
#:   "少做一次"远比"按错键"轻（按错会打断路线，少做只是卡一下）。
KEY_ALIASES: dict[str, str] = {
    "F": "f",
    "E": "e",
    "Q": "q",
    "R": "r",
    "T": "t",
    "V": "v",
    "X": "x",
    "Z": "z",
    "C": "c",
    "空格": "space",
    "跳跃": "space",
    "冲刺": "shift",
    "闪避": "shift",
    "蹲下": "ctrl",
    "攻击": "mouse_left",
    "重击": "mouse_left",
    "共鸣技能": "e",
    "共鸣解放": "r",
    "声骸": "q",
}

#: "长按" 的各种写法（视频/游戏里都出现过）
HOLD_MARKERS = ("长按", "按住", "长摁", "持续按", "hold")

#: 提取按键名用的模式（大写单字母 + 常见中文键名）
_LETTER = re.compile(r"\b([A-Z])\b")
_CN_KEY = re.compile("|".join(re.escape(k) for k in KEY_ALIASES
                              if not k.isascii()))

#: 提示里**必然**带着的"动作词"。没有它就要靠别的判据（见下）。
#:
#: ## ★ 为什么要有这道闸（实测抓到的）
#:
#: OCR 会读出**场景里的杂字**，不是只有按键提示。实测一例::
#:
#:     OCR 原文 = "宁（长按）离开心钥井"      ← 开头那个「宁」是噪声
#:
#: 噪声本身不致命（键还是解析对了），但它说明**OCR 会读进无关文字**。
#: 要是某段无关文字里碰巧有个大写字母（菜单标题、UP 主的字幕），
#: 就会被当成按键去按 —— 那是"机器在游戏里乱动"。
#:
#: 所以要求提示里**至少有一个动作词**，
#: **或者**符合 :data:`_INTERACT_PATTERN` 那个"键 + 目标名"的形状。
#: 「F 对话」有"对话"；「（长按）离开心钥井」有"离开" —— 都过。
#: 而"北"、"东"、"在下油甘"这种画面标注过不了。
_ACTION_WORDS = (
    "对话", "交谈", "调查", "拾取", "捡起", "开启", "打开", "使用",
    "离开", "返回", "进入", "退出", "确认", "取消", "跳过",
    "交互", "操作", "攻击", "闪避", "跳跃", "冲刺", "下落",
    "长按", "按住", "点击", "按下", "触发", "启动", "关闭",
    "拾起", "阅读", "查看", "驾驶", "乘坐", "下车", "上车",
)

#: ★★ "键 + 目标名"的形状 —— **游戏提示最常见的样子**。
#:
#: ## 为什么要这条（2026-10-11 实测抓到的漏判）
#:
#: 用户给的「在下油甘 3.5 无主的梁鸢」视频建完库**学到了 0 个按键**。
#: 看起来像"这视频没提示"，但把高分帧的提示区裁出来一看::
#:
#:     [F] 鸱吻          ← 清清楚楚一个交互提示！
#:
#: OCR 也确实读出来了（``'F 鸱吻'``）。但解析层把它**丢了** ——
#: 因为「鸱吻」是个**机关/怪物名**，不在 :data:`_ACTION_WORDS` 里，
#: 而当时"没有动作词就不算提示"。
#:
#: 这就是**判据写得太窄**：游戏提示的文案是"键 + 目标名"，
#: 目标名可能是任何东西（鸱吻 / 声匣 / 宝箱 / 信标 / NPC 名字…）。
#: 想把目标名列全是不可能的（跟"列色值永远列不全"一个道理）。
#:
#: → 所以改成**按形状判**：**开头就是交互键** + 后面还有内容。
#:
#: ## ⚠⚠ 为什么开头那个键必须是**已知的交互键**

#: 形状判据本身**不够**，实测抓到的反例::
#:
#:     'A B C'   → 会被当成"按 A"
#:     'B 方案'  → 会被当成"按 B"
#:
#: 这些都是场景杂字（分组标注、方案编号），不是提示。
#: 而 A / B 是**移动键**（A/D 是转视角！）—— 误按会让机器乱转。
#:
#: 所以要求开头那个字母在 :data:`INTERACTION_KEYS` 里。
#: 那份表只收**实测见过是交互键**的字母；要加新的**得先有证据**
#: （见到真实提示里用了它），不能凭猜 —— 这张表错了就是机器乱按键。
INTERACTION_KEYS: frozenset[str] = frozenset({
    "F",   # 最常见的交互键（对话/拾取/调查）
    "E",   # 技能/交互
    "Q",   # 声骸技能
    "R",   # 共鸣解放
    "T",   # 标记/追踪
    "V",   # 视角/其他
    "X", "Z", "C",   # 其余功能键
})

#: 交互提示的**形状**：开头是交互键（可带"长按"和括号）+ 后面还有内容。
_INTERACT_PATTERN = re.compile(
    r"^\s*[（(]?\s*"                       #: 可能前面有括号
    r"(?:长按|按住|长摁|hold)?\s*"          #: 可能有"长按"
    r"([" + "".join(sorted(INTERACTION_KEYS)) + r"])\b"   #: ★ 已知交互键
    r"\s*[）)]?\s*"                         #: 可能带右括号
    r"[：:、,，]?\s*"
    r"(.+)$"                                #: 后面还有内容（目标名）
)

#: 同上，但键是**中文键名**（"跳跃 前面的平台"）
_INTERACT_PATTERN_CN = re.compile(
    r"^\s*(?:" + "|".join(re.escape(k) for k in KEY_ALIASES
                          if not k.isascii()) + r")\s*[：:、,，]?\s*(.+)$"
)

#: 默认长按时长（秒）。视频看不出精确时长，取一个"够触发机关"的值。
DEFAULT_HOLD_SEC = 1.2

#: 普通点按的时长
TAP_SEC = 0.05

#: 同一次提示最多持续多少帧（防止把一次提示当成一百次按键）
#: 实测参考帧间隔 15 帧；提示通常持续 1~3 秒 = 2~6 个参考帧
MAX_CONSECUTIVE = 6


@dataclass(frozen=True)
class KeyPress:
    """**该按的一个键**。"""

    #: 原始提示文字（保留下来给日志/报告 —— 出问题要能回查）
    text: str
    #: 机器该按的键
    key: str
    #: 按多久（秒）
    seconds: float
    #: 是不是长按
    hold: bool = False
    #: 视频里的参考帧下标（视频第几秒按的）
    frame_index: int = 0

    @property
    def label(self) -> str:
        return f"{'长按' if self.hold else '按'}{self.key.upper()}"


@dataclass
class KeyEvent:
    """一次"视频在这一段里按了键"的事件。"""

    #: 提示原文
    text: str
    #: 键
    key: str
    #: 长按吗
    hold: bool
    #: 起始 / 结束参考帧下标
    start: int
    end: int

    @property
    def frames(self) -> int:
        return self.end - self.start + 1


@dataclass
class KeySchedule:
    """整段视频学出来的**按键表**。

    这是"照视频做操作"的核心产物：一串 ``(视频第几帧, 按什么键)``。
    """

    events: list[KeyEvent] = field(default_factory=list)
    #: 统计
    scanned: int = 0
    unreadable: int = 0

    def presses_for(self, index: int) -> list[KeyPress]:
        """走到视频第 ``index`` 个参考帧时，该按哪些键。

        ⚠ **只在事件的起点按一次**（不是每一帧都按）。
        持续按住的情况由 ``hold`` 的时长表达，而不是连按一百次 ——
        连按会让"长按机关"变成"点了一百下"，那是错的。
        """
        out = []
        for e in self.events:
            if e.start != index:
                continue
            out.append(KeyPress(
                text=e.text,
                key=e.key,
                seconds=DEFAULT_HOLD_SEC if e.hold else TAP_SEC,
                hold=e.hold,
                frame_index=index,
            ))
        return out

    def describe(self) -> str:
        """一行总结（报告用）。"""
        if not self.events:
            return "视频里没学到任何按键"
        holds = sum(1 for e in self.events if e.hold)
        keys = {}
        for e in self.events:
            keys[e.key] = keys.get(e.key, 0) + 1
        top = "、".join(f"{k}×{v}" for k, v in
                        sorted(keys.items(), key=lambda kv: -kv[1])[:6])
        return (f"学到 {len(self.events)} 次按键"
                f"（其中长按 {holds} 次）：{top}")


def parse_prompt(text: str) -> KeyPress | None:
    """把一句提示文字解析成"按什么键"。

    :param text: 提示原文，如 ``"F 对话"``、``"F 鸱吻"``、
        ``"（长按）离开心钥井"``
    :return: :class:`KeyPress`；解析不出返回 ``None``

    ## 判据（按可靠性排序）

    ⓪ ★ **先过"像不像按键提示"这道闸**（:func:`_looks_like_prompt`）——
       不像就返回 ``None``。OCR 会读进场景杂字，不加这道闸，
       一段碰巧含大写字母的无关文字（菜单标题 / UP 主字幕）
       就会被当成按键去按 = 机器在游戏里乱动。
    ① 有**大写单字母**（``F`` / ``E``）→ 用那个键
    ② 否则找**中文键名**（``跳跃`` / ``共鸣技能`` / ``声骸``）
    ③ 都没有 → ``None``（**宁可不按，也不猜**）

    ⚠ 出现"长按"字样就是**长按**。这个区别很重要：
    长按机关用点按是**不会触发**的（游戏要求按住），
    而点按机关用长按只是慢一点。所以宁可判成长按。

    ## ★★ 为什么"有动作词但没键名"要返回 ``None``

    实测那条真提示是 ``[F] （长按）离开心钥井`` ——
    **F 是键，"离开心钥井"是要做的事**。

    OCR 常常只读出文字、读不到那个 F 图标。这时如果拿"离开"去
    映射一个键，就会按 ESC（暂停菜单）—— **把整条路线打断**。

    → 读不到键名就**不按**。"少做一次"只是卡一下，
      "按错键"会毁掉整段流程。
    """
    raw = str(text or "").strip()
    if not raw:
        return None

    #: ⓪ 先确认这**像不像**按键提示（挡掉场景杂字）
    if not _looks_like_prompt(raw):
        return None

    hold = any(marker in raw.lower() for marker in HOLD_MARKERS)

    #: ① ★ "键 + 目标名"的形状优先 —— 这是游戏提示最常见的写法。
    #:
    #: ``"F 鸱吻"`` 这种：F 是键，"鸱吻"是**机关名**。
    #: 不能靠"认不认识鸱吻"来判断（目标名可以是任何东西），
    #: 只能靠**形状**：开头就是键 + 后面还有内容。
    match = _INTERACT_PATTERN.match(raw)
    if match:
        return KeyPress(
            text=raw,
            key=KEY_ALIASES.get(match.group(1), match.group(1).lower()),
            seconds=DEFAULT_HOLD_SEC if hold else TAP_SEC,
            hold=hold,
        )
    match_cn = _INTERACT_PATTERN_CN.match(raw)
    if match_cn:
        cn_key = match_cn.group(0)[:match_cn.start(1) - match_cn.start(0)]
        cn_key = cn_key.strip(" \t：:、,，")
        return KeyPress(
            text=raw,
            key=KEY_ALIASES.get(cn_key, cn_key),
            seconds=DEFAULT_HOLD_SEC if hold else TAP_SEC,
            hold=hold,
        )

    #: ② 退化：句子中间出现的大写单字母 / 中文键名
    key = ""
    letters = _LETTER.findall(raw)
    if letters:
        key = letters[0]
    else:
        found = _CN_KEY.findall(raw)
        if found:
            key = found[0]

    if not key:
        return None

    machine = KEY_ALIASES.get(key, key.lower())
    return KeyPress(
        text=raw,
        key=machine,
        seconds=DEFAULT_HOLD_SEC if hold else TAP_SEC,
        hold=hold,
    )


def _looks_like_prompt(text: str) -> bool:
    """这段文字像不像"游戏在让我按键"。

    过闸条件（任一即可）::

        ① ★ **形状对**：开头就是"键 + 目标名"（``F 鸱吻``）
        ② 有动作词（对话 / 离开 / 长按 …）
        ③ 本身就是中文键名（跳跃 / 共鸣技能 / 声骸 …）

    ## ★★ ① 是怎么来的（实测漏判）

    用户给的「在下油甘 3.5 无主的梁鸢」视频，建完库**学到了 0 个按键**。
    看上去像"这视频没提示"，但把高分帧裁出来一看::

        [F] 鸱吻          ← 清清楚楚一个交互提示

    OCR 也读出来了（``'F 鸱吻'``）—— 但**解析层把它丢了**，
    因为「鸱吻」是机关名、不在动作词表里，而当时"没动作词就不算提示"。

    **那是判据写得太窄**：游戏提示的文案是"键 + 目标名"，
    目标名可以是任何东西（鸱吻 / 声匣 / 宝箱 / 信标 / NPC 名字…）。
    想把它们列全是不可能的 —— 跟"列色值永远列不全"一个道理。

    ## ⚠ 为什么要求"**开头**就是键"

    提示条上的键永远画在最前面（``[F] 鸱吻``）；
    而场景杂字里的大写字母**位置随机**（"第 3 期 A 组"、"B 方案"）。
    要求"第一个字就是那个键"能挡掉绝大部分噪声 ——
    比"认不认识后面的词"可靠得多。
    """
    if _INTERACT_PATTERN.match(text):
        return True
    if _INTERACT_PATTERN_CN.match(text):
        return True
    if any(word in text for word in _ACTION_WORDS):
        return True
    return _CN_KEY.search(text) is not None


def build_schedule(observations) -> KeySchedule:
    """把逐帧观测合并成按键表。

    :param observations: 可迭代的 ``(参考帧下标, 提示文字或 None)``

    :return: :class:`KeySchedule`

    ## 合并规则（★ 这里最容易做错）

    同一个提示会**连续出现好几帧**（提示条不会一闪而过）。
    每一帧都记一条的话，一次"按 F"会变成"连按 F 十几下" ——
    在游戏里表现为疯狂连点，很多机关会被点坏（或者根本没反应）。

    所以要**合并成一段**（:class:`KeyEvent`），并且
    :meth:`KeySchedule.presses_for` **只在起点按一次**。

    ⚠ 换提示就断开（``"F 对话"`` → ``"空格 跳跃"`` 是两件事）。
    """
    schedule = KeySchedule()
    current: KeyEvent | None = None

    for index, text in observations:
        schedule.scanned += 1
        if not text:
            #: 提示消失 → 这一段结束
            if current is not None:
                schedule.events.append(current)
                current = None
            continue

        press = parse_prompt(text)
        if press is None:
            schedule.unreadable += 1
            continue

        if current is not None and current.text == press.text:
            #: 同一个提示继续 → 延长这一段（但有上限，防止卡死在一句提示上）
            if current.frames < MAX_CONSECUTIVE:
                current.end = index
            continue

        #: 换了提示 → 收尾旧的、开新的
        if current is not None:
            schedule.events.append(current)
        current = KeyEvent(text=press.text, key=press.key, hold=press.hold,
                           start=index, end=index)

    if current is not None:
        schedule.events.append(current)
    return schedule
