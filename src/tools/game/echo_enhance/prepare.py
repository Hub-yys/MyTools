# ⚠ 2026-09-26：**重新启用了**（不再是纯 LEGACY）。
#
# 用户要求：「**可以按照声骸筛选配置，按 B 打开背包筛选指定的声骸**」，
# 并选定把它作为任务流程「开始」步的**准备动作**。所以
# ``echo_enhance/tool.py`` 的 ``create_task_prep`` 现在会构造 :class:`EchoPrep`
# 交给流程（在工具任务真正开跑之前执行）。
#
# **不变的一条规矩**：只做**校准过**的步骤。目前只有「按 B 打开背包」是
# ``verified=True``；「切声骸页签 / 开过滤器 / 筛未调谐 / 按等级排序」四步仍是
# 占位值 —— 默认**跳过、绝不去点游戏里不确定的位置**
# （猜错坐标可能触发分解、弃置这类破坏性操作，不能赌），改为跑一次探测出校准数据。
"""任务流程「开始」步里的**准备动作**：把游戏停到"可以直接强化"的界面。

    按 B 打开背包
      └─ 切到「声骸」页签
           └─ 打开过滤器，筛出未调谐（0 级）的声骸
                └─ 按等级升序排序
                     └─ 停在声骸列表 —— 强化工具从这里接手

⚠ **现状：只有「按 B」这一步是确定的。**
游戏里「声骸页签 / 过滤器 / 排序」的按钮文字和位置，我这边**没有真实界面数据**，
所以 :data:`PREP_STEPS` 里那几步的 ``text`` / ``region`` 是**待校准的占位值**，
``verified=False`` —— 默认**直接跳过**，绝不去点游戏里任何不确定的地方
（猜错坐标可能触发分解、弃置这类破坏性操作，不能赌）。

跳过的同时会自动跑 :meth:`EchoPrep.probe`：把当前画面截图 + OCR 出来的每一行
「序号 + 文字 + 相对坐标 + 像素坐标」落到 ``data/probe/``，并且**在截图上画出框和序号**
—— 拿这一张图 + 一个 txt 就能把 ``PREP_STEPS`` 里的文本和区域填成真的。

为什么参考实现没做这几步：ok-ww 的说明就写着
「点击B进入背包, 在过滤器中选择需要强化的声骸, 并按照等级从0排序后开始」，
运行时只断言「必须在背包声骸界面过滤后开始!」—— 它也是让用户手动筛的。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ....core import paths
from ....core.loadout import normalize_qualities, normalize_status
from .controller import GameWindow, WindowNotFound
from .reader import EchoReader, OcrLine

#: 探测产物落这里（用户数据目录下的 probe/，见 core/paths.py）
DEFAULT_PROBE_DIR = paths.user_data_dir() / "probe"

#: 准备动作要求的**画面宽高比**。
#:
#: ## 为什么卡这一条（2026-09-27 用户问"换台电脑分辨率不一样还能跑吗"）
#:
#: 下面所有区域/坐标都是**相对值（0~1）**，所以：
#:
#: * **同比例的尺寸变化**（1920x1080 → 2560x1440 / 1280x720）：位置比例不变
#:   → **照样准** ✔（ok-ww 自己也只支持这几种，见它的 ``supported_resolution``）
#: * **比例变了**（16:10 / 21:9 / 4:3）：面板相对位置**会整体错位** ✘
#:   —— 比如 21:9 下右侧筛选面板会被挤到更右边，`右上角 0.68` 那一套全对不上
#:
#: 所以这里**先把比例卡住**：不匹配就明确报错停下。
#: 宁可停下说清楚，也不要拿一套错位的坐标去点游戏
#: （猜错位置可能触发分解、弃置这类破坏性操作）。
REQUIRED_ASPECT = 16 / 9
#: 宽高比的容差（实测到的比例和 16:9 差多少就算不匹配）。
#: 0.02 ≈ 1280x720 允许 ±10px 的测量误差。
ASPECT_TOLERANCE = 0.02
#: ok-ww 要求的最小尺寸（它的 ``supported_resolution.min_size`` 也是这个）
MIN_GAME_SIZE = (1280, 720)


def resolution_warning(width: int, height: int) -> str | None:
    """游戏画面尺寸不满足要求时给出**给用户看**的说明，否则 ``None``。

    纯函数（照 ``elevation.admin_hint`` 的写法）—— 好单测，也好在报错里复用。
    """
    if width <= 0 or height <= 0:
        return "读不到游戏画面尺寸（窗口是不是被最小化了？）"
    if (width, height) < MIN_GAME_SIZE:
        return (f"游戏画面太小（{width}x{height}）—— 至少要 "
                f"{MIN_GAME_SIZE[0]}x{MIN_GAME_SIZE[1]}。"
                "放大窗口、或把游戏分辨率调高一档再跑。")
    aspect = width / height
    if abs(aspect - REQUIRED_ASPECT) > ASPECT_TOLERANCE:
        return (f"游戏画面比例是 {width}:{height}（{aspect:.2f}），不是 16:9（1.78）。"
                "本工具的点击位置是按 16:9 的画面位置比例定的，"
                "比例不同会**整体错位**，所以先停下不动手。"
                f"把游戏改成 16:9（如 1920x1080 / 2560x1440 / 1600x900 / 1280x720）再跑。")
    return None


#: 「在区域里找文字」的重试时限（秒）。
#:
#: ★ 2026-09-27 用户反馈「点击太快，可适当停顿一下」。
#:   面板弹出、下拉展开、勾选框回显**都有动画**：点完立刻截图，OCR 到的还是**旧画面**
#:   （表现就是"这一步明明点了却没生效"）。所以这里不是"等多久才放弃"，
#:   而是"在时限内反复截图重试" —— 给慢一拍的界面留出余地。
#:
#: ⚠ 从 3.0 放宽到 5.0 **仍然不够**：实测"合鸣下拉"点完之后，列表要
#: **6 秒以上**才把 7 项都渲染出来（失败那一刻抓到的区域里只有第一项，
#: 而失败之后几秒的探测里 7 项全在）。→ 再放宽到 8.0。
FIND_TEXT_TIMEOUT = 8.0

#: 「列表可能比一屏长」时的滚动参数（2026-09-27）。
#: 合鸣一共 **34 套**，而那个下拉列表一屏只露 7 项左右 ——
#: 用户要的套装若排在后面，"只在可见区域里找"永远找不到
#: （报「没找到文字」，可手动滚一下就有）。
#:
#: 每次滚几格：列表项高约 0.067（一屏 7 项），滚 3 格 ≈ 翻 3~4 项。
LIST_SCROLL_CLICKS = -3
#: 最多滚几次。配合"内容没变就停"，不会无限滚。
MAX_LIST_SCROLLS = 10
#: 滚动找的时候，每一轮"停下来看"的时限（短一点：反正还会滚了再看）。
LIST_FIND_TIMEOUT = 2.5


@dataclass(frozen=True)
class PrepAction:
    """准备动作的一项。

    ``verified=False`` = **还没校准**（文本/区域是占位值）：默认跳过、不点游戏。
    校准方式：跑一次探测，照着 ``data/probe/probe-*.png`` + ``.txt`` 把
    ``region`` / ``text`` 填成真的，然后把 ``verified`` 改成 True。
    """

    kind: str                                   # "press" / "click_text" / "click_at"
    label: str                                  # 日志里的说明
    key: str = ""                               # kind="press" 的按键名
    region: tuple[float, float, float, float] = ()   # kind="click_text" 的搜索区域（相对坐标）
    text: str = ""                              # kind="click_text" 要找的文字（包含匹配）
    #: kind="click_at" 的落点（相对坐标）—— 给**没有文字**的图标按钮用
    point: tuple[float, float] = ()
    #: **点完验证**：点完之后 OCR 必须能在 ``expect_region`` 里找到 ``expect``。
    #: 找不到就抛错停下 —— 宁可停，也不要"以为点上了"继续往下瞎点。
    expect: str = ""
    expect_region: tuple[float, float, float, float] = ()
    #: ``True`` = 要求 ``expect`` **消失**（"把面板关掉了"这种就靠它验）
    expect_absent: bool = False
    #: 这个区域是**可能比一屏长的列表** → 在可见范围里找不到就**往下滚着找**。
    #: 只有"合鸣选套装"用它（合鸣 34 套，一屏只露 7 项）。
    scroll: bool = False
    verified: bool = False
    wait: float = 0.8                           # 动作之后的等待（游戏要时间响应）
    note: str = ""


# ---------------------------------------------------------------- 筛选面板
# 下面这些相对坐标/区域是**照用户 2026-09-26 给的实机截图**量的
# （截图是 16:9，所以比例可以直接用）。
#
# ⚠ 只有一个是**纯图标**、没有文字可 OCR，只能按坐标点：
#   · 底部那一排里的漏斗 = 筛选
#   所以它**点完必须验证**（见 PrepAction.expect）。
#   其余步骤全是按文字找（`click_text`），找不到就报错停下，不会瞎点。
#
# ★★ 2026-09-27 删掉了原来的 ECHO_TAB_POINT = (0.031, 0.296)
#   （注释写的是"背包左侧图标列第 2 个 = 声骸页签"）。**它是错的**：
#   用探测截图核对，按 B **之后本来就在声骸分类**（左上角就是「声骸 494/3000」），
#   而 (0.031, 0.296) 实测落在**左侧全局功能菜单的手套图标**上 ——
#   点下去会把界面切走，后面全乱。所以那一步整个去掉，
#   改成在"按 B"之后**只验证**「声骸」在不在（见 ECHO_PAGE_*）。
# ★★ 2026-09-27 用**探测截图 + 刻度尺**逐个核对过（`data/probe/probe-*.png`）。
#   核对方法：把底部横条裁出来放大 6 倍、画上 0.005 一格的刻度，
#   再把人眼读出的坐标写回来。**别再凭"照截图量的"拍脑袋** ——
#   下面这个漏斗坐标原来写的是 (0.173, 0.988)，y 差了 0.09（≈95px），
#   点下去落在图标**下方的空白处**，等于没点，于是"筛选面板没打开"。
#   （2026-09-27 用户的报错正是：第 2/17 步点完没看到「品质」。）
FILTER_BTN_POINT = (0.108, 0.895)        # 底部**左侧那个圆形按钮**（里面是漏斗图形）
#: 底部那排（都在这条水平线上，y≈0.895）：
#:   圆形漏斗(筛选) | 排序条[漏斗图标|等级顺序] | 排序箭头 | 批量管理 | … | 培养
#: 注意：**排序条里也有一个漏斗图标**，别把它当成筛选按钮 —— 那是排序控件。

#: 验证区域：按 B 之后左上角会有「声骸 494/3000」这样的标题。
#: **2026-09-27 实测确认**：按 B 直接进的就是声骸分类（不用再点页签）。
ECHO_PAGE_REGION = (0.00, 0.00, 0.22, 0.11)
ECHO_PAGE_TEXT = "声骸"
#: 验证区域：筛选面板打开后右侧会出现「品质 / 合鸣」这些行
FILTER_PANEL_REGION = (0.62, 0.10, 1.00, 0.75)
FILTER_PANEL_TEXT = "品质"

#: 筛选面板里各行所在的相对区域（都按用户截图量的）
STATUS_REGION = (0.63, 0.16, 1.00, 0.25)
QUALITY_REGION = (0.63, 0.26, 1.00, 0.34)
#: 「合鸣」那一行（点了会展开下拉）
ECHO_SET_ROW_REGION = (0.63, 0.38, 1.00, 0.46)
#: 合鸣下拉展开后，各个套装名出现的区域。
#:
#: ★★ 2026-09-27 修：原来是 ``(0.62, 0.44, 1.00, 0.80)``，**y 上限太小**。
#:   用真实截图 OCR 量出来：展开的列表里 7 个套装的中心 y 依次是
#:   ``0.4935 / 0.5597 / 0.6287 / 0.6940 / 0.7630 / 0.8306 / 0.8981``
#:   —— **最后一项「雪落无声之愿」在 0.898**，正好掉在 0.80 之外。
#:   用户要的偏偏就是它（配置里 ``echo_set = 雪落无声之愿``），
#:   于是第 6 步报「没找到文字」，怎么改配置都没用。
#:
#:   教训：**列表是"项数不定"的控件，区域要按"可能出现的整段"给**，
#:   不能按"当时看到几项"去框 —— 换个套装就又漏了。
#:   上限取 0.94：再往下是底部工具栏（「等级顺序」在 0.915，但它的 x=0.245
#:   远在 0.62 左边，不会被这个区域框进来）。
ECHO_SET_LIST_REGION = (0.62, 0.44, 1.00, 0.94)
#: 底部「等级顺序」（按等级升序排序 —— ok-ww 要求 0 级在最前）
#: ★ 2026-09-27 核对：文字实际在 x≈0.185~0.235、y≈0.885~0.905。
#:   原来写 (0.18, 0.93, 0.36, 1.00) —— **y 起点 0.93 已经把文字整个漏掉了**
#:   （文字在 0.885~0.905），点它必然"找不到文字"。改成下面这个。
SORT_REGION = (0.16, 0.85, 0.42, 0.95)
SORT_TEXT = "等级顺序"
#: 筛选面板右上角的关闭 X（不关掉的话它会盖住右边，ok-ww 读不到「培养」按钮）
FILTER_CLOSE_POINT = (0.956, 0.069)


#: 我们数据集里的主属性名 → 游戏「主音属性筛选」里那一项的文字。
#: 多数只是加个「主属性」前缀，但这几个说法不一样，必须单独列
#: （对了半天：游戏里是「暴击**率**」「攻击**力**百分比」「治疗**效果**加成」）。
MAIN_STAT_FILTER_NAMES = {
    "暴击": "主属性暴击率",
    "暴击伤害": "主属性暴击伤害",
    "治疗加成": "主属性治疗效果加成",
    "攻击百分比": "主属性攻击力百分比",
    "防御百分比": "主属性防御力百分比",
    "生命百分比": "主属性生命值百分比",
}


def main_stat_filter_name(stat: str) -> str:
    """配置里的主属性名 → 游戏筛选面板里的说法。

    不在表里的（共鸣效率 / 各种属性伤害加成）就是「主属性」+ 原名。
    """
    text = str(stat or "").strip()
    if not text:
        return ""
    return MAIN_STAT_FILTER_NAMES.get(text, "主属性" + text)


# —— 「主音属性」那一块的区域 ——
#: 外层筛选面板里的「主音属性 → 添加主属性筛选」入口（点了弹出小窗）
#:
#: ★ 2026-09-27 修：原来是 ``(0.63, 0.56, 1.00, 0.68)``，**y 起点太低**。
#:   用真实截图 OCR 量出来：「添加主属性筛选」中心在 **(0.7307, 0.5426)**，
#:   而区域从 0.56 才开始 —— 文字整个在**上方**，于是报
#:   「这个区域里**一个字都没 OCR 到**」（第 7/17 步）。
#:   ⚠ "一个字都没 OCR 到"这个提示很有用：它说明是**区域整体错位**，
#:     而不是"文字变了/识别不出"。
ADD_MAIN_STAT_REGION = (0.66, 0.50, 1.00, 0.58)
ADD_MAIN_STAT_TEXT = "添加主属性筛选"
#: 小窗标题（用来验证"小窗开了 / 关了"）
MODAL_TITLE_REGION = (0.06, 0.07, 0.30, 0.16)
MODAL_TITLE_TEXT = "主音属性筛选"
#: 三个 Cost 页签那一行
COST_TAB_REGION = (0.10, 0.19, 0.90, 0.25)
#: 每个页签下面那一片主属性勾选框（3 列网格；名字都唯一，按文字点就行）
MAIN_STAT_GRID_REGION = (0.10, 0.32, 0.92, 0.74)
#: 小窗右下角的「确认」
MODAL_CONFIRM_REGION = (0.70, 0.80, 0.95, 0.88)
MODAL_CONFIRM_TEXT = "确认"


#: 准备步骤表。**只有第一项是已校准的**，其余等探测结果回来再填。
#:
#: ⚠ 这套是**没挂「角色声骸筛选配置」时的兜底**：只把背包打开，
#: **不替用户决定筛选条件**。挂了配置才走 :func:`build_filter_steps`，
#: 那套会按配置真的筛（状态 / 品质 / 合鸣 / 主音属性）。
#: 所以要"自动筛选"，得在编排里挂上筛选配置 —— 没挂就只到背包为止。
#:
#: ★★ 2026-09-27 删掉了原来那四步（开过滤器 / 筛「未调谐」/ 确认 / 排序），
#:   其中**两步是凭空假设的**。用户手动截来的「筛选面板打开后」画面证明：
#:     · 面板的「状态」只有 **已弃置 / 已锁定 / 未标记** —— **根本没有「未调谐」**；
#:     · 面板里**没有「确认」按钮** —— 选完即时生效，关掉面板就是应用。
#:   所以"筛出未调谐"和"确认筛选"**无从点起**，留着只会让后来人白费一场校准。
#:   （"让 0 级排最前"是靠**按等级升序排序**解决的，不是靠筛"未调谐"。）
PREP_STEPS: tuple[PrepAction, ...] = (
    PrepAction(
        "press", "打开背包", key="b", verified=True, wait=1.8,
        # ★ 2026-09-27：原来后面跟了一步"切到「声骸」页签"，**删掉了**。
        #   按 B 之后**已经**在声骸分类（探测截图：左上角就是「声骸 494/3000」），
        #   再点一下页签纯属多余；而且那一步的区域也没实测过。
        #   改成在这里**验证**：没进声骸页就当场报错停下。
        expect=ECHO_PAGE_TEXT, expect_region=ECHO_PAGE_REGION,
        note="背包本来就是开着的时，这一下会把它关掉",
    ),
)


def build_filter_steps(loadout) -> tuple[PrepAction, ...]:
    """按一条「角色声骸筛选配置」生成准备步骤（用户 2026-09-26 第 (1) 条）。

    游戏那块「筛选」面板四行，配置里四个字段一一对应：

    ==============  ================================  ====================
    面板            配置字段                          动作
    ==============  ================================  ====================
    状态（单选）     ``loadout.status``                点那个选项
    品质（多选）     ``loadout.qualities``             每个勾上的点一下
    合鸣（下拉）     ``loadout.echo_set``              点开下拉 → 点套装名
    主音属性        （见下）                          暂不做，见 docstring 末
    ==============  ================================  ====================

    ⚠ **主音属性那一块（4C/3C/1C 各选主属性）还没做**：它是另一个弹窗
    （「主音属性筛选」，里面 3 个 Cost 页签 + 每个页签一组主属性勾选框），
    比外面这四行复杂一档，需要单独的坐标/文字校准。先不做，缺的位置只会
    "筛选条件不全"，不会乱点。

    排序（按等级升序）必须做 —— ok-ww 的强化循环只处理**列表第一个**，
    并按"第一个不再是 0 级"作为结束条件，所以 0 级必须在最前面。
    """
    status = normalize_status(getattr(loadout, "status", None))
    qualities = normalize_qualities(getattr(loadout, "qualities", None))
    echo_set = str(getattr(loadout, "echo_set", "") or "").strip()

    steps: list[PrepAction] = [
        PrepAction(
            "press", "打开背包", key="b", verified=True, wait=2.9,
            # ★ 原来这里后面还跟了一步"切到「声骸」页签"（按坐标点左侧第 2 个图标）。
            #   2026-09-27 用探测截图核对发现**那一步是错的**：按 B 之后**已经**
            #   在声骸分类（左上角就是「声骸 494/3000」），而那个坐标实测落在
            #   **左侧全局功能菜单的手套图标**上 —— 点下去会把界面切走。
            #   所以删掉，改成在"按 B"这步**只做验证**：必须看到「声骸」，
            #   否则当场报错停下（宁停，也不要以为点上了继续往下瞎点）。
            expect=ECHO_PAGE_TEXT, expect_region=ECHO_PAGE_REGION,
            note="背包本来就是开着的话，这一下会把它关掉",
        ),
        PrepAction(
            "click_at", "打开「筛选」面板", point=FILTER_BTN_POINT, verified=True,
            wait=1.6, expect=FILTER_PANEL_TEXT, expect_region=FILTER_PANEL_REGION,
            note="底部那排里的漏斗（没有文字，只能按坐标点，点完 OCR 验证）",
        ),
        PrepAction("click_text", f"状态选「{status}」", region=STATUS_REGION,
                   text=status, verified=True, wait=0.8),
    ]
    for quality in qualities:
        steps.append(PrepAction("click_text", f"品质勾「{quality}」",
                                region=QUALITY_REGION, text=quality,
                                verified=True, wait=0.6))
    if echo_set:
        # ★ 点完「合鸣」**直接验证目标套装已经出现在列表里** —— 比"固定等 N 秒"
        #   可靠得多：列表展开/渲染再慢也能兜住。
        #   2026-09-27 用户那条流程就栽在这：列表要 **6 秒以上**才渲染全，
        #   而当时只等 1.3 秒 + 找文字 5 秒超时，排在**最后一项**的
        #   「雪落无声之愿」一直没被抓到 → 报「没找到文字」。
        steps.append(PrepAction("click_text", "打开「合鸣」下拉",
                                region=ECHO_SET_ROW_REGION, text="合鸣",
                                verified=True, wait=2.0,
                                expect=echo_set,
                                expect_region=ECHO_SET_LIST_REGION,
                                # ★ 必须也标 scroll：验证要**滚着找**目标套装。
                                #   不标的话，目标排在列表后面时这步会 8 秒超时
                                #   直接报错，根本走不到下面"合鸣选…"那步。
                                scroll=True,
                                note="点完必须看得到目标套装（会滚着找）；看不到说明列表还没展开"))
        steps.append(PrepAction("click_text", f"合鸣选「{echo_set}」",
                                region=ECHO_SET_LIST_REGION, text=echo_set,
                                verified=True, wait=1.3,
                                # ★ 34 套，一屏只露 7 项 → 要能滚着找（2026-09-27）
                                scroll=True))
    # ---- 主音属性（4C / 3C / 1C 各选主属性）----
    # 它是**另一个小窗**：外层面板点「添加主属性筛选」弹出来，
    # 里面三个 Cost 页签、每个页签一组主属性勾选框，右下角「确认」。
    # 每档勾哪些 = 配置里那一档的声骸上勾的主属性（见 Loadout.main_stats_by_cost）。
    by_cost = loadout.main_stats_by_cost() if loadout is not None else {}
    if by_cost:
        steps.append(PrepAction(
            "click_text", "打开「主音属性筛选」", region=ADD_MAIN_STAT_REGION,
            text=ADD_MAIN_STAT_TEXT, verified=True, wait=1.6,
            expect=MODAL_TITLE_TEXT, expect_region=MODAL_TITLE_REGION,
            note="点了会弹出小窗；小窗没出来就报错停下",
        ))
        for cost, stats in by_cost.items():
            steps.append(PrepAction(
                "click_text", f"主音属性切到 Cost{cost}", region=COST_TAB_REGION,
                text=f"Cost{cost}", verified=True, wait=1.0,
                note="切错页签的话，下面那些属性名会找不到 —— 找不到就停",
            ))
            for stat in stats:
                label = main_stat_filter_name(stat)
                steps.append(PrepAction(
                    "click_text", f"主音属性勾「{label}」",
                    region=MAIN_STAT_GRID_REGION, text=label, verified=True,
                    wait=0.6,
                ))
        steps.append(PrepAction(
            "click_text", "确认主音属性", region=MODAL_CONFIRM_REGION,
            text=MODAL_CONFIRM_TEXT, verified=True, wait=1.6,
            expect=MODAL_TITLE_TEXT, expect_region=MODAL_TITLE_REGION,
            expect_absent=True,          # 验"小窗关了"
        ))

    steps += [
        PrepAction("click_at", "关掉筛选面板", point=FILTER_CLOSE_POINT, verified=True,
                   wait=1.0,
                   # 验"品质"**消失** = 面板真的关掉了（不然它盖住右边，
                   # ok-ww 读不到「培养」按钮）
                   expect=FILTER_PANEL_TEXT, expect_region=FILTER_PANEL_REGION,
                   expect_absent=True,
                   note="不关的话面板会盖住右边，ok-ww 读不到「培养」按钮"),
        PrepAction("click_text", "按等级升序排序", region=SORT_REGION,
                   text=SORT_TEXT, verified=True, wait=1.3,
                   note="ok-ww 只处理列表第一个，0 级必须在最前"),
    ]
    return tuple(steps)


@dataclass
class ProbeResult:
    """一次探测的产物。"""

    png_path: Path
    txt_path: Path
    lines: int = 0
    pending: tuple[str, ...] = ()       # 这次跳过、还等着校准的步骤

    def summary(self) -> str:
        text = f"探测完成：{self.lines} 行文字 → {self.txt_path.name}"
        if self.pending:
            text += f"（{len(self.pending)} 个准备步骤待校准）"
        return text


class EchoPrep:
    """「开始」步的准备动作：开背包 → （校准后）筛选 → 必要时探测。"""

    def __init__(
        self,
        window: GameWindow | None = None,
        reader: EchoReader | None = None,
        *,
        log: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        probe_dir: Path | str | None = None,
        force_probe: bool = False,
        steps: tuple[PrepAction, ...] | None = None,
    ):
        self.window = window
        self.reader = reader
        self.probe_dir = Path(probe_dir) if probe_dir else DEFAULT_PROBE_DIR
        self.force_probe = force_probe
        self.steps = steps if steps is not None else PREP_STEPS
        self._log_fn = log or (lambda _msg: None)
        self._should_stop = should_stop or (lambda: False)
        #: 最近一次 OCR 在那个区域里看到的文字（失败报错时带上，方便判断原因）
        self._last_lines: list[str] = []

    # ---------------------------------------------------------------- 工具
    def _log(self, message: str) -> None:
        self._log_fn(message)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise RuntimeError("已停止")

    def _get_window(self) -> GameWindow:
        window = self.window or GameWindow()
        self.window = window
        return window

    def _get_reader(self) -> EchoReader:
        if self.reader is None:
            self.reader = EchoReader()
        return self.reader

    # ---------------------------------------------------------------- 主流程
    def run(self) -> ProbeResult | None:
        """跑准备动作。

        返回 ``None`` = 所有步骤都校准好了、按流程走完；
        返回 :class:`ProbeResult` = 有步骤还没校准（跳过了），顺便出了探测产物。
        """
        window = self._get_window()
        if window.find() is None:
            raise WindowNotFound(
                "没找到《鸣潮》窗口。请先打开游戏，并用**窗口模式**（无边框窗口）"
            )
        # ★ 先卡画面比例（2026-09-27）。下面所有区域都是**相对坐标**，
        #   所以同比例的尺寸变化（1080p→1440p）照样准；但比例一变
        #   （16:10 / 21:9）就会**整体错位**，而且还不会报错 ——
        #   那才是最难查的。宁可现在停下说清楚。
        rect = window.refresh_rect()
        warning = resolution_warning(rect.width, rect.height)
        if warning:
            raise RuntimeError(warning)
        self._log(f"窗口：{window.describe()}")
        if not window.bring_to_front():
            # 探测最怕这个：抓到的其实是"当前前台那个窗口"（实测拍到过 MyTools 自己）
            self._log("  ⚠ 游戏窗口没能置前 —— 探测结果可能是别的窗口的画面，先点一下游戏再试")
        self._check_stop()

        pending: list[PrepAction] = []
        for step in self.steps:
            self._check_stop()
            if not step.verified:
                pending.append(step)
                continue
            if step.kind == "press":
                self._log(f"准备：{step.label}（按 {step.key.upper()}）")
                window.press(step.key, after_sleep=step.wait)
            elif step.kind == "click_text":
                self._log(f"准备：{step.label}（点「{step.text}」）")
                if not self._click_text(window, step):
                    raise RuntimeError(
                        f"准备步骤「{self._step_no(step)}」没找到文字「{step.text}」"
                        + self._seen_hint()
                        + self._failure_dump(window, step)
                    )
            elif step.kind == "click_at":
                x, y = step.point
                self._log(f"准备：{step.label}（点坐标 {x:.3f}, {y:.3f}）")
                window.click(x, y, after_sleep=step.wait)
            else:
                raise ValueError(f"不认识的准备动作类型：{step.kind}")

            # ★ 点完验证：配了 expect 就必须验。
            #   两个图标按钮没有文字、只能按坐标点 —— 万一坐标不对，
            #   这一条会**当场报错停下**，而不是"以为点上了"继续往下瞎点。
            if step.expect and not self._verify(window, step):
                what = (f"仍然看得到「{step.expect}」" if step.expect_absent
                        else f"没看到「{step.expect}」")
                raise RuntimeError(
                    f"准备步骤「{self._step_no(step)}」点完之后{what}"
                    + self._seen_hint()
                    + self._failure_dump(window, step)
                )

        if pending:
            self._log("以下准备步骤还没校准，已跳过（不会去点游戏里不确定的位置）：")
            for step in pending:
                self._log(f"  · {step.label} —— {step.note or '待校准'}")

        if pending or self.force_probe:
            return self.probe(window, pending=tuple(step.label for step in pending))
        return None

    # ---------------------------------------------------------------- 失败留痕
    def _failure_dump(self, window: GameWindow, step: PrepAction) -> str:
        """失败时**把现场拍下来**，返回一段拼进报错的说明。

        ## 为什么要这样（2026-09-27）

        以前报错就一句话：

            准备步骤「第 2/17 步 · 打开「筛选」面板」点完之后没看到「品质」

        用户手上只有这句话，我这边只能回头追问"能不能截个图"—— 一个坐标
        来回好几轮才校准得动。真因是 `FILTER_BTN_POINT` 的 y 偏了 0.09，
        点到图标下方的空白处了；**只要有一张"点完之后"的截图，一眼就能看出来**。

        现在失败时自动跑一次探测（截图 + OCR + 画框标序号，落到 ``data/probe/``），
        并把**当时在找什么、在哪个区域找**一并写进报错。
        """
        where = ""
        if step.point:
            where = f"（我点的坐标是 {step.point[0]:.3f}, {step.point[1]:.3f}）"
        elif step.region:
            r = step.region
            where = (f"（我是在 x {r[0]:.2f}~{r[2]:.2f} / y {r[1]:.2f}~{r[3]:.2f} "
                     f"这个区域里找的）")
        try:
            result = self.probe(window, pending=(step.label,))
        except Exception as exc:  # noqa: BLE001 - 留痕失败绝不能盖掉原始错误
            self._log(f"  ⚠ 失败现场没能存下来：{type(exc).__name__}: {exc}")
            return f"\n{where}（失败现场没能存下来：{type(exc).__name__}: {exc}）"
        return (f"\n{where}\n失败现场已存 → {result.txt_path}\n"
                f"（画了框和序号的截图：{result.png_path}；共 {result.lines} 行文字）")

    # ---------------------------------------------------------------- 点击
    def _step_no(self, step: PrepAction) -> str:
        """「第 3/18 步 · 打开「筛选」面板」—— 报错里带步号，用户好对数。"""
        try:
            index = list(self.steps).index(step) + 1
            return f"第 {index}/{len(self.steps)} 步 · {step.label}"
        except ValueError:  # pragma: no cover - 正常不会发生
            return step.label

    def _seen_hint(self, limit: int = 8) -> str:
        """失败时补一句"当时那个区域里看到的是什么"。"""
        lines = [t for t in self._last_lines if t][:limit]
        if not lines:
            return "；这个区域里**一个字都没 OCR 到**（画面不对 / 窗口没在前台 / 权限不足都可能是原因）"
        return "；这个区域里当时看到的是：" + " / ".join(lines)

    def _verify(self, window: GameWindow, step: PrepAction) -> bool:
        """**点完验证**：OCR 确认 ``step.expect`` 在 ``step.expect_region`` 里的**出现/消失**。

        给"没有文字、只能按坐标点"的图标按钮兜底 —— 点错了当场报错停下。
        ``expect_absent=True`` 时反过来要求它**不在**（"把面板关掉了"用这个验）。

        ★ 2026-09-27 修：``step.scroll=True`` 时要**滚着找**（``_find_text_in_list``）。
        原来的写法一律用不滚动的 ``_find_text``，于是「打开合鸣下拉」那步的
        ``expect=目标套装`` 在"目标排在列表后面"时**永远等不到** ——
        8 秒超时直接报错，连会滚的第 6 步都走不到。
        （实测：用户换了个角色，套装「长路启航之星」在列表下方，一屏只露 7 项。）
        """
        region = step.expect_region or step.region
        if not region or not step.expect:
            return True
        if step.scroll:
            found = self._find_text_in_list(window, region, step.expect) is not None
        else:
            found = self._find_text(window, region, step.expect) is not None
        return (not found) if step.expect_absent else found

    def _click_text(self, window: GameWindow, step: PrepAction) -> bool:
        if step.scroll:
            line = self._find_text_in_list(window, step.region, step.text)
        else:
            line = self._find_text(window, step.region, step.text)
        if line is None:
            return False
        window.click(line.x + line.width / 2, line.y + line.height / 2, after_sleep=step.wait)
        return True

    def _find_text_in_list(self, window: GameWindow,
                           region: tuple[float, float, float, float],
                           wanted: str) -> OcrLine | None:
        """在**可能比一屏长**的列表里找文字：找不到就往下滚着找。

        ## 为什么需要（2026-09-27 用户要求）

        合鸣一共 **34 套**，而那个下拉列表一屏只看得到 7 项左右。
        用户要的套装若排在后面，"光在可见区域里找"永远找不到 ——
        报「没找到文字」，可手动滚一下明明就有。

        ## 什么时候停

        滚之前记下"这一屏有哪些文字"；滚完发现**内容没变**，
        说明已经到底了（滚不动了），就别再空转。
        """
        seen: set[frozenset[str]] = set()
        for attempt in range(MAX_LIST_SCROLLS + 1):
            # 第一轮多等一会儿：列表刚展开有渲染延迟（实测要 6 秒以上）。
            # 后面每轮是"滚完再看一眼"，短一点就够 —— 不然找不到时要干等半分钟。
            timeout = FIND_TEXT_TIMEOUT if attempt == 0 else LIST_FIND_TIMEOUT
            line = self._find_text(window, region, wanted, timeout=timeout)
            if line is not None:
                return line
            texts = frozenset(self._last_lines)
            if texts in seen:
                self._log("  （列表已经滚到底了，没再往下翻）")
                break
            seen.add(texts)
            self._scroll_list(window, region)
        return None

    def _scroll_list(self, window: GameWindow,
                     region: tuple[float, float, float, float]) -> None:
        """把光标挪到列表上再滚一屏。

        滚轮只作用于**光标底下**的控件，所以必须先 `move_cursor` ——
        否则滚的是别的区域（甚至整页），越滚越乱。
        """
        x1, y1, x2, y2 = region
        # 落在列表里偏上的位置：别贴边（贴边可能落在滚动条/边框上）
        window.move_cursor((x1 + x2) / 2, y1 + (y2 - y1) * 0.35)
        time.sleep(0.2)
        for _ in range(2):          # 分两次滚，给游戏一帧一帧处理的机会
            window.scroll(LIST_SCROLL_CLICKS)
            time.sleep(0.25)

    def _find_text(
        self,
        window: GameWindow,
        region: tuple[float, float, float, float],
        wanted: str,
        timeout: float = FIND_TEXT_TIMEOUT,
    ) -> OcrLine | None:
        """在相对区域里 OCR，找含指定文字的行（坐标换算回 0~1 相对值）。

        这套"按区域 OCR + 相对坐标换算"在 ``runner.py`` 里也有一份
        （那边还要顺带返回整帧做别的用）。等准备步骤校准完，两处可以合成一个工具函数。
        """
        reader = self._get_reader()
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_stop()
            frame = window.grab()
            height, width = frame.shape[:2]
            x1, y1, x2, y2 = region
            crop = frame[int(y1 * height): int(y2 * height), int(x1 * width): int(x2 * width)]
            lines = reader.ocr_lines(crop)
            # 记下"当时这个区域里到底有什么"—— 失败时把它写进报错，
            # 否则用户只看到"没找到文字"，分不清是"坐标不对"还是"画面根本不对"
            self._last_lines = [line.text for line in lines if line.text]
            # crop 内的像素坐标 → 整帧的相对坐标（和 runner._ocr_region 同一套算法）
            span_x = (x2 - x1) * width or 1.0
            span_y = (y2 - y1) * height or 1.0
            for line in lines:
                if wanted and wanted in line.text:
                    return OcrLine(
                        text=line.text,
                        score=line.score,
                        x=x1 + line.x / span_x * (x2 - x1),
                        y=y1 + line.y / span_y * (y2 - y1),
                        width=line.width / span_x * (x2 - x1),
                        height=line.height / span_y * (y2 - y1),
                    )
            time.sleep(0.25)
        return None

    # ---------------------------------------------------------------- 探测
    def probe(self, window: GameWindow | None = None,
              pending: tuple[str, ...] = ()) -> ProbeResult:
        """截当前画面 → OCR → 落盘「画了框和序号的 png」+「序号/文本/坐标的 txt」。

        这两个文件就是校准 ``PREP_STEPS`` 用的原始数据。
        ``pending`` 是这次因为没校准而跳过的步骤，记进结果里方便日志和界面提示。
        """
        window = window or self._get_window()
        self._log(f"探测当前界面：截图 + OCR，结果写到 {self.probe_dir}")
        frame = window.grab()
        height, width = frame.shape[:2]
        lines = sorted(self._get_reader().ocr_lines(frame), key=lambda ln: (ln.y, ln.x))

        out_dir = Path(self.probe_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        png_path = out_dir / f"probe-{stamp}.png"
        txt_path = out_dir / f"probe-{stamp}.txt"

        # 图上画框 + 序号，和 txt 里的序号一一对应。
        # 画框只是给人看的，失败了照样把原始截图存下来。
        marked = frame.copy()
        drew = False
        try:
            import cv2

            for index, line in enumerate(lines, 1):
                x1, y1 = int(line.x), int(line.y)
                x2, y2 = int(line.x + line.width), int(line.y + line.height)
                cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(marked, str(index), (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            drew = True
        except Exception:  # noqa: BLE001
            self._log("  （画框失败，存的是原始截图）")

        try:
            import cv2

            # imencode + tofile：路径含中文时 cv2.imwrite 会失败，这个写法不会
            cv2.imencode(".png", marked if drew else frame)[1].tofile(str(png_path))
        except Exception as exc:  # noqa: BLE001 - 截图存不下来就只留文本，别把整步搞崩
            self._log(f"  ⚠ 截图保存失败：{exc}")

        rows = [
            f"# 窗口 {width}x{height}  共 {len(lines)} 行文字",
            "# 序号 | 文本 | 相对坐标 x,y,w,h（0~1）| 像素坐标 x,y,w,h",
        ]
        for index, line in enumerate(lines, 1):
            rel = (line.x / width, line.y / height, line.width / width, line.height / height)
            rows.append(
                "%3d | %s | %.4f,%.4f,%.4f,%.4f | %d,%d,%d,%d | %.2f"
                % (index, line.text, rel[0], rel[1], rel[2], rel[3],
                   line.x, line.y, line.width, line.height, line.score)
            )
        txt_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

        self._log(f"  截图（画了框和序号）：{png_path}")
        self._log(f"  文字与坐标：{txt_path}")
        return ProbeResult(png_path, txt_path, len(lines), pending)
