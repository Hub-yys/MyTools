# -*- coding: utf-8 -*-
"""主题皮肤页面 —— 左侧边栏点「主题皮肤」，**右侧以卡片形式**展示所有主题。

## 用户要求（2026-10-05）

    1. "皮肤加在左侧边栏，不是左下角"        ← 做成侧栏一个**导航项**
    2. "右边显示所有的皮肤，以卡片的形式展示"  ← 右侧页面 = 卡片网格
    3. "以DSH这个主题皮肤为例（液态玻璃主题）" ← 卡片本身也要玻璃感

## ★ 2026-10-30 改名为「主题皮肤」+ 加角色主题

用户：

    "改进皮肤功能，参考dsh-pet，和鸣潮角色抽卡动画，
     把角色抽卡动画做进皮肤里，并把皮肤改名为主题皮肤，
     以爱弥斯为例，先做一个看看"

页面上现在**两组卡片**：

    角色主题    带抽卡动画（见 :mod:`src.gui.gacha_reveal`）。
                点「使用这款」→ **先播开卡动画，再落主题**。
    配色主题    原来那 6 款纯配色（晨雾/樱雾/深空/星云/幽海/熔火）。

## ⚠⚠ 上一版的 bug：预览条画不出来

预览条用 ``s['bg']`` 直接拼进 QSS —— 而 ``bg`` 现在是**渐变的
stop 列表** ``[(0.0, '#0B1026'), ...]``，拼出来是::

    stop:0 [(0.0, '#0B1026'), (0.45, '#141A38'), (1.0, '#0A0E1F')]

**整个 Python 列表被当字符串塞进去了** —— QSS 解析失败，
预览条和卡片背景**全画不出来**（实测截图：卡片区域是纯灰）。

→ 现在统一走 :func:`src.core.skins.gradient_qss` 拼。

## 一张卡片长什么样

::

    ┌───────────────────────────┐
    │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │  ← 预览条（真的画该主题的渐变）
    │  深空玻璃          [使用中] │
    │  DSH 同款：深邃蓝黑渐变…    │
    │  ● #4A9EFF                │  ← 主色点
    │  ┌─────────────────────┐  │
    │  │      使用这款        │  │
    │  └─────────────────────┘  │
    └───────────────────────────┘

角色主题的卡片多一块：**头像缩略图 + 角色名 + 「开卡动画」标记**。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .compat import ScrollArea
from ..core import skins

logger = logging.getLogger(__name__)

#: 卡片宽度
CARD_WIDTH = 268
#: 预览条高度
PREVIEW_H = 88
#: 一行几张
PER_ROW = 3


class SkinCard(QWidget):
    """一款皮肤的卡片（预览 + 名字 + 说明 + 主色 + 使用按钮）。"""

    chosen = Signal(str)                       #: 皮肤 id

    def __init__(self, skin: dict, *, active: bool = False, parent=None):
        super().__init__(parent)
        self._skin = skin
        self._is_active = bool(active)          #: 测试要看这个
        self.setObjectName("skinCard")
        self.setFixedWidth(CARD_WIDTH)
        self._build(active)

    @staticmethod
    def _load_avatar(skin: dict) -> QPixmap | None:
        """加载角色主题的头像（``assets/<avatar>``）。拿不到返回 None。

        ⚠ 拿不到就**不画**（不留空洞）—— 和别的"图标缺失"处理一致。
        """
        rel = str(skin.get("avatar") or "")
        if not rel:
            return None
        try:
            from ..core import paths  # noqa: PLC0415 - 避免循环导入

            #: 项目根目录下的 assets/（``resource_dir`` 就是项目根/打包后的根）
            path = paths.resource_dir() / "assets" / rel
            if not path.is_file():
                logger.warning("主题皮肤：找不到头像 %s", path)
                return None
            pix = QPixmap(str(path))
            return None if pix.isNull() else pix
        except Exception:  # noqa: BLE001 - 加载失败不该让页面挂掉
            logger.warning("主题皮肤：加载头像失败", exc_info=True)
            return None

    def set_active(self, active: bool) -> None:
        """★ 切换壁纸后**原地更新**这个卡片的使用中状态。

        ## ★★★ 2026-11-01 为什么不重建卡片

        用户截图：画面已经是坎特蕾拉，但列表里使用中还在守岸人。

        之前是靠 `_refresh_wallpapers()` **整个重建**卡片列表，
        但 Qt 的 `deleteLater()` 是**排队**的，加上 grid 布局
        重排 —— 新旧卡片可能重叠，看到的是旧的。

        → 改成**原地改状态**：不删不建，只改按钮文字 + 徽章 +
          边框颜色。这样 100% 可靠，也没有重建开销。
        """
        try:
            new_active = bool(active)
            if new_active == self._is_active:
                return
            self._is_active = new_active
            #: ① 徽章
            badge = getattr(self, "_badge", None)
            if badge is not None:
                badge.setVisible(new_active)
            #: ② 按钮文字 + 信号参数
            btn = getattr(self, "_btn", None)
            if btn is not None:
                btn.setText("取消使用" if new_active else "使用这个壁纸")
                try:
                    btn.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
                wp_id = str(self._info.get("id") or "")
                btn.clicked.connect(
                    lambda _=False, i=wp_id, a=new_active:
                    self.chosen.emit("" if a else i))
            #: ③ 边框/强调色
            try:
                from ..core import skins

                ui = skins.ui_tokens(skins.active_skin())
                accent = ui["primary"] if new_active else ui["border"]
                self.setStyleSheet(
                    f"border: 1px solid {accent};"
                    f" border-radius: 12px;")
            except Exception:  # noqa: BLE001
                pass
            self.update()
        except Exception:  # noqa: BLE001
            logger.debug("壁纸卡片：更新状态失败", exc_info=True)

    def _build(self, active: bool) -> None:
        s = self._skin
        #: ★★★ 卡片上的**文字**用**当前生效皮肤**的颜色，不是被预览那个。
        #:
        #: ⚠⚠ 这里踩过坑：一开始用 ``s['text']``（被预览皮肤的文字色）——
        #: 深色皮肤的文字是**浅色**，画在**当前皮肤**（也许是浅色）的页面底上
        #: → **字几乎看不见**（用户截图里「深空玻璃」那几款就是这个）。
        #:
        #: 道理很简单：卡片坐落在**当前皮肤的页面**上，
        #: 文字对比度该跟**页面**算，不该跟预览条算。
        ui = skins.current_skin()
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)

        #: ── ① 预览条：**真的画这个主题的渐变**
        #:
        #: ⚠ 必须用 ``gradient_qss`` 拼 —— 直接把 ``bg``（列表）
        #: 塞进 QSS 会解析失败、什么都画不出来（上一版的 bug）。
        #: ★ 角色主题在预览条右侧再叠一个**角色头像**（看得出是谁的主题）。
        preview = QWidget(self)
        preview.setObjectName("skinPreview")
        preview.setFixedHeight(PREVIEW_H)
        preview.setStyleSheet(
            f"#skinPreview {{"
            f" background: {skins.gradient_qss(s)};"
            f" border-radius: 8px;"
            f" border: 1px solid {s['border']}; }}")
        box.addWidget(preview)

        #: 头像**浮在预览条上**（用 preview 当父控件 + 绝对定位）。
        #: 不用布局 —— 那样会把预览条撑高、和别的卡片对不齐。
        if skins.is_character_skin(s):
            avatar = QLabel(preview)
            avatar.setFixedSize(58, 76)
            avatar.setScaledContents(True)
            avatar.setStyleSheet("background: transparent;")
            pix = self._load_avatar(s)
            if pix is not None and not pix.isNull():
                avatar.setPixmap(pix)
                avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
                #: 靠右、垂直居中
                avatar.move(CARD_WIDTH - 14 * 2 - 58, (PREVIEW_H - 76) // 2)
                avatar.raise_()

        #: ── ② 名字 + 「使用中」
        row = QHBoxLayout()
        row.setSpacing(6)
        name = QLabel(s["name"], self)
        name.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {ui['text']};")
        row.addWidget(name)
        row.addStretch(1)
        if active:
            badge = QLabel("使用中", self)
            self._badge = badge
            badge.setObjectName("skinBadge")
            badge.setStyleSheet(
                f"#skinBadge {{ background: {s['primary']}; color: #ffffff;"
                f" font-size: 11px; font-weight: bold;"
                f" padding: 2px 9px; border-radius: 9px; }}")
            row.addWidget(badge)
        box.addLayout(row)

        #: ── ②-b 角色主题多一行小标记（「爱弥斯 · 开卡动画」）
        if skins.is_character_skin(s):
            tag_row = QHBoxLayout()
            tag_row.setSpacing(6)
            tag = QLabel("开卡动画", self)
            tag.setStyleSheet(
                f"background: {s['primary']}; color: #ffffff;"
                f" font-size: 10px; font-weight: bold;"
                f" padding: 1px 8px; border-radius: 8px;")
            tag_row.addWidget(tag)
            who = QLabel(str(s.get("character") or ""), self)
            who.setStyleSheet(f"font-size: 11px; color: {ui['dim']};")
            tag_row.addWidget(who)
            tag_row.addStretch(1)
            box.addLayout(tag_row)

        #: ── ③ 说明（用**当前皮肤**的次要色 —— 见上面 ui 的说明）
        desc = QLabel(s.get("desc") or "", self)
        desc.setWordWrap(True)
        desc.setMinimumHeight(34)               #: 高度对齐，卡片不会参差
        desc.setStyleSheet(f"font-size: 12px; color: {ui['dim']};")
        box.addWidget(desc)

        #: ── ④ 主色点 + 色值
        color_row = QHBoxLayout()
        color_row.setSpacing(7)
        dot = QLabel(self)
        dot.setFixedSize(14, 14)
        dot.setStyleSheet(
            f"background: {s['primary']}; border-radius: 7px;")
        color_row.addWidget(dot)
        hexlab = QLabel(s["primary"].upper(), self)
        hexlab.setStyleSheet(
            f"font-size: 11px; color: {ui['dim']};"
            f" font-family: Consolas, monospace;")
        color_row.addWidget(hexlab)
        color_row.addStretch(1)
        box.addLayout(color_row)

        #: ── ⑤ 按钮
        #:
        #: ★★ 2026-10-30 角色主题**即使正在使用也要能点**。
        #:
        #: 原来「使用中」就 ``setEnabled(False)``（置灰点不了）。
        #: 用户报了"哪里播放抽卡动画了？" —— 因为爱弥斯主题已经被应用过、
        #: 按钮显示"使用中"点不动，**动画那条路根本没被走到**。
        #:
        #: 现在角色主题在使用中时按钮写「重播开卡动画」并且**可点**：
        #: 点了只播动画、不重复应用主题（``_on_chosen`` 里
        #: ``is_current`` 为真时仍然播，见那里的说明）。
        is_char = skins.is_character_skin(s)
        if active:
            label = "重播开卡动画" if is_char else "使用中"
        else:
            label = "使用这款"
        btn = QPushButton(label, self)
        btn.setObjectName("skinUseBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setEnabled(is_char or not active)
        if active and not is_char:
            #: ⚠ 边框/文字也要用**当前皮肤**的色（用被预览皮肤的会糊在一起）
            btn.setStyleSheet(
                f"#skinUseBtn {{ font-size: 12px; padding: 7px 0;"
                f" border-radius: 6px; background: transparent;"
                f" border: 1px solid {ui['border']}; color: {ui['dim']}; }}")
        else:
            btn.setStyleSheet(
                f"#skinUseBtn {{ font-size: 12px; padding: 7px 0;"
                f" border-radius: 6px; border: none;"
                f" background: {s['primary']}; color: #ffffff;"
                f" font-weight: bold; }}")
        btn.clicked.connect(lambda: self.chosen.emit(s["id"]))
        box.addWidget(btn)

        #: ── 卡片本身：半透明玻璃 + 浅色细边
        #: （选中的用主色描边，一眼看出是哪个）
        accent = s["primary"] if active else s["border"]
        self.setStyleSheet(
            f"#skinCard {{ border-radius: 12px;"
            f" border: 2px solid {accent};"
            f" background: {s['card']}; }}")


class WallpaperCard(QWidget):
    """★ 一个 Wallpaper Engine 壁纸的卡片（缩略图 + 标题 + 类型 + 使用按钮）。

    ## ★★★ 2026-10-31 用户

        > 这个不能像插件一样接入 Wallpaper Engine 吗

    这是"壁纸库"里的一格。显示：缩略图、标题、类型标记、使用按钮。

    ``supported`` 为 False 的（scene / web 型）**按钮禁用**并标注原因 ——
    它们需要 WebGL 渲染引擎，本模块不提供。
    """

    #: 用户点了「使用这个壁纸」（参数是壁纸 id / 空串=关闭）
    chosen = Signal(str)

    def __init__(self, info: dict, *, active: bool = False,
                 parent=None):
        super().__init__(parent)
        self._info = info
        self._is_active = bool(active)     #: 测试要看这个
        #: ★ 原地更新用的引用（set_active）
        self._badge = None
        self._btn = None
        self.setObjectName("wallpaperCard")
        self.setFixedWidth(CARD_WIDTH)
        self._build(active)

    def _build(self, active: bool) -> None:
        info = self._info
        ui = skins.current_skin()
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)

        #: ── ① 缩略图（WE 的 preview.jpg）
        preview = QLabel(self)
        preview.setObjectName("wpPreview")
        preview.setFixedHeight(PREVIEW_H)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet(
            "#wpPreview { background: rgba(0, 0, 0, 0.35);"
            " border-radius: 8px; }")
        pp = str(info.get("preview_path") or "")
        pix = QPixmap(pp) if pp else QPixmap()
        if not pix.isNull():
            preview.setPixmap(pix.scaled(
                CARD_WIDTH - 24, PREVIEW_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation))
        else:
            preview.setText("（无缩略图）")
        box.addWidget(preview)

        #: ── ② 标题 + 「使用中」
        row = QHBoxLayout()
        row.setSpacing(6)
        name = QLabel(info.get("title") or "（未命名）", self)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {ui['text']};")
        row.addWidget(name, 1)
        if active:
            badge = QLabel("使用中", self)
            self._badge = badge
            badge.setStyleSheet(
                f"background: {ui['primary']}; color: #fff;"
                f" font-size: 10px; font-weight: bold;"
                f" padding: 2px 8px; border-radius: 8px;")
            row.addWidget(badge)
        box.addLayout(row)

        #: ── ③ 类型标记（video ✅ / scene ❌）
        wp_type = str(info.get("type") or "?")
        ok = bool(info.get("supported"))
        tag = QLabel(
            ("▶ 视频" if wp_type == "video" else f"{wp_type}") if ok
            else f"{wp_type}（需 WebGL，暂不支持）", self)
        tag.setStyleSheet(
            f"font-size: 10px; color: {ui['dim']};")
        box.addWidget(tag)

        #: ── ④ 按钮
        if ok:
            btn = QPushButton("取消使用" if active else "使用这个壁纸", self)
            self._btn = btn
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 12px; padding: 6px 0;"
                f" border-radius: 6px; border: none;"
                f" background: {ui['primary']}; color: #fff;"
                f" font-weight: bold; }}")
            btn.clicked.connect(
                lambda: self.chosen.emit("" if active
                                         else str(info.get("id") or "")))
        else:
            btn = QPushButton("不支持", self)
            btn.setEnabled(False)
            btn.setStyleSheet(
                f"QPushButton {{ font-size: 12px; padding: 6px 0;"
                f" border-radius: 6px; background: transparent;"
                f" border: 1px solid {ui['border']};"
                f" color: {ui['dim']}; }}")
        box.addWidget(btn)

        accent = ui["primary"] if active else ui["border"]
        self.setStyleSheet(
            f"#wallpaperCard {{ border-radius: 12px;"
            f" border: 2px solid {accent};"
            f" background: {ui['card']}; }}")


class SkinInterface(ScrollArea):
    """★ 主题皮肤页面（侧栏导航项 → 右边整页卡片）。

    ## ⚠ 必须继承 ``ScrollArea`` 并 ``setWidget(view)``

    我第一版做成裸 ``QWidget`` —— 结果**整页不显示**（实测
    ``100x30``、``isVisible()=False``，切过去了也是空白）。

    这是本项目的**固定写法**（HomeInterface / ConfigInterface /
    TasksInterface 都一样）::

        self.setWidget(view)          # 内层 view 交给滚动区托管
        self.setWidgetResizable(True) # 跟着窗口伸缩
        setAttribute(WA_StyledBackground, True)
        setStyleSheet("#XxxInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    ## ★ 2026-10-30 两组卡片

    ``角色主题`` 带抽卡动画（点使用 → 先播动画再落主题）；
    ``配色主题`` 是原来那 6 款纯配色。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SkinInterface")
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cards: list[SkinCard] = []
        #: 正在播的抽卡动画（防止连点开出两层）
        self._reveal = None

        view = QWidget(self)
        view.setObjectName("skinView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        title = QLabel("主题皮肤", view)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        s = skins.current_skin()
        hint = QLabel(
            "配色主题：点一下立刻生效，所有选择都会记住。\n"
            "壁纸：从本机 Wallpaper Engine 创意工坊读取（视频型可播放，"
            "Scene 型需要 WebGL 渲染，暂不支持）。",
            view)
        hint.setStyleSheet(f"font-size: 13px; color: {s['dim']};")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(10)

        #: ══════════════════════════════════════════════════════════
        #: ★★★ 2026-10-31 用户：「删掉配色主题，只留壁纸」
        #:
        #: 原来这里有「角色主题」和「配色主题」两组可选卡片，
        #: 但配色主题的背景是**不透明渐变**，会把壁纸整个盖住 ——
        #: 用户选了配色主题就看不到壁纸了（截图报的就是这个）。
        #:
        #: 现在只留**一款基础主题**（``glass``），它不参与"选择"，
        #: 只是提供配色令牌（文字色/强调色/卡片边框）。
        #: 界面背景完全交给壁纸。
        #:
        #: ⚠ 代码保留（不是删掉），以后想恢复多主题把下面几行注释解开，
        #: 并把 ``skins.SKINS`` 里的主题加回去（备份在
        #: ``src/core/skins.py.bak_before_remove_themes``）。
        #: ══════════════════════════════════════════════════════════
        #: ★★★ 2026-11-01 用户：「把标记的干掉，只把壁纸留着」
        #:
        #: 删掉了两块：
        #:   ① **当前主题**（标题 + 说明）—— 只留一款主题，没得选，纯占地方
        #:   ② **壁纸外观（液态玻璃）** 的 10 个滑块 —— 参数已对齐 DSH，
        #:      普通用户不需要调；真要改可以手编辑
        #:      ``data/wallpaper_settings.json``
        #:
        #: 现在这一页只有**壁纸库**一个内容。
        #:
        #: ⚠ 保留属性（refresh 里还会用到，避免 AttributeError）
        self._base_title = QLabel("当前主题", view)
        self._base_title.setVisible(False)
        layout.addWidget(self._base_title)

        self._base_hint = QLabel("", view)
        self._base_hint.setVisible(False)
        layout.addWidget(self._base_hint)

        self._char_title = QLabel("角色主题", view)
        self._char_title.setVisible(False)
        layout.addWidget(self._char_title)
        char_grid = QGridLayout()
        layout.addLayout(char_grid)
        self._char_grid = char_grid

        self._color_title = QLabel("配色主题", view)
        self._color_title.setVisible(False)
        layout.addWidget(self._color_title)
        grid = QGridLayout()
        layout.addLayout(grid)
        self._grid = grid

        #: 壁纸外观设置 —— **不显示**（参数用 DSH 默认值）
        self._glass_sliders: dict = {}

        #: ★★★ 2026-10-31 **Wallpaper Engine 壁纸库**（用户：
        #: > 这个不能像插件一样接入 Wallpaper Engine 吗）
        #:
        #: 现在是这一页**唯一**的内容。
        #: ══════════════════════════════════════════════════════════
        self._wp_title = QLabel("Wallpaper Engine 壁纸", view)
        self._wp_title.setStyleSheet(
            "font-size: 15px; font-weight: bold; margin-top: 4px;")
        layout.addWidget(self._wp_title)

        self._wp_hint = QLabel("", view)
        self._wp_hint.setStyleSheet(f"font-size: 12px; color: {s['dim']};")
        self._wp_hint.setWordWrap(True)
        layout.addWidget(self._wp_hint)

        wp_grid = QGridLayout()
        wp_grid.setHorizontalSpacing(16)
        wp_grid.setVerticalSpacing(16)
        wp_grid.setAlignment(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignTop)
        layout.addLayout(wp_grid)
        self._wp_grid = wp_grid

        layout.addStretch(1)

        #: ⚠ 跟其它页面一样 —— 不写这几行整页不显示（见类文档）
        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#SkinInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        self.refresh()

    def refresh(self) -> None:
        """刷新页面。

        ## ★ 2026-10-31 简化

        配色主题删掉后，这里不再画主题卡片 —— 只更新"当前主题"那行文字，
        然后刷新壁纸卡片。

        ⚠ 原来那套卡片创建逻辑整段删了（不是注释掉）——
        留着会让人以为还有多主题可选。想恢复见
        ``src/core/skins.py.bak_before_remove_themes``。
        """
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()

        #: 清掉残留占位（旧版留下的空 grid）
        for box in (self._char_grid, self._grid):
            while box.count():
                item = box.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()

        cur = skins.current_skin()
        try:
            self._base_hint.setText(
                f"{cur['name']} —— {cur.get('desc', '')}\n"
                f"界面背景由下面的壁纸决定；没选壁纸时用这层深色底。")
        except (RuntimeError, AttributeError):
            pass

        #: ★ 壁纸库
        self._refresh_wallpapers()

        #: ★★★ 2026-10-31 Wallpaper Engine 壁纸库
        self._refresh_wallpapers()

    def _build_glass_settings(self, view, s: dict, layout) -> QWidget:
        """★ 壁纸外观设置面板（参数照抄 DSH 插件）。

        ## 参数来源

        ``dsh-plugin-wallpaper-engine/lib/settings-schema.js``::

            scrim: 0.25             整体暗化 0~1
            border: 0.35            边框 0~1
            blur: 16                面板雾化 0~60
            wallpaperBlur: 0        壁纸模糊 0~60
            backgroundBrightness: 100   壁纸亮度 40~160
            backgroundContrast: 100     壁纸对比度 40~200
            backgroundSaturate: 100     壁纸饱和度 0~200
            wallpaperOpacity: 100       壁纸不透明度 0~90
            glassAlpha: 20          玻璃透明度 0~100
            glassFidelity: 100      玻璃保真度 0~100

        ## 为什么用滑块

        这些参数**调一下就想看效果**，输入框要回车才生效，滑块即时。
        """
        from PySide6.QtWidgets import (
            QCheckBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )
        from qfluentwidgets import Slider

        box = QWidget(view)
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 8, 0, 8)
        v.setSpacing(6)

        title = QLabel("壁纸外观（液态玻璃）", box)
        title.setStyleSheet(
            "font-size: 15px; font-weight: bold; margin-top: 6px;")
        v.addWidget(title)

        hint = QLabel(
            "参数和默认值来自 DSH 壁纸引擎插件（settings-schema.js）。"
            "调完立即生效。", box)
        hint.setStyleSheet(f"font-size: 12px; color: {s['dim']};")
        hint.setWordWrap(True)
        v.addWidget(hint)

        try:
            from ..core import wallpaper_settings as WS
        except Exception:  # noqa: BLE001
            WS = None

        self._glass_sliders: dict = {}

        #: 显示顺序（也是重要性的顺序）
        #: (键, 显示倍数, 是否按百分比显示)
        order = [
            ("scrim", 100, True),
            ("border", 100, True),
            ("blur", 1, False),
            ("wallpaperBlur", 1, False),
            ("backgroundBrightness", 1, False),
            ("backgroundContrast", 1, False),
            ("backgroundSaturate", 1, False),
            ("wallpaperOpacity", 1, False),
            ("glassAlpha", 1, False),
            ("glassFidelity", 1, False),
        ]

        for key, mul, as_pct in order:
            lo, hi, step = (
                WS.RANGES.get(key, (0, 100, 1)) if WS else (0, 100, 1))
            row = QHBoxLayout()
            row.setSpacing(8)
            label_text = (WS.LABELS.get(key, key) if WS else key) + ":"
            lab = QLabel(label_text, box)
            lab.setMinimumWidth(96)
            row.addWidget(lab)

            sld = Slider(Qt.Orientation.Horizontal, box)
            #: 用整数刻度（0.25 这种小数乘 100 显示）
            sld.setRange(int(lo * mul), int(hi * mul))
            sld.setSingleStep(max(1, int(step * mul)))
            cur = WS.get(key) if WS else 0
            sld.setValue(int(float(cur) * mul))
            row.addWidget(sld, 1)

            val = QLabel("", box)
            val.setMinimumWidth(52)
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(val)

            def _fmt(v: int, _mul=mul, _pct=as_pct) -> str:
                real = v / _mul
                if _pct:
                    return f"{real * 100:.0f}%"
                return f"{real:g}" if isinstance(real, float) else str(real)

            val.setText(_fmt(sld.value()))
            self._glass_sliders[key] = (sld, val, mul, _fmt, as_pct)

            def _on_change(v: int, _k=key, _w=val, _m=mul,
                           _f=_fmt) -> None:
                _w.setText(_f(v))
                if WS is not None:
                    WS.save(**{_k: v / _m})
                self._reapply_glass()

            sld.valueChanged.connect(_on_change)
            v.addLayout(row)

        #: ── 主题随壁纸开关 ──
        auto = QCheckBox("主题颜色跟随壁纸（自动取主色）", box)
        if WS is not None:
            auto.setChecked(bool(WS.get("autoAccent")))
        v.addWidget(auto)

        def _on_auto(checked: bool) -> None:
            if WS is not None:
                WS.save(autoAccent=bool(checked))
            self._reapply_glass()

        auto.toggled.connect(_on_auto)
        self._auto_accent_box = auto

        #: ── 重置按钮 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        reset = QPushButton("恢复默认", box)
        reset.clicked.connect(self._reset_glass)
        btn_row.addWidget(reset)
        v.addLayout(btn_row)

        return box

    def _reapply_glass(self) -> None:
        """设置改了 → 重刷皮肤 + 卡片底色 + QML 暗化。

        ## ★★★ 2026-11-01 修「设置这么卡，而且完全没效果」

        **卡**：每拖一格滑块都同步调 `refresh_windows()`，
        而它内部是 `app.setStyleSheet()` —— **O(总 widget 数)**，
        一个 MainWindow 有 2500+ widget，一次要 1.7 秒。
        拖动时连续触发 → 界面卡死。

        → 改成 **250ms 防抖**：拖动期间只记标记，停下才真刷。

        **没效果**：只刷了 QSS，没刷卡片 `backgroundColor`
        （qfluentwidgets 的卡片是自绘背景，不读 QSS）。
        → 明确调 `apply_card_backgrounds()`。

        **壁纸本身**：`scrim` 要传给 QML 的 `tintValue` 才会压暗画面。
        """
        #: ★ 防抖：拖动中只记标记，250ms 后再刷
        try:
            from PySide6.QtCore import QTimer

            if getattr(self, "_glass_timer", None) is None:
                self._glass_timer = QTimer(self)
                self._glass_timer.setSingleShot(True)
                self._glass_timer.setInterval(250)
                self._glass_timer.timeout.connect(self._do_reapply_glass)
            self._glass_timer.start()
        except Exception:  # noqa: BLE001
            self._do_reapply_glass()

    def _do_reapply_glass(self) -> None:
        """真正重刷（防抖后才执行）。"""
        try:
            from ..core import skins as _skins
            from ..core import wallpaper_settings as WS

            _skins.invalidate_paint_cache()
            _skins.refresh_windows()
            #: ★ 卡片是自绘背景，必须单独刷
            try:
                _skins.apply_card_backgrounds()
            except Exception:  # noqa: BLE001
                pass
            #: 更新 QML 里的 tintValue（用 scrim 压暗壁纸画面）
            try:
                from . import wallpaper_quick as _wq

                lay = _wq.current_layer()
                if lay is not None and lay._view is not None:
                    root = lay._view.rootObject()
                    if root is not None:
                        root.setProperty("tintValue",
                                         float(WS.get("scrim") or 0.0))
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            logger.debug("壁纸外观：重刷失败", exc_info=True)

    def _reset_glass(self) -> None:
        """恢复默认参数并刷新 UI。"""
        try:
            from ..core import wallpaper_settings as WS

            WS.reset()
            for key, item in getattr(self, "_glass_sliders", {}).items():
                sld, val, mul, fmt = item[0], item[1], item[2], item[3]
                sld.blockSignals(True)
                sld.setValue(int(float(WS.get(key)) * mul))
                sld.blockSignals(False)
                val.setText(fmt(sld.value()))
            auto = getattr(self, "_auto_accent_box", None)
            if auto is not None:
                auto.blockSignals(True)
                auto.setChecked(bool(WS.get("autoAccent")))
                auto.blockSignals(False)
            self._reapply_glass()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸外观：重置失败", exc_info=True)

    def _refresh_wallpapers(self) -> None:
        """扫描本机 WE 壁纸库并铺卡片。

        ## ⚠ 扫描失败不能把页面搞挂

        没装 Wallpaper Engine、路径不对、project.json 坏了 ——
        任何情况都要退化成"一行提示文字"，不能让整页空白。
        """
        #: ★★★ 2026-11-01 **同步销毁旧卡片**
        #:
        #: 用户：「切换这么难做？」—— 截图里画面已经是坎特蕾拉，
        #: 但列表里「使用中」还在守岸人身上。
        #:
        #: 根因：`deleteLater()` 只是**排队**，要等事件循环才真删。
        #: 而这里紧接着就 `addWidget` 新的 —— 旧卡片还在 grid 里，
        #: 新旧重叠，看到的是旧的那个（还带着旧的使用中标记）。
        #:
        #: → `hide()` 立刻从屏幕消失 + `setParent(None)` 解绑，
        #:   最后才 `deleteLater()` 兜底。
        #: ★★★ 2026-11-01 **优先原地更新，不重建**
        #:
        #: 用户截图：画面已经是坎特蕾拉，但使用中标记还在守岸人。
        #:
        #: 重建卡片列表不可靠（`deleteLater` 排队 + grid 重排，
        #: 新旧可能重叠）。这里改成：**卡片数量和顺序没变时，
        #: 只调 `set_active` 改状态**，不删不建。
        try:
            from ..core import wallpaper_state as _wst

            _active = _wst.current_id()
            _cards = getattr(self, "_wp_cards", [])
            if _cards:
                #: 检查这组卡片是不是真的对应当前壁纸列表
                from ..core import wallpaper_engine as _we

                _items = _we.scan_wallpapers()
                _same = (
                    len(_items) == len(_cards)
                    and all(
                        str(c._info.get("id") or "")  # noqa: SLF001
                        == str(it.get("id") or "")
                        for c, it in zip(_cards, _items))
                )
                if _same:
                    for c in _cards:
                        c.set_active(
                            str(c._info.get("id") or "") == _active)  # noqa: SLF001
                    logger.debug("壁纸库：原地更新 %d 张卡片的 active 状态",
                                 len(_cards))
                    return
        except Exception:  # noqa: BLE001
            logger.debug("壁纸库：原地更新失败，走重建", exc_info=True)

        for c in getattr(self, "_wp_cards", []):
            c.hide()
            c.setParent(None)
            c.deleteLater()
        self._wp_cards = []
        while self._wp_grid.count():
            item = self._wp_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        try:
            from ..core import wallpaper_engine as WE  # noqa: PLC0415

            items = WE.scan_wallpapers()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸库扫描失败", exc_info=True)
            items = []

        self._wp_title.setVisible(True)
        if not items:
            self._wp_hint.setText(
                "没找到 Wallpaper Engine 壁纸库。\n"
                "请确认已安装 Wallpaper Engine，且订阅了创意工坊壁纸。")
            return

        ok_count = sum(1 for x in items if x.get("supported"))
        self._wp_hint.setText(
            f"扫到 {len(items)} 个壁纸（可播放 {ok_count} 个视频型；"
            f"Scene / Web 型需要 WebGL 渲染，暂不支持）。")

        try:
            from ..core import wallpaper_state  # noqa: PLC0415

            active_id = wallpaper_state.current_id()
        except Exception:  # noqa: BLE001
            active_id = ""

        for i, info in enumerate(items):
            card = WallpaperCard(
                info, active=(info.get("id") == active_id), parent=self)
            card.chosen.connect(self._on_wallpaper_chosen)
            self._wp_grid.addWidget(card, i // PER_ROW, i % PER_ROW)
            self._wp_cards.append(card)

    def _on_wallpaper_chosen(self, wp_id: str) -> None:
        """选中/取消一个 WE 壁纸。

        :param wp_id: 壁纸 id；空串 = 取消当前壁纸
        """
        try:
            from ..core import wallpaper_state
            from . import wallpaper_layer
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：导入失败", exc_info=True)
            return

        window = self.window()
        if not wp_id:
            wallpaper_state.set_current("")
            wallpaper_layer.shutdown()
            #: ★ 清缓存再重刷 —— 不然 ``_paint`` 看到"QSS 没变"就跳过，
            #: 界面还挂着壁纸模式的透明 QSS，看着像"点了没反应"。
            try:
                skins.invalidate_paint_cache()
            except AttributeError:
                skins._PAINTED_QSS = ""              # noqa: SLF001
                skins._PAINTED_WINDOWS = set()       # noqa: SLF001
            skins.refresh_windows()
            self._refresh_wallpapers()
            return

        try:
            from ..core import wallpaper_engine as WE  # noqa: PLC0415

            info = WE.wallpaper_by_id(wp_id)
            if info is None or not info.get("supported"):
                logger.warning("壁纸：%s 不可播放", wp_id)
                wallpaper_state.set_current("")
                self._refresh_wallpapers()
                return
            #: ★★★ 2026-10-31 **必须把路径一起存进去**
            #:
            #: 用户截图：「切换也有问题啊」——
            #: 卡片标「使用中」的是「坎特蕾拉」，但壁纸播的还是上一个画面。
            #:
            #: 根因：``set_current(wp_id)`` 只存了 id、**没存 path**。
            #: 而 ``wallpaper_layer.apply_wallpaper`` 读的是
            #: ``wallpaper_state.current_path()`` —— 拿到空串后会去
            #: "按 id 重新扫描找路径"，那条路会重新 `scan_wallpapers()`，
            #: 既慢又可能因为排序/同名找错。
            #: → 这里直接把路径存下来，不留歧义。
            wallpaper_state.set_current(wp_id, info["video_path"])
            #: ★★★ 2026-10-31 **顺序很重要**：先铺壁纸，再重刷皮肤。
            #:
            #: 用户截图：「是不是上面的冲突了」——
            #: 壁纸明明在播，界面却是纯色板看不到它。
            #:
            #: 根因：`skins._paint` 里的 `_apply_wallpaper_for` 会判断
            #: 有没有壁纸来决定用不透明渐变还是玻璃高光。
            #: 但 `_paint` 的 QSS **有缓存**（`_PAINTED_QSS`）——
            #: 铺壁纸前后 QSS 字符串没变，它就**跳过重刷**了，
            #: 于是界面还挂着无壁纸时的不透明渐变。
            #:
            #: → 先 `apply_video`（让 `current_layer()` 有值），
            #: 再**清缓存**强制重刷，QSS 才会走玻璃分支。
            wallpaper_layer.apply_video(window, info["video_path"])
            #: ★ ① 先等壁纸层真的 start（apply_video 内部是同步的，
            #: 但 Qt 的 QMediaPlayer 要等事件循环转一圈才真正 load）
            app = None
            try:
                from PySide6.QtWidgets import QApplication as _QA  # noqa: PLC0415

                app = _QA.instance()
            except Exception:  # noqa: BLE001
                app = None
            if app is not None:
                for _ in range(30):
                    app.processEvents()

            #: ★ ② 清缓存 → 全量重刷（走玻璃分支）
            try:
                skins.invalidate_paint_cache()
            except AttributeError:
                skins._PAINTED_QSS = ""              # noqa: SLF001
                skins._PAINTED_WINDOWS = set()       # noqa: SLF001
            skins.refresh_windows()

            #: ★ ③ **再单独刷一次侧栏 + 标题栏**。
            #:
            #: 用户截图：「上面你没改」—— 标题栏还是一块实心板。
            #:
            #: 因为 `_paint` 里刷面板时，`current_layer()` 可能
            #: 还没值（壁纸刚 apply_video，QMediaPlayer 还没就绪）。
            #: 这里补一道，确保用的是玻璃分支。
            try:
                skins.refresh_glass_panels([window])
            except Exception:  # noqa: BLE001
                pass

            self._refresh_wallpapers()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：铺失败", exc_info=True)
            self._refresh_wallpapers()

    def _on_chosen(self, skin_id: str) -> None:
        """选中一款主题。

        ## ★ 角色主题：**先播开卡动画，播完再落主题**

        用户 2026-10-30 要的就是这个仪式感。

        ⚠ 顺序不能反 —— 先落主题的话，换肤瞬间界面会闪一下，
        动画盖在闪完的界面上，观感很差。

        ## ★★ 已经在用它了，也照样播（2026-10-30 修）

        用户报"哪里播放抽卡动画了？" —— 因为爱弥斯主题**已经是当前主题**，
        卡片按钮显示"使用中"且 ``setEnabled(False)``，**点不动**，
        动画那条路根本没被走到。

        现在：角色主题在使用中时按钮写「重播开卡动画」且可点。
        这时**只播动画、不重复应用主题**（应用了也没变化，
        但 ``apply_skin`` 会刷一遍 QSS，白白闪一下）。

        ⚠ 连点保护：已经在播就直接忽略，免得叠出两层动画。
        """
        skin = skins.skin_by_id(skin_id)
        if skin is None:
            return

        is_current = skins.current_skin()["id"] == skin_id

        #: 角色主题 → 播动画（不管是不是当前主题：当前主题时是"重播"）
        if skins.is_character_skin(skin):
            if self._reveal is not None:
                return                      #: 正在播 → 忽略这次点击
            try:
                window = self.window()
                logger.info("播放开卡动画：%s（当前主题=%s）",
                            skin.get("name"), is_current)

                def _apply() -> None:
                    self._reveal = None
                    if is_current:
                        #: 只是重播 —— 主题没变，不用再 apply 一遍
                        return
                    self._apply_now(skin_id)

                #: ★★★ 2026-10-30 优先播**真实视频**（用户给了抽卡 CG）。
                #:
                #: 有视频 → QMediaPlayer 播真 CG
                #: 没视频 → 退回 QPainter 光效 + 定格图
                from .gacha_video import has_video  # noqa: PLC0415

                if has_video(skin):
                    from .gacha_video import play_video_reveal  # noqa: PLC0415

                    self._reveal = play_video_reveal(
                        window, skin, on_done=_apply)
                else:
                    from .gacha_reveal import play_gacha_reveal  # noqa: PLC0415

                    self._reveal = play_gacha_reveal(
                        window, skin, on_done=_apply)
                return
            except Exception:  # noqa: BLE001 - 动画失败也要能换主题
                logger.warning("开卡动画播放失败，直接应用主题", exc_info=True)
                self._reveal = None

        if is_current:
            return                          #: 纯配色主题、且已经在用 → 什么都不做

        self._apply_now(skin_id)

    def _apply_now(self, skin_id: str) -> None:
        """真正应用主题 + 刷新卡片。"""
        if skins.apply_skin(skin_id):
            self.refresh()
            #: ⚠ 换肤后 QSS 是新的 —— 让其它已开窗口也跟上
            skins.refresh_windows()


def build_skin_page(parent=None) -> SkinInterface:
    """给侧栏用的皮肤页面。"""
    return SkinInterface(parent)
