# -*- coding: utf-8 -*-
"""扫荡残像聚落 —— 工具页：**卡片展示 + 一键全选 + 按顺序刷**。

## 用户要的是什么

原话（2026-10-13）::

    新增"扫荡残像聚落"工具，会展示当前版本所有的残像聚落和梦魇残像，
    以卡片形式展示，可以一键勾选全部，勾选的运行后，根据顺序一个一个去刷

这一页就照着这句话长：**卡片**（一个目标一张）、**全选按钮**、
**运行按钮**（按勾选的顺序跑）。顺序逻辑全在
:mod:`src.core.nest_sweep`（纯逻辑、有单测），本页只管画和接线。

## ★ 卡片长什么样（2026-10-13 用户**五轮**调整后的最终版）

::

    ┌────────────────────────────────┐
    │    [图]套装A  [图]套装B          │   ← ★ 套装在上（图标 + 名称）
    │    [图]套装C  [图]套装D          │      ⚠ 没有「可出套装」小标题
    │    [图]套装E  [图]套装F          │      ⚠ 高度**固定 4 行** → 各卡对齐
    │    [图]套装G                     │
    │        复生丘原残像聚落           │   ← ★ 名字**自己居中**（偏移 0）
    │              ☑                 │   ← ★ 勾选框在名字**下面**、单独居中
    └────────────────────────────────┘

用户原话（按时间顺序）::

    ① 残像聚落显示的卡片，应该展示他可以出的声骸套装图片+名称
    ② 卡片展示为：上方套装图标+套装名称，下方聚落名称
    ③ 放在聚落名称下面，可出套装也去掉，另外整体按聚落出的时间顺序倒叙排序
       （图上还标了「居中」）
    ④ 排列要整齐 … 这些说明直接干掉
    ⑤ 名称在上，按钮在下 … 没有对齐 / 像这样对齐

刷之前就知道这一趟值不值。**每一轮改动的细节（以及为什么）见
:class:`TargetCard` 的类文档。**

## ★ 只有一张卡片墙 —— **不再区分残像聚落 / 梦魇聚落**

原话：「不再区分残像聚落/梦魇聚落，统一叫残像聚落」。

所以**不再按 kind 分段**（原先分两段还各加一行小标题，现在都去掉了），
所有目标平铺成一张卡片墙。数据里的 ``kind`` 字段仍然保留 ——
任务侧的三层定位（名称 → 别名 → 行号）还要用它区分分组。

## ★ 卡片顺序 = 版本从新到旧

原话：「整体按照聚落出的时间顺序倒叙排序」。
排序逻辑在 :func:`src.core.nest_sweep.catalog._version_key`，本页只显示。

## ⚠ 曾经有过一张"梦魇声骸清单"卡片（**已删**）

第一版下面还铺了一块「当前版本的梦魇残像声骸」（25 个名字的资料卡）。
用户 2026-10-13 把它整块划掉：「**干掉**」。

删掉的理由（现在回头看）：那 25 个里有约 10 个是**大世界野外刷新**的，
本来就不在这 5 处聚落里 —— 那块清单既不完整、又和上面的聚落卡片重复，
留着只会让人以为"打完聚落能拿全这 25 个"。
数据文件里的 ``_nightmare_echoes`` 一节**保留**（是资料，别的用途可能还要）。

## ⚠ 卡片不写成"全选后 50 个框一起动会卡"

本项目为列表性能返工过（见 ``pickers.STAT_COLUMNS`` 的说明）。
这里目标数量是**个位到十几个**（不是几百个角色的量级），
所以直接铺卡片就够了，不需要虚拟滚动。真到几十上百条再说。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    CheckBox,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core import paths
from ....core.categories import ToolCategory
from ....core.nest_sweep import (
    SweepTarget,
    build_plan,
    load_catalog,
    load_selection,
    save_selection,
    selection_summary,
)
from ....core.game_data import icon_path
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.widgets import ConfigCard
from ..auto_combat.okww_boot import get_host

#: 页面在引擎里的任务名（要和 ``okww_boot.TASKS`` 的键一致）
TASK_KEY = "扫荡残像聚落"

#: 说明文字颜色（(浅色主题, 深色主题)）—— 与其他页保持同一套灰
MUTED = ("#8A8F98", "#7C7C7C")

#: 卡片网格的列数。目标名字不长（10 字上下），3 列在常见窗口宽度下正好。
CARD_COLUMNS = 3

#: 卡片最小宽度 —— 比这窄的话名字会折成两行，卡片高度就参差不齐了
CARD_MIN_WIDTH = 260

#: 套装图标显示尺寸（px）。32 能看清图形、又不至于把卡片撑高。
SET_ICON_SIZE = 32

#: 套装图标在磁盘上的位置（``assets/game/echo_sets/<套装名>.png``）
SET_ICON_DIR = "echo_sets"

#: ⚠ 这里**没有**「套装区固定几行」那样的常量了。
#:
#: 第 ④ 轮曾经有（``SET_ROWS = 4``，为了"排列整齐"），
#: 但用户第 ⑨ 轮指出：「这种只有一种的，卡片自适应所需，**内容并且居中**」——
#: 固定 4 行会让只有 1 套的 5 张梦魇卡各留 3 行空白（约 105px 的洞）。
#: 现在高度按**实际行数**算（:meth:`TargetCard._sets_rows`），
#: 同行卡片被拉高时靠**上下 stretch** 让内容居中。

#: 一行放几个套装
SET_COLUMNS = 2

#: 套装**列之间**的间距（px）。
#:
#: ⚠ 列位置必须由 ``QGridLayout`` 统一决定（见 ``_build_sets_block``）——
#:   用"每行一个 QHBoxLayout"时列宽会随每行内容漂，
#:   实测第 2 列 x 在 [181, 181, 129] 之间跳（52px！），那就是用户说的"没对齐"。
SET_COL_GAP = 6

#: 套装行之间的间距（px）。
#:
#: ⚠ 这个值必须和 :meth:`TargetCard._sets_block_height` 里算的**完全一致**：
#: 固定高度和实际内容高度对不上时，Qt 会把差额**摊到各行上**，
#: 行距就漂了 —— 实测 6 套的卡行距 41/42、7 套的 40/41，并排看就是"没对齐"。
SET_ROW_GAP = 3

#: 勾选框控件至少要这么宽（px）—— Qt 会把更小的值钳到这个数，实测值。
CHECK_INDICATOR_WIDTH = 20

#: 把**指示器**（不是控件）推到中线上所需的左侧垫片（px）。
#:
#: ``CheckBox("")`` 的指示器**画在固定的左侧位置** —— 实测中心离控件左缘
#: ``a ≈ 10.5px``，**与控件宽度无关**。控件被 Qt 钳到 ``W ≈ 29px``，所以
#: 控件居中时指示器偏左 ``W/2 - a ≈ 4px``。
#:
#: 推导（见 :class:`TargetCard` 的注释）::
#:
#:     S = W - 2a = 29 - 21 = 8
#:
#: ``setFixedWidth`` / ``setContentsMargins`` 都**改不动**这个偏移
#: （位置由 paintEvent 直接算），所以只能在布局里垫。
CHECK_NUDGE = 8


def set_icon_pixmap(name: str) -> QPixmap | None:
    """取套装图标；**文件不在就返回 ``None``**（界面自己留白）。

    ⚠ ``assets/game/`` **不进仓库**（是库洛画面衍生物，见 .gitignore）——
    所以"图标不在"是**正常情况**，不是错误。这里绝不能抛异常，
    也不能画一个破图占位：宁可只显示名字。
    """
    stem = str(name or "").strip()
    if not stem:
        return None
    try:
        target = Path(icon_path(f"{SET_ICON_DIR}/{stem}.png"))
    except Exception:                                 # noqa: BLE001
        return None
    if not target.exists():
        return None
    pix = QPixmap(str(target))
    if pix.isNull():
        return None
    return pix.scaled(SET_ICON_SIZE, SET_ICON_SIZE,
                      Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _muted(label) -> None:
    """把说明文字刷成统一的灰。"""
    try:
        label.setTextColor(*MUTED)
    except Exception:  # noqa: BLE001 - 老版本 qfluentwidgets 没这个接口
        pass


class TargetCard(CardWidget):
    """一个可勾选的目标卡片：**套装图标 + 聚落名**。

    ## ★ 布局（2026-10-14 用户第⑨轮调整 —— 现在的样子）

    ::

        ┌────────────────────────────────┐
        │    [图]套装A  [图]套装B          │   ← ★ 套装在上（图标 + 名称）
        │    [图]套装C  [图]套装D          │      ⚠ 高度按**实际行数**（不固定）
        │    [图]套装E  [图]套装F          │
        │    [图]套装G                     │
        │        复生丘原残像聚落           │   ← ★ 名字**自己居中**（不带勾选框）
        │              ☑                 │   ← ★ 勾选框在名字**下面**、单独居中
        └────────────────────────────────┘

    用户原话（按时间顺序）::

        ① 残像聚落显示的卡片，应该展示他可以出的声骸套装图片+名称
        ② 卡片展示为：上方套装图标+套装名称，下方聚落名称
        ③ 放在聚落名称下面，可出套装也去掉，另外整体按聚落出的时间顺序倒叙排序
        ④ 排列要整齐 … 这些说明直接干掉
        ⑤ 名称在上，按钮在下 … 没有对齐 / 像这样对齐
        ⑥ 没修啊，还是不对齐（行距漂移）
        ⑦ 每个卡片背景加上，使用这些套装的角色头像  → **第⑨轮又要求去掉**
        ⑧ 还是没对齐啊 … 陷足流川这是对齐（列位置漂移）
        ⑨ 角色的背景图片还是干掉吧
           ＋ 这种只有一种的，卡片自适应所需，内容并且居中

    ## ★ 第⑨轮的「只有一种的，卡片自适应所需，内容并且居中」

    **背景图片已删**（第⑦轮加的，第⑨轮去掉）——
    连配套的数据文件、读取模块、测试、刷新脚本一起删了，不留死代码。

    高度不再固定 4 行：1 套的卡就是 1 行高。
    但同一网格行里 ``QGridLayout`` 会把卡片拉成等高 ——
    所以**上下各加一个 stretch**，让内容落在中间，
    而不是顶着上边、下面留一个洞（用户圈的正是那个洞）。

    ## ★ 第④轮的「这些说明直接干掉」

    原先名字下面还有两行：``梦枢天罗 · 每日 48 · 3.7 版本`` 和
    ``别名：梦枢天罗 / 梦枢天罗残象聚落``。用户在图里把这两行整块划掉。

    **删掉是有代价的**：别名原本是给"名称对不上时自己改数据文件"用的提示。
    现在改看 :mod:`src.core.nest_sweep.catalog` 里的数据文件注释
    （``_how_to_edit`` 已经写明怎么改 aliases）。
    区域 / 版本也还在数据里，只是不在卡片上显示了。

    ## 勾选框为什么不再放左上角

    第一版按"多选列表惯例"放了左上角，后来用户要求跟名字走
    （第③轮并排 → 第⑤轮改成名字下面）。
    —— 整卡可点仍然不做（会和"点卡片看详情"打架，且误触率高）。
    """

    def __init__(self, target: SweepTarget, checked: bool, on_toggle, parent=None):
        super().__init__(parent)
        self.target = target
        self._on_toggle = on_toggle

        self.setMinimumWidth(CARD_MIN_WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)

        #: ★★ 上下各加一个 stretch —— **内容整体垂直居中**。
        #:
        #: 用户第 ⑨ 轮：「这种只有一种的，卡片自适应所需，**内容并且居中**」。
        #:
        #: 为什么需要：同一网格行里的卡片会被拉成等高（``QGridLayout`` 的
        #: 行为），只有 1 套的那张自然比同行的 7 套卡矮 ——
        #: 不加 stretch 的话内容**顶着上边**，下面留一个大洞（用户圈的正是这个）。
        #: 两头都加 stretch，内容就落在中间。
        box.addStretch(1)

        #: ★ 套装（图标 + 名称）—— 用户 2026-10-13 要求：
        #: 「残像聚落显示的卡片，应该展示他可以出的声骸套装图片+名称」。
        #: 刷之前就知道这趟值不值。
        #: ⚠ 「可出套装」那行小标题**去掉**了（用户第二次要求）——
        #:   图标 + 套装名本身就够说明，多一行标题只是占地方。
        #: ⚠ 高度按**实际行数**（见 :meth:`_sets_rows`）——
        #:   用户第⑨轮：「这种只有一种的，卡片自适应所需，内容并且居中」。
        if target.sets:
            block = self._build_sets_block(target.sets)
            box.addWidget(block)
        box.addSpacing(2)

        # ── 聚落名（**居中一行**）
        #: ★ 用户 2026-10-13 第五次调整：「**名称在上，按钮在下**」。
        #:   原先勾选框和名字**并排**（``[☑ 名称]`` 作为整体居中），
        #:   结果是勾选框占了左边宽度、把名字推右 —— 实测**恒定偏移 +32px**，
        #:   名字不在卡片中线上（用户在图上标了「没有对齐」）。
        #:   改成上下排列后，名字自己居中（偏移 0），勾选框在它正下方。
        self.name_label = StrongBodyLabel(target.name, self)
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignCenter)
        box.addWidget(self.name_label)

        #: ★ 勾选框在**名字下面**、单独居中
        #:
        #: ⚠⚠ 这个勾选框**不是简单地放在 stretch 之间就完事** —— 里面有两层
        #: "假居中"，都是量了才知道的：
        #:
        #:   ① ``CheckBox("")`` 默认控件有 ~57px 宽（**文本区照留**），
        #:      而可见指示器只有 ~20px → 控件居中时指示器**偏左约 18px**。
        #:   ② 压掉文本区之后，指示器**画在固定的左侧位置**（实测中心离
        #:      控件左边缘约 10.5px，**与控件宽度无关**）→ 控件自身仍偏左 4px。
        #:      ``setFixedWidth`` / ``setContentsMargins`` 都改不动这个偏移
        #:      （位置由 paintEvent 直接算）。
        #:
        #:   所以最终做法：**不试图让控件居中**，而是按实测偏移量把控件
        #:   **整体右移**，让"指示器"落在中线上 —— 见 :data:`CHECK_NUDGE`。
        #:
        #:   实测教训（2026-10-13）：我第一版只量了**控件几何**，报告
        #:   "偏移 0、已居中"，但用户在图上标的是「**这个位置偏了**」——
        #:   因为眼睛看到的是**指示器**。另外 ``widget.grab()`` 出的图
        #:   **比控件大**（355 的卡 grab 出 444，有阴影边距），
        #:   拿图里的像素当控件坐标会算出 +40px 的**假偏移**。
        #:   → 量对齐要用 ``mapTo`` 换到**同一坐标系**，并量**看得见的东西**。
        check_row = QHBoxLayout()
        check_row.setContentsMargins(0, 2, 0, 0)
        check_row.setSpacing(0)
        check_row.addStretch(1)
        #: ★ 左侧垫一块 S —— 布局顺序 [stretch, S, 控件, stretch]
        #:   推导（W=控件宽, a=指示器中心离控件左缘, S=垫片）::
        #:       控件左边 = (CW - S - W)/2 + S
        #:       指示器中心 = 控件左边 + a   ← 要等于 CW/2
        #:       ⇒ S = W - 2a
        #:   实测 W=29、a=10.5 ⇒ **S = 8**（见 CHECK_NUDGE）
        check_row.addSpacing(CHECK_NUDGE)
        self.check = CheckBox("", self)
        self.check.setChecked(bool(checked))
        self.check.stateChanged.connect(self._toggled)
        #: 压掉假文本区：控件宽度 = 指示器宽度。
        #: ⚠ Qt 会把过小的值钳到最小宽度（实测 ~29），这没关系 ——
        #:   公式里用的就是钳完之后的真实宽度。
        self.check.setFixedWidth(CHECK_INDICATOR_WIDTH)
        check_row.addWidget(self.check)
        check_row.addStretch(1)
        box.addLayout(check_row)

        #: ★★ 底部 stretch —— 和顶部那个配对，内容才**垂直居中**。
        box.addStretch(1)

    @staticmethod
    def _sets_rows(sets) -> int:
        """这块套装区要占**几行**（按实际数量算）。

        ★ 用户第 ⑨ 轮：「这种只有一种的，卡片自适应所需，内容并且居中」。

        ⚠ 第 ④ 轮当时是**固定 4 行**（为了"排列整齐"）——
        但那让只有 1 套的 5 张梦魇卡各空了 **3 行**（约 105px 的洞）。
        现在改成按实际行数：1 套 → 1 行，7 套 → 4 行。
        同一网格行里的卡片仍会被拉伸到等高（``QGridLayout`` 的行为），
        但**内容会垂直居中**，不再顶在上面留一个大洞。
        """
        if not sets:
            return 0
        return (len(sets) + SET_COLUMNS - 1) // SET_COLUMNS

    @staticmethod
    def _sets_block_height(rows: int) -> int:
        """套装区占 ``rows`` 行时的高度。

        ## ⚠ 这个数必须**精确等于实际内容高度**

        否则 Qt 会把差额摊到各行上（布局会拉伸子项），
        行距就漂了 —— 实测 6 套的卡行距 41/42、7 套的 40/41，
        并排看就是"这一格怎么歪了"。

        算式：``上边距 + N 行 × 行高 + (N-1) 个行距``，
        其中行高 = :data:`SET_ICON_SIZE`（chip 被 ``setFixedHeight`` 锁死）。
        """
        top = 2                                    #: 和 col.setContentsMargins 对齐
        if rows <= 0:
            return top
        return top + rows * SET_ICON_SIZE + (rows - 1) * SET_ROW_GAP

    def _build_sets_block(self, sets) -> QWidget:
        """把「这处能出的套装」画成 图标 + 名称 的**网格**（固定高度）。

        ⚠ 这里**不画**「可出套装」小标题 —— 用户 2026-10-13 明确要求去掉
        （图标 + 套装名本身就够说明，多一行标题只是占地方）。

        ## ★★ 为什么用 ``QGridLayout`` 而不是「每行一个 QHBoxLayout」

        **这是用户第 8 轮的「还是没对齐啊」的根因。**

        每行各自一个 ``QHBoxLayout`` 时，**列宽是由该行内容决定的**：

        ::

            第1行   [茜染怀想之花] [衔梦照世之心]   ← 第1格宽，第2格被推到 x=181
            第2行   [镜影流电之瞬] [羽落空尘之歌]   ← 同上
            第3行   [清邪荡煞之心]                  ← 只剩 1 格，没有第2格约束

        更糟的是**跨行**：第 1 格文字长短不同，第 2 格的 x 就跟着漂。

        实测（我自己的渲染）::

            梦枢天罗  第2列 x = [181, 181, 129]   ★ 漂移 52px
            落渊南丘  第2列 x = [181, 181, 129]   ★ 漂移 52px
            陷足流川  第2列 x = [181, 181, 181]   ✔ 齐（恰好内容一样宽）

        换成 ``QGridLayout``：**列宽由整列最宽的那个决定**，
        所有行的同一列必然落在同一个 x 上 —— 这就是用户要的"对齐"。

        ## 高度按**实际行数**（第 ⑨ 轮改的）

        用户第 ⑨ 轮：「这种只有一种的，卡片自适应所需，内容并且居中」。

        先前是固定 :data:`SET_ROWS` 行 + 补等高占位 —— 那让只有 1 套的
        5 张梦魇卡各留了 **3 行空白**（约 105px 的洞），名字被顶到很下面。
        现在按 :meth:`_sets_rows` 算真实行数，不再补占位。

        > 同一网格行里的卡片仍会被拉成等高（``QGridLayout`` 的行为），
        > 但**内容垂直居中**，所以那张矮卡看起来是"内容居中"而不是"有洞"。
        """
        rows = self._sets_rows(sets)
        holder = QWidget(self)
        holder.setAttribute(Qt.WA_StyledBackground, True)
        #: ★ 高度 = **实际内容高度**（不多不少）
        holder.setFixedHeight(self._sets_block_height(rows))

        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 2, 0, 0)
        #: ⚠ 行距必须和 :meth:`_sets_block_height` 里算的**一致**，
        #:   否则固定高度和实际内容高度对不上，Qt 会把差额摊到各行上，
        #:   行距就漂了（实测 6 套的卡行距 41/42、7 套的 40/41）。
        grid.setVerticalSpacing(SET_ROW_GAP)
        grid.setHorizontalSpacing(SET_COL_GAP)
        #: 多出来的一列用来"吸走"剩余宽度，免得两列被拉开
        grid.setColumnStretch(SET_COLUMNS, 1)

        for i, name in enumerate(sets):
            chip = self._build_set_chip(name, holder)
            #: ★ 每个格子**固定高度** —— 不让它被垂直拉伸。
            #:   拉伸量各卡不同（行数 1/3/4 不等），会直接把行距拉歪。
            chip.setFixedHeight(SET_ICON_SIZE)
            grid.addWidget(chip, i // SET_COLUMNS, i % SET_COLUMNS)
        return holder

    def _build_set_chip(self, name: str, parent) -> QWidget:
        """一个套装 = 小图标 + 名字。"""
        chip = QWidget(parent)
        chip.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        pix = set_icon_pixmap(name)
        if pix is not None:
            icon = QLabel(chip)
            icon.setFixedSize(SET_ICON_SIZE, SET_ICON_SIZE)
            icon.setPixmap(pix)
            icon.setToolTip(name)
            lay.addWidget(icon)

        label = CaptionLabel(name, chip)
        label.setToolTip(name)
        lay.addWidget(label)
        lay.addStretch(1)
        return chip

    def _toggled(self, _state: int) -> None:
        self._on_toggle(self.target.key, self.check.isChecked())

    def set_checked(self, checked: bool, *, silent: bool = False) -> None:
        """外部改勾选。``silent=True`` 时不回调（用于"全选/全不选"批量设置）。"""
        if silent:
            self.check.blockSignals(True)
        self.check.setChecked(bool(checked))
        if silent:
            self.check.blockSignals(False)

    def is_checked(self) -> bool:
        return self.check.isChecked()


class NestSweepWidget(ScrollArea):
    """扫荡残像聚落面板：目标卡片墙 + 全选/反选 + 运行/停止 + 进度。"""

    POLL_MS = 300

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._host = get_host()
        self._targets: tuple[SweepTarget, ...] = ()
        self._cards: dict[str, TargetCard] = {}
        #: 勾选集合（**内存里就是这份**；每次改动立刻落盘）
        self._selected: set[str] = set()

        self.setObjectName("nest_sweep_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget(self)
        page.setObjectName("nest_sweep_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_run_card(page))
        layout.addWidget(self._build_targets_card(page))
        layout.addStretch(1)
        self.setWidget(page)

        self._reload()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)
        self._poll()

    # ------------------------------------------------------------------ 清单
    def _reload(self) -> None:
        """读清单 + 已存勾选，重建卡片墙。"""
        self._targets = load_catalog()
        try:
            saved = set(load_selection(self._targets))
        except Exception:  # noqa: BLE001 - 设置读不出来不该挡住页面
            saved = set()
        #: ★ 第一次打开（盘上什么都没存）时**默认全选**。
        #:   用户要的是"一键勾选全部"，那默认就替他勾上 —— 想少刷再取消。
        #:   ⚠ 只有"从来没存过"才默认全选；用户取消过就尊重他的选择，
        #:     否则每次开工具页都把他取消的又勾回来。
        self._selected = saved if self._has_saved_selection() else {
            t.key for t in self._targets}
        self._rebuild_cards()

    def _has_saved_selection(self) -> bool:
        """盘上有没有存过勾选？（用来区分"没存过"和"存了个空"）"""
        try:
            from ....core import tool_settings

            saved = tool_settings.load("nest_sweep")
            return "selected" in saved
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ 构建
    def _build_run_card(self, parent) -> ConfigCard:
        card = ConfigCard(
            "扫荡残像聚落",
            "勾选要刷的目标，点「运行」后**按下面的顺序一个一个刷**"
            "（顺序 = 卡片顺序 = **版本从新到旧**，同一版本内看 order）。",
            parent,
        )

        # ── 勾选控制行
        pick_row = QHBoxLayout()
        pick_row.setSpacing(10)
        self.select_all_button = PushButton("全选", card)
        self.select_all_button.clicked.connect(self._select_all)
        pick_row.addWidget(self.select_all_button)

        self.clear_button = PushButton("全不选", card)
        self.clear_button.clicked.connect(self._clear_all)
        pick_row.addWidget(self.clear_button)

        self.invert_button = PushButton("反选", card)
        self.invert_button.clicked.connect(self._invert)
        pick_row.addWidget(self.invert_button)

        pick_row.addSpacing(10)
        self.selection_label = CaptionLabel(selection_summary([], ()), card)
        _muted(self.selection_label)
        pick_row.addWidget(self.selection_label, 1)
        card.body.addLayout(pick_row)

        # ── 运行控制行
        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        self.run_button = PrimaryPushButton("运行", card)
        self.run_button.clicked.connect(self._run)
        run_row.addWidget(self.run_button)

        self.stop_button = PushButton("停止", card)
        self.stop_button.clicked.connect(self._stop)
        run_row.addWidget(self.stop_button)

        self.state_label = CaptionLabel("引擎：未启动 · 点「运行」会先加载引擎再开跑", card)
        _muted(self.state_label)
        run_row.addWidget(self.state_label, 1)
        card.body.addLayout(run_row)

        # ── 进度行（跑起来才有内容）
        self.progress_label = CaptionLabel("", card)
        _muted(self.progress_label)
        self.progress_label.setWordWrap(True)
        card.body.addWidget(self.progress_label)

        return card

    def _build_targets_card(self, parent) -> ConfigCard:
        """卡片墙那块。

        ★ 用户第 ⑩ 轮：标题从「可以刷的目标」**改成「残像聚落」**，
        下面那整段说明文字**干掉**。

        > ⚠ **删说明是有代价的**（和卡片上删「别名：…」时一样）：
        > 那段文字原本是唯一一处告诉用户"名称对不上时改
        > ``wuwa_sweep_targets.json`` 的 aliases"的地方。
        > 现在界面上**没有任何提示**了 —— 改数据文件的知识只在
        > :mod:`src.core.nest_sweep.catalog` 的模块文档里。
        > 真出问题时用户不会知道能自己改。
        """
        card = ConfigCard("残像聚落", "", parent)
        self.targets_host = QWidget(card)
        self.targets_grid = QGridLayout(self.targets_host)
        self.targets_grid.setContentsMargins(0, 4, 0, 0)
        self.targets_grid.setHorizontalSpacing(12)
        self.targets_grid.setVerticalSpacing(12)
        card.add(self.targets_host)
        return card

    def _rebuild_cards(self) -> None:
        """按清单重建卡片墙（清空旧卡片）。"""
        self._cards.clear()
        while self.targets_grid.count():
            item = self.targets_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        #: ★ 2026-10-13 用户要求：**不再区分残像聚落 / 梦魇聚落，统一叫残像聚落**。
        #:   所以这里**不再按 kind 分段**，所有目标平铺成一张卡片墙
        #:   （原先分两段还各加一行小标题，现在那两行也去掉了）。
        for index, target in enumerate(self._targets):
            card = TargetCard(target, target.key in self._selected,
                              self._on_card_toggle, self.targets_host)
            self.targets_grid.addWidget(card, index // CARD_COLUMNS,
                                        index % CARD_COLUMNS)
            self._cards[target.key] = card

        self._refresh_selection_label()

    # ------------------------------------------------------------------ 勾选
    def _on_card_toggle(self, key: str, checked: bool) -> None:
        """单张卡被勾/取消 —— 立刻落盘（用户切页 / 关程序都不丢）。"""
        if checked:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        self._persist()
        self._refresh_selection_label()

    def _select_all(self) -> None:
        """★ 一键勾选全部（用户明确要的功能）。"""
        self._selected = {t.key for t in self._targets}
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _clear_all(self) -> None:
        self._selected.clear()
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _invert(self) -> None:
        self._selected = {t.key for t in self._targets
                          if t.key not in self._selected}
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _apply_to_cards(self) -> None:
        """把 ``self._selected`` 刷到每个勾选框上。

        ⚠ 必须 ``silent=True``：否则每张卡都会回调一次
        :meth:`_on_card_toggle`，50 张卡就是 50 次存盘 + 50 次刷新
        —— 而且中途的回调会拿**半更新**的集合去写盘。
        """
        for key, card in self._cards.items():
            card.set_checked(key in self._selected, silent=True)

    def _persist(self) -> None:
        try:
            save_selection(self._selected, self._targets)
        except Exception as exc:  # noqa: BLE001 - 存不下来不该挡住操作
            self._toast("勾选存不下来", str(exc), error=True)

    def _refresh_selection_label(self) -> None:
        self.selection_label.setText(
            selection_summary(self._selected, self._targets))
        #: 没勾任何东西时「运行」点不动 —— 免得点了才发现没勾
        self.run_button.setEnabled(bool(self._selected) and not self._running())

    # ------------------------------------------------------------------ 运行
    def _running(self) -> bool:
        return bool(self._host.running_task or self._host.pending_start)

    def _run(self) -> None:
        """把勾选**当场**变成计划，注入任务，启动。"""
        plan = build_plan(self._selected, self._targets)
        if not len(plan):
            self._toast("还没勾选", "先在下面勾选要刷的目标，再点运行")
            return

        def configure(task) -> None:
            #: ★ 把用户**此刻看到的**那份计划交给任务 ——
            #:   任务自己也会读盘兜底（冷启动场景），但界面上这份优先，
            #:   否则"我刚取消了它还是刷了"就会变成很难解释的现象。
            task.sweep_plan = plan

        err = self._host.start_task(TASK_KEY, configure=configure)
        if err:
            self._toast("启动失败", err, error=True)
            return
        self.progress_label.setText(f"已交给引擎：{plan.describe()}")
        self._refresh_selection_label()

    def _stop(self) -> None:
        err = self._host.stop_task()
        if err:
            self._toast("停止失败", err, error=True)
        else:
            self.progress_label.setText("已请求停止")

    # ------------------------------------------------------------------ 轮询
    def _poll(self) -> None:
        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error

        if err and state == "error":
            self.state_label.setText(f"引擎：启动失败 —— {err}（点「运行」可重试）")
        elif state == "booting":
            self.state_label.setText(
                "引擎：正在后台启动 ok-ww…就绪后自动开始（首次加载 OCR 会慢一些）")
        elif state == "running":
            self.state_label.setText(f"引擎：运行中 —— {running}（点「停止」结束）")
        elif state == "ready":
            self.state_label.setText("引擎：就绪 · 点「运行」开始扫荡")
        else:
            self.state_label.setText("引擎：未启动 · 点「运行」会先加载引擎再开跑")

        self.stop_button.setEnabled(bool(running) or bool(pending))
        for button in (self.select_all_button, self.clear_button, self.invert_button):
            button.setEnabled(not running)
        self._refresh_selection_label()

        #: 跑的时候把引擎那边的进度抄过来（任务用 ``info_set`` 写的）
        self._refresh_progress(running)

        self._host.poll_done()

    def _refresh_progress(self, running: str | None) -> None:
        """把 ok-ww 任务里 ``info`` 的进度抄到界面上。"""
        if not running:
            return
        try:
            task = self._host.find_task(TASK_KEY)
            info = getattr(task, "info", None) if task is not None else None
            if not isinstance(info, dict):
                return
            parts = []
            total = info.get("扫荡目标总数")
            done = info.get("扫荡完成数")
            if total:
                parts.append(f"进度 {done or 0}/{total}")
            current = info.get("当前进度")
            if current:
                parts.append(str(current))
            result = info.get("扫荡结果")
            if result:
                parts.append(str(result))
            if parts:
                self.progress_label.setText(" · ".join(parts))
        except Exception:  # noqa: BLE001 - 抄进度失败不该让界面崩
            pass

    # ------------------------------------------------------------------ 杂项
    def _toast(self, title: str, message: str = "", *, error: bool = False) -> None:
        try:
            window = self.window()
            if error:
                InfoBar.error(title, message, duration=6000, parent=window)
            else:
                InfoBar.warning(title, message, duration=6000, parent=window)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.GAME,
    name="扫荡残像聚落",
    description="展示当前版本的残像聚落（含能出的声骸套装），勾选后按顺序逐个扫荡",
    icon_name="GAME",
    coming_soon=False,
)
class NestSweepTool(BaseTool):
    key = "nest_sweep"
    name = "扫荡残像聚落"
    description = "勾选残像聚落，按顺序一个一个自动扫荡"
    version = "0.1.0"
    tags = ("自动", "声骸", "日常")
    coming_soon = False
    #: 可以在任务流程里跑（ok-ww 那边已注册 MyToolsNestSweepTask）
    supports_task_run = True
    icon_path = str(paths.resource_dir("assets", "icons", "nest_sweep.png"))

    def create_widget(self, parent=None):
        return NestSweepWidget(self.meta(), parent)

    # ---------------------------------------------------------------- 任务系统
    def create_task_runner(self, options: dict, log, should_stop):
        """给「任务流程」用：把 ok-ww 宿主上的扫荡任务包装成同步 runner。

        ## ★ 勾选从哪来（没有工具页的时候）

        任务流程跑起来**可能根本没打开过工具页**（用户刚开机就跑流程）。
        所以勾选**不从编排里读**，而是让任务自己读
        ``tool_settings.json`` 里工具页存的那份
        （见 ``MyToolsNestSweepTask._resolve_plan`` 的兜底分支）。

        这样"从任务页跑"和"从工具页点运行"用的就是**同一套勾选** ——
        本项目在声骸强化那边立下的规矩：两条入口的规则必须一致。
        """
        plan = build_plan(load_selection(self._targets_for_log()))
        if not len(plan):
            #: ⚠ 说清楚"为什么没跑"，而不是静默跑一个空任务
            log("⚠ 扫荡残像聚落：一个目标都没勾选 —— 先去工具页勾选，再重跑这条流程")
        else:
            log(f"扫荡残像聚落：{plan.describe()}（顺序按清单）")

        from .runner import NestSweepRunner

        return NestSweepRunner(log=log, should_stop=should_stop)

    @staticmethod
    def _targets_for_log():
        """读清单给日志用；读不出来返回空（日志少一行，不是错误）。"""
        try:
            return load_catalog()
        except Exception:  # noqa: BLE001
            return ()
