# -*- coding: utf-8 -*-
"""「新建任务」对话框 —— 选任务类型 + 选角色，自动生成整条流程。

## 用户 2026-10-29

> 改任务，不再自己手动配置，新增任务时增加任务类型，
> 目前只有一种类型，声骸强化，保存后自动生成任务

## 改之前是什么样

点「＋ 新增任务流程」→ 打开**完整编排编辑器**（``TaskEditorDialog``）：
左边是工具/配置的调色板，右边是拖拽区，用户得自己
一个一个把「开始 → 声骸筛选配置 → 声骸强化配置 → 工具 → 结束」
拖进去、排好序、再保存。

对现在的需求（只有一种固定套路）来说太繁琐了。

## 现在是什么样

点「＋ 新增任务流程」→ 这个对话框：

    ┌─────────────────────────────────────┐
    │  新增任务                           │
    │                                     │
    │  任务类型   [声骸强化          ▼]   │
    │                                     │
    │  角色       [绯雪              ▼]   │
    │             （兼容的配置：筛选 ✓ 强化 ✓）│
    │                                     │
    │              [保存]  [取消]          │
    └─────────────────────────────────────┘

保存后**自动生成**这 5 步（和现有流程结构一模一样）::

    开始 → <角色>-声骸筛选 → <角色>-声骸强化 → 声骸自动强化 → 结束

## 为什么还要保留旧编辑器

「修改」按钮仍然打开完整编辑器 —— 用户可能想调整步骤顺序、
加别的工具（比如先跑一次「扫荡残像聚落」）。

新建走简化路径，修改走完整路径。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..core import game_data
from ..core import tasks as tasks_mod
from ..core.tasks import (  #: 成套声骸结构（界面和任务运行两侧共用一份）
    DEFAULT_SET_BONUS,
    DEFAULT_SET_PLAN,
    SET_BONUS_CHOICES,
    SET_PLAN_CHOICES,
    SET_PLAN_CUSTOM,
    SET_PLAN_PRESETS,
    format_set_plan,
    parse_set_plan,
    resolve_set_plan,
    set_plan_error,
)
from .config_names import (
    flow_character_of,
    flow_level_of,
    flow_name_for,
    flow_name_with_level,
    flow_set_plan_of,
)
from .pickers import (
    CHARACTER_BOX_HINT,
    CHARACTER_BOX_WIDTH,
    FilterComboBox,
    avatar_icon,
)

logger = logging.getLogger(__name__)

#: 配置类型常量 —— **不在 ``core.tasks`` 里**，各自定义在对应的 store 模块。
#:
#: 步骤的 ``config_kind`` 必须用这两个值（见 ``tasks.kind_type_name``）：
#: 工具靠它判断"挂的是不是我这类配置"。填错的话筛选步骤会被当成
#: 强化配置读，判定条件就全错了。
_KIND_LOADOUT = "loadout"            #: = ``core.loadout.KIND``
_KIND_ECHO_PROFILE = "echo_profile"  #: = ``core.echo_profile.KIND``

#: 任务类型 → 生成器。目前只有一种，以后加新套路往这里加。
#:
#: 每个生成器签名：``(character, loadout_id, profile_id) -> list[TaskStep]``
TASK_TYPES: dict[str, str] = {
    "声骸强化": "echo_enhance",
}

#: 对话框宽度（和「修改」那个对齐）
DIALOG_WIDTH = 520

#: 套装结构输入框的宽度（5 位数字 + 左右内边距）
PLAN_BOX_WIDTH = 110

#: 套装结构「下拉」的宽度 —— 要放得下「自定义」三个字
PLAN_CHOICE_WIDTH = 120

#: 套装结构输入框的占位提示。
#: ⚠ 别写长 —— 110px 里只放得下约 7 个汉字，写多了会被截成带省略号的半句。
PLAN_BOX_HINT = "如 4311"

#: 声骸属性级别 → 有效词条数。
#:
#: ## 用户 2026-10-29
#:
#: > 任务再增加声骸属性级别，分为小毕业，大毕业，完美毕业，
#: > 分别对应有效词条3条，4条，5条
#:
#: 「有效词条数」就是配置里的 ``settings["min_valid_count"]``
#: （见 ``tools/game/echo_enhance/settings.py``）：
#: 满级时至少有这么多条**核心属性 + 可选属性**里的词条才算符合条件。
#:
#: ## ⚠ 上限受「核心 + 可选」总条数限制
#:
#: ``EchoSettings.valid_count_range()`` 算出的上界 = 核心条数 + 可选条数
#: （因为声骸 5 个孔位里**每种词条只出现一次**，凑不出重复的）。
#:
#: 实测（2026-10-29 用户真实配置）::
#:
#:     锁暝     核心 2 + 可选 2 = 上限 4  → **「完美毕业」做不到**
#:
#: 所以选级别时要检查，做不到就提示用户去配置页补可选属性 ——
#: 不能默默把 5 夹成 4（用户以为选了完美毕业，实际按大毕业在跑）。
ATTR_LEVELS: dict[str, int] = {
    "小毕业": 3,
    "大毕业": 4,
    "完美毕业": 5,
}

#: 默认级别（和现有配置的常见值一致：多数是 3~4）
DEFAULT_ATTR_LEVEL = "大毕业"


def build_echo_enhance_flow(character: str, loadout_id: str,
                            profile_id: str,
                            level: str = "",
                            set_plan: str = "") -> tasks_mod.TaskFlow:
    """生成一条「声骸强化」任务流程。

    :param character: 角色名（用于流程名和步骤显示名）
    :param loadout_id: 该角色的「角色声骸筛选」配置 id
    :param profile_id: 该角色的「角色声骸强化」配置 id
    :param level: 声骸属性级别（``小毕业`` / ``大毕业`` / ``完美毕业``）。
        会写进流程名 ``绯雪-声骸自动强化（小毕业）`` ——
        用于"同角色同级别只能一条"的查重（见 :func:`existing_flow_for`）。
        传空串 = 不带级别（老格式）。
    :param set_plan: 套装结构（1~5 位，每位只能是 4/3/1、各位之和 ≤12），
        如 ``43311`` / ``44111`` / ``4311``；空串 = 不成套。
        也会写进流程名 ``绯雪-声骸自动强化（小毕业 43311）``，
        任务跑的时候从名字里读出来（见 ``config_names.flow_set_plan_of``，
        解析成 ``{Cost: 需要几种}`` 见 ``core.tasks.parse_set_plan``）。

    结构（和用户现有的两条流程完全一致）::

        开始 → <角色>-声骸筛选 → <角色>-声骸强化 → 声骸自动强化 → 结束

    ⚠ ``config_kind`` 必须填对：工具靠它判断"挂的是不是我这类配置"
    （见 ``core/tasks.py`` 的 ``KIND_LOADOUT`` / ``KIND_ECHO_PROFILE``），
    填错的话筛选步骤会被当成强化配置读，判定条件就全错了。
    """
    who = str(character or "").strip()
    steps = [
        tasks_mod.TaskStep(type=tasks_mod.STEP_START, key="start", name="开始"),
        tasks_mod.TaskStep(
            type=tasks_mod.STEP_CONFIG,
            key=str(loadout_id or ""),
            name=f"{who}-声骸筛选",
            config_kind=_KIND_LOADOUT,
        ),
        tasks_mod.TaskStep(
            type=tasks_mod.STEP_CONFIG,
            key=str(profile_id or ""),
            name=f"{who}-声骸强化",
            config_kind=_KIND_ECHO_PROFILE,
        ),
        tasks_mod.TaskStep(
            type=tasks_mod.STEP_TOOL,
            key="echo_enhance",
            name="声骸自动强化",
        ),
        tasks_mod.TaskStep(type=tasks_mod.STEP_END, key="end", name="结束"),
    ]
    #: ★ 2026-10-29 用户：
    #: > 每个任务里，每个角色、声骸属性级别只能有1条
    #:
    #: 把级别和套装结构写进流程名（``绯雪-声骸自动强化（小毕业 43311）``）：
    #:   * 让用户一眼看出这是什么任务
    #:   * 查重时能反推"这个角色这个级别已经有任务了"
    #:   * **运行时**任务从名字里读出套装结构，据此判断哪一档已经凑够种类
    return tasks_mod.TaskFlow(
        name=flow_name_with_level(who, level, set_plan), steps=steps)


def existing_flow_for(character: str, level: str, flows=None):
    """已存在的「同角色 + 同级别」流程（没有就 ``None``）。

    ## 用户 2026-10-29

    > 每个任务里，每个角色、声骸属性级别只能有1条，
    > 同一个角色，同一个声骸属性级别再保存时就直接提示，并保存不了

    判定方式：从流程名里剥出**角色**和**级别**，两个都相同就算重复。
      * 「绯雪-声骸自动强化（小毕业）」 vs 「绯雪-声骸自动强化（大毕业）」
        → 角色同、级别不同 → **不冲突**（可以共存）
      * 两条都是「绯雪-声骸自动强化（小毕业）」→ **冲突**

    ⚠ 老流程（没带级别括号的「绯雪-声骸自动强化」）算**级别为空** ——
    不拦着。那种流程是 2026-10-29 之前建的，用户自己知道是哪个级别，
    硬拦会让他连原来的流程都重建不了。

    :param flows: 传进来用于测试；``None`` 时读真实 store
    """
    who = str(character or "").strip()
    lv = str(level or "").strip()
    if not who or not lv:
        return None
    if flows is None:
        try:
            store = tasks_mod.TaskStore()
            store.load()
            flows = store.all()
        except Exception:  # noqa: BLE001 - 读不到就当没有，别挡着保存
            logger.warning("读任务流程失败", exc_info=True)
            return None
    for flow in flows or ():
        name = str(getattr(flow, "name", "") or "")
        if flow_character_of(name) == who and flow_level_of(name) == lv:
            return flow
    return None


def valid_count_cap(profile) -> int:
    """这条强化配置**最多能要求几条有效词条**。

    上界 = 核心属性条数 + 可选属性条数 —— 因为声骸 5 个孔位里
    **每种词条只会出现一次**，配了 2 核心 + 2 可选就最多凑出 4 条。

    这跟 ``EchoSettings.valid_count_range()`` 的算法一致（那边还要夹
    ``MAX_VALID_COUNT = 5``），这里只要上界用于提示用户"做不到"。

    .. note::
       2026-11-05 起 ``valid_count_range()`` 的**下界**也变了
       （核心条数 + 可选勾了 ≥1 条就 +1），但**上界算法没变**，
       所以本函数（只算上界）不受影响，仍是 ``n_core + n_opt``。
       核心勾满 5 条时可选属性在界面上已不可勾，于是这里也不会 >5。

    :param profile: ``EchoProfile``（读它的 ``settings`` dict）
    :return: 0 = 读不到配置；否则是最多条数
    """
    try:
        settings = dict(getattr(profile, "settings", None) or {})
    except Exception:  # noqa: BLE001 - 配置坏了当读不到
        return 0
    core = settings.get("core_stats")
    optional = settings.get("optional_stats")
    n_core = len(core) if isinstance(core, (list, tuple)) else 0
    n_opt = len(optional) if isinstance(optional, (list, tuple)) else 0
    return n_core + n_opt


def apply_attr_level(profile, level: str) -> bool:
    """把「属性级别」写进这条强化配置的 ``min_valid_count``。

    ## 用户 2026-10-29

    > 任务再增加声骸属性级别，分为小毕业，大毕业，完美毕业，
    > 分别对应有效词条3条，4条，5条

    ⚠ **会真的改配置**（落盘）—— 因为任务流程跑的时候读的是配置里
    存的那份 ``settings``，不落盘的话选了也不生效。

    ⚠ 超上限时**不改**并返回 ``False``：绝不默默夹成上限值
    （用户以为选了完美毕业、实际按大毕业在跑，那是最难发现的问题）。

    :return: 是否改成功
    """
    want = ATTR_LEVELS.get(str(level or "").strip())
    if want is None:
        return False
    cap = valid_count_cap(profile)
    if cap and want > cap:
        return False
    try:
        from ..core.echo_profile import EchoProfileStore

        settings = dict(getattr(profile, "settings", None) or {})
        settings["min_valid_count"] = want
        #: 用真实的 EchoSettings 走一遍收敛（夹核心数、夹有效词条范围），
        #: 免得存进去一个越界值 —— 界面回填时才不会莫名跳回别的数。
        try:
            from ..tools.game.echo_enhance.settings import EchoSettings

            settings = EchoSettings.from_dict(settings).to_dict()
        except Exception:  # noqa: BLE001 - 收敛失败就用原样，至少值是对的
            logger.warning("收敛强化配置失败，按原值保存", exc_info=True)
        profile.settings = settings
        store = EchoProfileStore()
        store.load()
        return bool(store.update(profile))
    except Exception:  # noqa: BLE001
        logger.warning("写回强化配置失败", exc_info=True)
        return False


def compatible_characters() -> list[tuple[str, str, str]]:
    """能自动生成流程的角色 → ``[(角色, 筛选id, 强化id), ...]``。

    **两个配置都必须有**才能生成（缺一个流程就跑不起来）：
      * 筛选配置 → 决定游戏里筛出哪些声骸
      * 强化配置 → 决定判定条件（什么词条算好）

    数据来自两个 store，名字对上就算配对。用 ``updated_at``
    倒序 —— 最近改过的角色排前面（同配置页的排序规矩）。
    """
    from ..core.echo_profile import EchoProfileStore
    from ..core.loadout import LoadoutStore

    try:
        loadouts = LoadoutStore()
        loadouts.load()
        filter_by_char = {x.character: x for x in loadouts.all()
                          if str(getattr(x, "character", "") or "").strip()}
    except Exception:  # noqa: BLE001 - 读不到就当没有
        logger.warning("读角色声骸筛选配置失败", exc_info=True)
        filter_by_char = {}

    try:
        store = EchoProfileStore()
        store.load()
        enhance_by_char = {p.name: p for p in store.all()
                           if str(getattr(p, "name", "") or "").strip()}
    except Exception:  # noqa: BLE001
        logger.warning("读角色声骸强化配置失败", exc_info=True)
        enhance_by_char = {}

    result: list[tuple[str, str, str]] = []
    for character, loadout in filter_by_char.items():
        profile = enhance_by_char.get(character)
        if profile is None:
            continue
        result.append((character,
                       str(getattr(loadout, "id", "") or ""),
                       str(getattr(profile, "id", "") or "")))
    result.sort(key=lambda x: x[0])
    return result


class NewFlowDialog(MessageBoxBase):
    """新增任务：选类型 + 选角色 → 自动生成流程。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.widget.setFixedWidth(DIALOG_WIDTH)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

        self.viewLayout.addWidget(SubtitleLabel("新增任务"))

        # -------------------------------------------------------------- 角色
        #: ★ 2026-10-29 用户：「任务这里，角色要做成跟前面同一套，
        #: 应该说所有角色这里都是一样的」
        #:
        #: → 改用和**配置页 / 完整编排编辑器**完全同一套控件：
        #:   ``pickers.FilterComboBox`` + ``game_data.CHARACTERS`` + ``avatar_icon``
        #:
        #:   和原来那个朴素 ``ComboBox`` 的区别：
        #:     * **列出全部角色**（以前只列"两个配置都齐"的 7 个）
        #:     * **带角色头像**图标
        #:     * **可打拼音/中文筛选**（点一下摊开全部，打字即过滤）
        #:     * 提示语 "选角色（可打拼音筛）" —— 和别处一模一样
        #:
        #:   ⚠ 配置是否齐全**不在下拉里挡**（那会让用户以为角色不存在），
        #:   改在下面 :meth:`_refresh_hint` 里说清楚"这个角色还缺哪个配置"。
        #:   这样和配置页的行为一致：选谁都能选，缺什么提示什么。
        char_row = QWidget(self)
        row2 = QHBoxLayout(char_row)
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(10)
        tag2 = StrongBodyLabel("角色", char_row)
        tag2.setFixedWidth(76)
        row2.addWidget(tag2)
        game_data.ensure_loaded()          # 保证 CHARACTERS 有内容
        self.character_box = FilterComboBox(char_row)
        self.character_box.setFixedWidth(CHARACTER_BOX_WIDTH)
        self.character_box.setPlaceholderText(CHARACTER_BOX_HINT)
        self.character_box.set_choices(
            [(c.name, avatar_icon(c.avatar, c.name)) for c in game_data.CHARACTERS])
        row2.addWidget(self.character_box)
        row2.addStretch(1)
        self.viewLayout.addWidget(char_row)

        # ---------------------------------------------------------- 任务类型
        type_row = QWidget(self)
        row = QHBoxLayout(type_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        tag = StrongBodyLabel("任务类型", type_row)
        tag.setFixedWidth(76)
        row.addWidget(tag)
        self.type_box = ComboBox(type_row)
        self.type_box.setFixedWidth(220)
        for name in TASK_TYPES:
            self.type_box.addItem(name)
        row.addWidget(self.type_box)
        row.addStretch(1)
        self.viewLayout.addWidget(type_row)

        type_hint = CaptionLabel(
            "选任务类型后会自动生成整条流程（开始 → 筛选 → 强化 → 工具 → 结束），"
            "不用再手动拖拽编排。", self)
        type_hint.setTextColor("#8A8F98", "#7C7C7C")
        type_hint.setWordWrap(True)
        self.viewLayout.addWidget(type_hint)

        # ------------------------------------------------------ 声骸属性级别
        #: ★ 2026-10-29 用户：
        #: > 任务再增加声骸属性级别，分为小毕业，大毕业，完美毕业，
        #: > 分别对应有效词条3条，4条，5条
        #:
        #: 这个值会**写进该角色的「角色声骸强化」配置**（``min_valid_count``）——
        #: 因为任务流程跑的时候读的就是配置里存的那份。
        level_row = QWidget(self)
        row3 = QHBoxLayout(level_row)
        row3.setContentsMargins(0, 0, 0, 0)
        row3.setSpacing(10)
        tag3 = StrongBodyLabel("声骸属性级别", level_row)
        tag3.setFixedWidth(96)
        row3.addWidget(tag3)
        self.level_box = ComboBox(level_row)
        self.level_box.setFixedWidth(220)
        for name, count in ATTR_LEVELS.items():
            #: 用户 2026-10-29：「这里大于等于改成 =」
            #: 写成「有效词条=4」—— 和配置页那行「有效词条 ≥4」区分开，
            #: 这里是"这个级别要几条"，不是"至少几条"的区间描述。
            self.level_box.addItem(f"{name}（有效词条={count}）")
        #: 默认选 DEFAULT_ATTR_LEVEL（现有配置大多是 3~4 条，大毕业最常见）
        _names = list(ATTR_LEVELS)
        if DEFAULT_ATTR_LEVEL in _names:
            self.level_box.setCurrentIndex(_names.index(DEFAULT_ATTR_LEVEL))
        row3.addWidget(self.level_box)
        row3.addStretch(1)
        self.viewLayout.addWidget(level_row)

        self.level_hint = CaptionLabel("", self)
        self.level_hint.setTextColor("#8A8F98", "#7C7C7C")
        self.level_hint.setWordWrap(True)
        self.viewLayout.addWidget(self.level_hint)

        # ------------------------------------------------------ 是否成套声骸
        #: ★ 2026-10-29 用户：
        #: > 任务再增加一个是否成套声骸，如果是再让用户选择是43311,还是44111，
        #: > 根据这个判断，如果强化好了声骸类型，就不再强化该类型
        #:
        #: 不成套 = 现有行为（配置里勾的都强化，不按结构计数）。
        set_row = QWidget(self)
        row4 = QHBoxLayout(set_row)
        row4.setContentsMargins(0, 0, 0, 0)
        row4.setSpacing(10)
        tag4 = StrongBodyLabel("是否成套声骸", set_row)
        tag4.setFixedWidth(96)
        row4.addWidget(tag4)
        self.set_box = ComboBox(set_row)
        self.set_box.setFixedWidth(120)
        for name in SET_BONUS_CHOICES:
            self.set_box.addItem(name)
        if DEFAULT_SET_BONUS in SET_BONUS_CHOICES:
            self.set_box.setCurrentIndex(SET_BONUS_CHOICES.index(DEFAULT_SET_BONUS))
        row4.addWidget(self.set_box)

        #: 套装结构（只有「成套」时才显示出来）
        #:
        #: ★ 2026-11-07 用户：结构要能**自由输入**
        #:
        #: > 成套可以自由输入成套时的数字比如，现在现有44111，43311，
        #: > 我可以输入4311，这时强化好1个4C，1个3C就跳过，其他4C、3C，
        #: > 但是这个输入有校验，数字长度最多为5，数字加起来不能超过12
        #:
        #: 所以从 ``ComboBox``（只能在那两个预设里选）换成可输入的单行框：
        #: 预设只是占位提示里的例子，用户想填什么填什么，合法性由
        #: :func:`core.tasks.set_plan_error` 统一判（前端不另写一套规则）。
        #:
        #: ★ 2026-11-08 用户（圈图纠正）：
        #:
        #: > 这里应该是下拉列表选择43311 44111 自定义，自定义时就是自由输入
        #:
        #: 所以是**下拉 + 可选输入框**的组合，不是光秃秃一个输入框：
        #: ``plan_choice_box`` 里放两个预设和「自定义」，只有选到
        #: 「自定义」时才把 ``plan_box`` 显示出来。
        self.plan_choice_box = ComboBox(set_row)
        self.plan_choice_box.setFixedWidth(PLAN_CHOICE_WIDTH)
        for name in SET_PLAN_CHOICES:
            self.plan_choice_box.addItem(name)
        #: 默认选第一个预设（= DEFAULT_SET_PLAN，老行为不变）
        if DEFAULT_SET_PLAN in SET_PLAN_CHOICES:
            self.plan_choice_box.setCurrentIndex(
                SET_PLAN_CHOICES.index(DEFAULT_SET_PLAN))
        row4.addWidget(self.plan_choice_box)

        self.plan_box = LineEdit(set_row)
        self.plan_box.setFixedWidth(PLAN_BOX_WIDTH)
        self.plan_box.setText("")
        #: ⚠ 不设 ``setMaxLength(5)``：全角数字 / 带空格的 ``4 3 1 1``
        #: 会被硬截断成半截数字，反而更难看出哪里错。
        #: 长度和位数之和都交给保存时校验提示。
        self.plan_box.setPlaceholderText(PLAN_BOX_HINT)
        #: 只有选「自定义」才露出来（初始是预设 → 先藏起来）
        self.plan_box.setVisible(False)
        row4.addWidget(self.plan_box)
        row4.addStretch(1)
        self.viewLayout.addWidget(set_row)

        self.set_hint = CaptionLabel("", self)
        self.set_hint.setTextColor("#8A8F98", "#7C7C7C")
        self.set_hint.setWordWrap(True)
        self.viewLayout.addWidget(self.set_hint)

        self.char_hint = CaptionLabel("", self)
        self.char_hint.setTextColor("#8A8F98", "#7C7C7C")
        self.char_hint.setWordWrap(True)
        self.viewLayout.addWidget(self.char_hint)

        self.viewLayout.addStretch(1)

        #: 角色 → (筛选id, 强化id)。**只有配置齐全的角色才在这里**；
        #: 下拉里仍然能选到全部角色（跟配置页一致），选到不齐的由
        #: :meth:`_refresh_hint` / :meth:`validate` 说清楚缺什么。
        self._pairs: dict[str, tuple[str, str]] = {}
        self._reload_pairs()
        #: FilterComboBox 是 EditableComboBox —— 用 textChanged 而不是
        #: currentIndexChanged（打字/清空时索引不变，但文本会变）
        self.character_box.currentTextChanged.connect(
            lambda _t: self._refresh_hint())
        self.level_box.currentIndexChanged.connect(
            lambda _i: self._refresh_level_hint())
        self.set_box.currentIndexChanged.connect(
            lambda _i: self._refresh_set_hint())
        #: ★ 2026-11-08：plan_box 是「自定义」时才露出的输入框，
        #: 下拉选到预设时它藏着 —— 两个信号都要接（换下拉要立刻显示/隐藏）。
        self.plan_choice_box.currentIndexChanged.connect(
            lambda _i: self._refresh_set_hint())
        self.plan_box.textChanged.connect(
            lambda _t: self._refresh_set_hint())
        self._refresh_hint()

    # ---------------------------------------------------------------- 数据
    def _reload_pairs(self) -> None:
        """加载"角色 → 两个配置 id"的配对表。

        ⚠ **不再**用 ``clear()`` + ``addItem()`` 填下拉 —— 那是朴素
        ``ComboBox`` 的用法。``FilterComboBox`` 的候选是 ``set_choices()``
        一次性给的（构造时已经填好全部角色），这里只更新配对表。
        """
        self._pairs.clear()
        for character, loadout_id, profile_id in compatible_characters():
            self._pairs[character] = (loadout_id, profile_id)

    def _refresh_hint(self) -> None:
        """按当前选中的角色更新提示（**说清楚缺哪个配置**）。"""
        #: ⚠ 先同步「套装结构」的显隐，**和角色选没选无关**。
        #: ★ 2026-11-08 用户圈图："不成套" 旁边还露着 43311 下拉 ——
        #: 因为这个方法在"没选角色"时提前 return 了，从没调过
        #: :meth:`_refresh_set_hint`，那两个控件就一直保持着
        #: 构造时的默认可见状态。
        self._sync_set_visibility()
        who = self.character()
        if not who:
            self.char_hint.setText("请选一个角色（点一下下拉可打拼音筛选）")
            self.level_hint.setText("")
            self.set_hint.setText("")
            return
        if who in self._pairs:
            self.char_hint.setText(
                f"将自动生成：开始 → {who}-声骸筛选 → {who}-声骸强化 "
                f"→ 声骸自动强化 → 结束")
            self._refresh_level_hint()
            self._refresh_set_hint()
            return
        #: 选到了配置不齐的角色 —— 明确告诉他缺什么、去哪补
        missing = self._missing_of(who)
        self.char_hint.setText(
            f"⚠ 「{who}」还缺「{'」「'.join(missing)}」配置 —— "
            f"请先到「配置」页建好，再回来新建任务")
        self.level_hint.setText("")
        self.set_hint.setText("")

    def is_set_bonus(self) -> bool:
        """选的是「成套」吗。"""
        return str(self.set_box.currentText() or "").strip() == "成套"

    def is_set_plan_custom(self) -> bool:
        """套装结构选的是「自定义」吗（只有这时候才看输入框）。"""
        picked = str(self.plan_choice_box.currentText() or "").strip()
        return picked == SET_PLAN_CUSTOM

    def _sync_set_visibility(self) -> None:
        """只做显隐：成套才露下拉，选「自定义」才露输入框。

        单独抽出来，是因为它必须**在没选角色时也执行** ——
        :meth:`_refresh_hint` 在角色为空时会提前 return（提示语要说
        "请选一个角色"），但显隐不能跟着跳过，否则「不成套」旁边会
        一直挂着一个 43311 下拉（★ 2026-11-08 用户圈出来的那个）。
        """
        is_set = self.is_set_bonus()
        self.plan_choice_box.setVisible(is_set)
        self.plan_box.setVisible(is_set and self.is_set_plan_custom())

    def set_plan(self) -> str:
        """填的套装结构（``43311`` / ``44111`` / ``4311`` …）；不成套时返回空串。

        选的是预设就直接返回预设，选「自定义」才去读输入框
        （见 :func:`core.tasks.resolve_set_plan`）。
        返回的是**规整过**的纯数字串（去空白、全角转半角），
        所以 ``4 3 1 1`` 和 ``４３１１`` 都会变成 ``4311``。
        """
        if not self.is_set_bonus():
            return ""
        return resolve_set_plan(
            self.plan_choice_box.currentText(), self.plan_box.text())

    def _refresh_set_hint(self) -> None:
        """「是否成套」的提示 + 显示/隐藏套装结构输入框。

        ## 用户 2026-10-29

        > 任务再增加一个是否成套声骸，如果是再让用户选择是43311,还是44111，
        > 根据这个判断，如果强化好了声骸类型，就不再强化该类型，
        > 比如强化好了2个1C的，如果还有别的1C那也不再强化了，也就是跳过

        ## 用户 2026-11-07（结构改成自由输入）

        > 成套可以自由输入成套时的数字比如，现在现有44111，43311，
        > 我可以输入4311，这时强化好1个4C，1个3C就跳过，其他4C、3C，
        > 但是这个输入有校验，数字长度最多为5，数字加起来不能超过12

        ## 用户 2026-11-08（一个光秃秃的输入框他不认）

        > 这里应该是下拉列表选择43311 44111 自定义，自定义时就是自由输入

        所以他圈出来的是「下拉 + 条件出现的输入框」：
        ``plan_choice_box`` 里放两个预设 + 「自定义」，只有选「自定义」
        才露出 ``plan_box``。自由输入的校验规则一点没变。

        所以提示文字必须**现算**：填什么就把什么换算成 ``4C×1 + 3C×1 + 1C×2``，
        填错了当场说清楚错在哪（不是等点保存才报）。

        计数规则（用户确认）：**按种类算，不按件数**。
        43311 的 ``1C×2`` = 凑齐 2 种**不同名字**的 1C。
        """
        #: 只有「成套」时才显示下拉；选到「自定义」才显示输入框
        self._sync_set_visibility()
        is_set = self.is_set_bonus()
        if not is_set:
            self.set_hint.setText(
                "不成套：按配置里勾选的所有声骸逐个强化，"
                f"不按 {' / '.join(SET_PLAN_PRESETS)} 这类结构计数")
            return
        plan = resolve_set_plan(
            self.plan_choice_box.currentText(), self.plan_box.text())
        if not plan:
            #: 只有「自定义」+ 没填才会走到这（预设本身一定合法）
            self.set_hint.setText(
                "自定义：几位 = 一共几个声骸，每位 = 那个声骸的 COST。"
                f"例如 {'、'.join(SET_PLAN_PRESETS)}，也可以自己写 4311")
            return
        problem = set_plan_error(plan)
        if problem:
            #: 直接说清楚哪里不合法，别让用户猜
            self.set_hint.setText(f"⚠ {problem}")
            return
        try:
            counts = parse_set_plan(plan)
        except ValueError as exc:      # 理论上上面已经拦过
            self.set_hint.setText(f"⚠ {exc}")
            return
        parts = format_set_plan(counts)
        detail = "、".join(f"{cost}C 凑齐 {n} 种**不同名字**的"
                          for cost, n in sorted(counts.items(), reverse=True))
        total = sum(counts.values())
        self.set_hint.setText(
            f"{plan} = {parts}（共 {total} 个声骸）。强化好这些种类数后，"
            f"该档剩余的同类型声骸**全部跳过**（{detail}）")

    def _refresh_level_hint(self) -> None:
        """按「角色 + 属性级别」提示能不能做到，以及会改哪条配置。

        ## 为什么要提示"做不到"

        「有效词条数」的上界 = 核心属性条数 + 可选属性条数
        （声骸 5 个孔位里每种词条只出现一次）。实测用户的「锁暝」配置
        是 2 核心 + 2 可选 = 上限 4 → 选「完美毕业（5 条）」根本凑不出来。

        这时候**必须说清楚**，否则用户会以为选了完美毕业、实际一直在
        按大毕业跑（或者更糟：因为 `min_valid_count` 被夹到 4，
        每个声骸都判不过、全部被弃置）。
        """
        who = self.character()
        level = self.attr_level()
        want = ATTR_LEVELS.get(level, 0)
        profile = self._profile_of(who)
        if profile is None:
            self.level_hint.setText("")
            return
        cap = valid_count_cap(profile)
        if not cap:
            self.level_hint.setText(
                f"⚠ 读不到「{who}-声骸强化」配置的内容 —— 保存时会跳过属性级别设置")
            return
        #: 现有配置的条数，让用户知道这次会改什么
        try:
            current = int(dict(profile.settings or {}).get("min_valid_count") or 0)
        except Exception:  # noqa: BLE001
            current = 0
        base = f"「{who}-声骸强化」的有效词条数：{current or '?'} → {want}"
        if want > cap:
            self.level_hint.setText(
                f"⚠ {base} —— **做不到**：这条配置只勾了 {cap} 条属性"
                f"（核心 + 可选），最多凑出 {cap} 条有效词条。"
                f"请到「配置」页给「{who}-声骸强化」多勾几条可选属性，"
                f"或改用「小毕业 / 大毕业」")
            return
        self.level_hint.setText(f"保存时会更新 {base}")

    def _profile_of(self, character: str):
        """取某角色的「角色声骸强化」配置（``EchoProfile`` 或 ``None``）。"""
        who = str(character or "").strip()
        if not who:
            return None
        try:
            from ..core.echo_profile import EchoProfileStore

            store = EchoProfileStore()
            store.load()
            for p in store.all():
                if p.name == who:
                    return p
        except Exception:  # noqa: BLE001
            logger.warning("读角色声骸强化配置失败（%s）", who, exc_info=True)
        return None

    def _missing_of(self, character: str) -> list[str]:
        """这个角色缺哪些配置（用于提示）。"""
        missing: list[str] = []
        try:
            from ..core.echo_profile import EchoProfileStore
            from ..core.loadout import LoadoutStore

            loadouts = LoadoutStore()
            loadouts.load()
            if not any(x.character == character for x in loadouts.all()):
                missing.append("角色声骸筛选")
        except Exception:  # noqa: BLE001 - 读不到就按"缺"算，提示他去检查
            missing.append("角色声骸筛选")
        try:
            from ..core.echo_profile import EchoProfileStore

            store = EchoProfileStore()
            store.load()
            if not any(p.name == character for p in store.all()):
                missing.append("角色声骸强化")
        except Exception:  # noqa: BLE001
            missing.append("角色声骸强化")
        return missing or ["（配置读取失败）"]

    def character(self) -> str:
        return str(self.character_box.text() or "").strip()

    def task_type(self) -> str:
        return str(self.type_box.currentText() or "").strip()

    def attr_level(self) -> str:
        """当前选的属性级别名。

        ``level_box`` 的条目是 ``"大毕业（有效词条=4）"`` 这种带说明的，
        这里把括号那部分切掉 —— 只留纯级别名去查 :data:`ATTR_LEVELS`。
        """
        text = str(self.level_box.currentText() or "").strip()
        return text.split("（")[0].strip() if text else ""

    def attr_level_count(self) -> int:
        return ATTR_LEVELS.get(self.attr_level(), 0)

    # ---------------------------------------------------------------- 校验
    def validate(self) -> bool:  # noqa: D102 - MessageBoxBase 钩子
        """保存前把关。返回 False 会**阻止对话框关闭**。"""
        who = self.character()
        if not who:
            self.char_hint.setText("⚠ 请先选一个角色")
            return False
        if who not in self._pairs:
            #: 具体缺哪个配置已经由 _refresh_hint 说过，这里只拦下保存
            self._refresh_hint()
            return False
        if self.task_type() not in TASK_TYPES:
            self.char_hint.setText("⚠ 请先选任务类型")
            return False
        if not self.attr_level_count():
            self.level_hint.setText("⚠ 请先选声骸属性级别")
            return False
        #: ★ 2026-11-07 用户：结构可自由输入，但「数字长度最多为5，
        #: 数字加起来不能超过12」—— 校验只有 ``core.tasks.set_plan_error``
        #: 一份，界面和网页两端都调它，别各写一套。
        if self.is_set_bonus():
            problem = set_plan_error(self.set_plan())
            if problem:
                self._refresh_set_hint()
                self.set_hint.setText(f"⚠ {problem}")
                return False
        #: 级别超过这条配置能凑出的条数 → 不许保存
        #: （否则要么被默默夹小、要么每个声骸都判不过全被弃置）
        profile = self._profile_of(who)
        if profile is not None:
            cap = valid_count_cap(profile)
            if cap and self.attr_level_count() > cap:
                self._refresh_level_hint()
                return False
        #: ★ 2026-10-29 用户：
        #: > 每个任务里，每个角色、声骸属性级别只能有1条，
        #: > 同一个角色，同一个声骸属性级别再保存时就直接提示，并保存不了
        #:
        #: ⚠ 查重只看**角色 + 级别**，不看套装结构 —— 用户说的是
        #: "每个角色、声骸属性级别只能有1条"，套装结构是级别内的选项。
        #: （否则同一个「小毕业」能建 43311 和 44111 两条，
        #: 两个任务又会互相覆盖同一条强化配置，等于白建。）
        existing = existing_flow_for(who, self.attr_level())
        if existing is not None:
            self.char_hint.setText(
                f"⚠ 已经有「{who}」的「{self.attr_level()}」任务了："
                f"「{existing.name}」—— 同一个角色同一个属性级别只能有一条。"
                f"请改用别的属性级别，或到任务列表里直接运行那一条")
            return False
        return True

    # ---------------------------------------------------------------- 结果
    def result_flow(self) -> tasks_mod.TaskFlow | None:
        """按选择生成流程；配置不全 / 重复返回 ``None``。

        ⚠ **会先改配置**：把选的属性级别写进该角色的「角色声骸强化」
        配置（``min_valid_count``）。任务流程跑的时候读的就是那份。
        """
        who = self.character()
        pair = self._pairs.get(who)
        if pair is None:
            return None
        level = self.attr_level()
        #: 兜底再查一次重复（正常路径 validate 已经拦过）
        if existing_flow_for(who, level) is not None:
            return None
        loadout_id, profile_id = pair
        #: 把属性级别落到配置里（做不到就保持原样，validate 已经拦过）
        profile = self._profile_of(who)
        if profile is not None:
            if not apply_attr_level(profile, level):
                logger.warning("属性级别「%s」没能写到「%s」的配置里", level, who)
        return build_echo_enhance_flow(who, loadout_id, profile_id, level,
                                       self.set_plan())
