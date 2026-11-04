# -*- coding: utf-8 -*-
"""抽卡动画 —— 使用「角色主题」时播放的鸣潮式开卡演出。

## 用户 2026-10-30

    "改进皮肤功能，参考dsh-pet，和鸣潮角色抽卡动画，
     把角色抽卡动画做进皮肤里，并把皮肤改名为主题皮肤，
     以爱弥斯为例，先做一个看看"

## 鸣潮抽卡动画是怎么演的（照着做的四段）

======================================  ==================================
阶段                                     画面
======================================  ==================================
① 蓄力（约 0.9s）                        全屏压黑 → 中心一个亮点由小变大、
                                         星芒开始旋转（速度渐快）
② 绽放（约 0.6s）                        星芒猛地扩散到全屏，光晕爆开，
                                         出现「五星」金色粒子
③ 揭晓（约 0.7s）                        角色立绘从中心缩放淡入，
                                         外围星环扫过一圈
④ 收束（约 0.4s）                        光效淡出，整层透明 → 关掉
======================================  ==================================

总时长约 2.6 秒 —— 够看，又不至于让人等得不耐烦。

## 怎么实现（纯 QPainter，**不用动画文件/视频**）

为什么不用序列帧或视频：
  * 打包体积（一段 3 秒 1080p 视频就是好几 MB）
  * 素材依赖（dsh-pet 那种要专门的图集）
  * **可调**（配色直接读主题的 ``gacha`` 那几项，换角色只改配置）

QPainter 画这些完全够：径向渐变做光晕、旋转的细长三角做星芒、
``QPainterPath`` 做星环、透明度做淡入淡出。

## 怎么接进界面（见 :class:`GachaReveal`）

它是个**覆盖在父窗口上的透明子控件**（``Qt.WA_TransparentForMouseEvents``
由调用方决定），用 ``QPropertyAnimation`` 驱动一个 0→1 的进度值，
``paintEvent`` 按进度画对应阶段。

    reveal = GachaReveal(parent_window, skin)
    reveal.finished.connect(lambda: skins.apply_skin(skin["id"]))
    reveal.start()

⚠ 一定要**先播完再落主题** —— 用户要的是"换主题时先看一段开卡"的仪式感。
如果先落主题再播，换肤瞬间界面会闪一下，观感很差。
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Property,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 各阶段在总进度 [0,1] 里的分界
PHASE_CHARGE = 0.35       #: 蓄力结束
PHASE_BLOOM = 0.58        #: 绽放结束
PHASE_REVEAL = 0.85       #: 揭晓结束（之后是收束）

#: 动画总时长（毫秒）
TOTAL_MS = 2600

#: 兜底配色（角色主题没配 ``gacha`` 时用）
_FALLBACK = {
    "rays": "#8B7CFF",
    "glow": "#C9C0FF",
    "bg": "#06040F",
    "star": "#FFD766",
    "accent": "#5ED3F3",
}


def _ease_out_cubic(t: float) -> float:
    """0→1 的缓出（开卡那下"猛地出来"靠它）。"""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _ease_in_quad(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t


class GachaReveal(QWidget):
    """★ 抽卡开卡动画层（覆盖在父窗口上）。

    ## 生命周期

        reveal = GachaReveal(window, skin_dict)
        reveal.finished.connect(...)      #: 播完了
        reveal.start()                    #: 开始播（自己会 show + 置顶）

    播完自动 ``hide()`` 并 ``deleteLater()``（用 ``WA_DeleteOnClose`` 更稳，
    这里手动删 —— 因为不是 ``close()`` 语义）。

    ## 为什么是"覆盖层"而不是"独立窗口"

    独立窗口会和主窗口抢焦点、还可能被系统动画搞乱时序。
    作为**子控件铺满父窗口**最简单：``resize`` 跟着父窗口走，
    ``raise_()`` 保证在其它控件上面。
    """

    #: 动画播完（成功播完才发 —— 中途被打断不发）
    finished = Signal()

    def __init__(self, parent: QWidget, skin: dict):
        super().__init__(parent)
        self._skin = skin or {}
        style = (self._skin.get("gacha") if isinstance(
            self._skin.get("gacha"), dict) else None) or {}
        self._style = {**_FALLBACK, **style}

        self._progress = 0.0
        self._pixmap: QPixmap | None = None
        self._character = str(self._skin.get("character") or "")
        self._done = False

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)   #: 接住按键（可跳过）
        self.hide()

        #: 驱动进度：``QPropertyAnimation`` 需要一个 Qt 属性，
        #: 这里用自定义 ``progress`` 属性（见下面 property 定义）。
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(TOTAL_MS)
        #: 用线性 —— 每个阶段自己决定怎么缓动（统一缓动的话
        #: "蓄力慢、绽放快"这种节奏就做不出来了）。
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.finished.connect(self._on_anim_done)

        #: ★ 2026-10-30 跟着父控件尺寸变 —— 用户拖窗口时动画不能错位。
        #:
        #: 用 ``installEventFilter`` 而不是重写父控件的方法：
        #: 我们不该为了一个覆盖层去改 MainWindow。
        parent = self.parentWidget() if parent is not None else None
        if parent is not None:
            try:
                parent.installEventFilter(self)
            except Exception:  # noqa: BLE001
                logger.warning("抽卡动画：装父控件事件过滤器失败", exc_info=True)

        self._load_avatar()

    # ---------------------------------------------------------------- 属性
    #: ★★★ 2026-10-30 **必须用 ``Property``，不能用 Python 的 ``property``**。
    #:
    #: ## 踩过的坑
    #:
    #: 第一版写的是::
    #:
    #:     progress = property(_get_progress, _set_progress)
    #:
    #: 测试输出警告::
    #:
    #:     QPropertyAnimation: you're trying to animate a non-existing
    #:     property progress of your QObject
    #:
    #: **动画完全不动**（进度一直是 0，画面卡在第一帧）。
    #: 原因：``QPropertyAnimation`` 找的是 **Qt 元对象系统**里的属性
    #: （要 ``Q_PROPERTY`` 声明 + 元对象注册），
    #: 而 Python 的 ``property`` 只是解释器层面的描述符，Qt 根本不认识。
    #:
    #: ``Property``（``PySide6.QtCore.Property``）会在类创建时把这个描述符
    #: 注册进元对象 → ``QPropertyAnimation`` 才找得到。
    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = float(value)
        self.update()

    progress = Property(float, _get_progress, _set_progress)

    # ---------------------------------------------------------------- 资源
    def _load_avatar(self) -> None:
        """加载**定格立绘**（``skins.splash_image(skin)``）。

        ## ★★★ 2026-10-30 改用官方抽卡立绘

        用户：

            > 而且这也不是爱弥斯的，然后背景图片也不是抽卡动画最后定格的爱弥斯图片

        原来读的是 ``avatar``（240x320 的小头像）——
        放大到 1400px 高会糊得看不清，而且头像本来就不是立绘。

        现在优先读 ``splash``（1920x1080 官方抽卡图，
        自带「鸣潮」logo + 角色名 + 五颗星 + 台词）——
        **它就是抽卡动画最后定格的那张**，直接铺满当背景。

        找不到 ``splash`` 才退回 ``avatar``（至少有个图，总比空白强）。

        ⚠ 拿不到任何图就只播光效 + 角色名（不留空洞）。
        """
        rel = ""
        try:
            from ..core import skins  # noqa: PLC0415 - 避免循环导入

            rel = skins.splash_image(self._skin)
        except Exception:  # noqa: BLE001
            rel = str(self._skin.get("avatar") or "")
        if not rel:
            return
        try:
            from ..core import paths  # noqa: PLC0415 - 避免循环导入

            #: 项目根目录下的 assets/（resource_dir 就是项目根/打包后的根）
            path = paths.resource_dir() / "assets" / rel
            if not path.is_file():
                logger.warning("抽卡动画：找不到立绘 %s", path)
                return
            pix = QPixmap(str(path))
            if pix.isNull():
                return
            self._pixmap = pix
            logger.info("抽卡动画：立绘 %s（%dx%d）",
                        rel, pix.width(), pix.height())
        except Exception:  # noqa: BLE001 - 加载失败不该让动画挂掉
            logger.warning("抽卡动画：加载立绘失败", exc_info=True)

    # ---------------------------------------------------------------- 播放
    def _fill_parent(self) -> None:
        """把覆盖层铺满父控件。

        ## ⚠⚠ 2026-10-30 踩的坑：``parent.rect()`` 可能是 (0,0,100,30)

        原来 ``start()`` 里直接 ``self.setGeometry(parent.rect())`` ——
        实测**动画层只有 100x30 且 ``isVisible()==False``**（什么都不显示）。

        原因：这行在 ``QTimer.singleShot(0, ...)`` 里执行，
        那一刻父窗口**可能还没完成首次布局**（``rect()`` 还是 Qt 给的
        默认最小几何 100x30）。用那个矩形铺，等于把一个 100x30 的小窗口
        盖在窗口左上角 —— 用户什么都看不到。

        现在改成读 ``parent.size()``，并且**每次 resize 都重新铺**
        （见 ``_parent_resized``）。

        ⚠ 父控件为 None 时直接返回 —— 没爹的覆盖层没法铺满，
        那种情况调用方有 bug，不该在这里崩。
        """
        parent = self.parentWidget()
        if parent is None:
            return
        size = parent.size()
        #: 尺寸还没就绪（<= 1px）就别铺 —— 等下一轮 resize
        if size.width() <= 1 or size.height() <= 1:
            return
        self.setGeometry(0, 0, size.width(), size.height())

    def _parent_resized(self) -> None:
        """父控件尺寸变了 → 跟着铺满（用户拖窗口时动画不能错位）。"""
        if self._done:
            return
        self._fill_parent()
        self.update()

    def start(self) -> None:
        """开始播（铺满父窗口、置顶、抢键盘以便跳过）。

        ⚠ 这里的顺序有讲究：

        1. 先 ``_fill_parent()`` 把几何铺对（见那个方法的说明 ——
           直接读 ``parent.rect()`` 会拿到 100x30 这种默认值）
        2. 再 ``show()``（几何为 0 时 show 出来是看不见的）
        3. ``raise_()`` 盖到兄弟控件上面
        4. 最后启动动画

        ## ★ 父控件没尺寸时**先别启动动画**

        实测（2026-10-30）：模拟启动流程时覆盖层拿到 100x30、
        而且 ``isVisible()==False`` —— 原因是那一刻父窗口还在首帧布局。

        所以这里加一道闸：**尺寸没就绪就一直等**（最多等 1 秒），
        等到了再真正 start。不然动画会在一个 100x30 的隐形小框里
        跑完 2.6 秒，用户什么都看不到。
        """
        self._start_retry = getattr(self, "_start_retry", 0) + 1
        parent = self.parentWidget()
        ready = (parent is not None
                 and parent.width() > 1 and parent.height() > 1)
        if not ready:
            if self._start_retry <= 60:      #: 60 × 16ms ≈ 1 秒
                QTimer.singleShot(16, self.start)
                return
            #: 等了一秒还没有尺寸 → 放弃（不该无限等）
            logger.warning("抽卡动画：父窗口一直没有尺寸，放弃播放")
            self._on_anim_done()
            return

        self._fill_parent()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._progress = 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def skip(self) -> None:
        """立刻结束（用户按 Esc / 点一下）。"""
        if self._done:
            return
        self._anim.stop()
        self._progress = 1.0
        self.update()
        self._on_anim_done()

    def _on_anim_done(self) -> None:
        if self._done:
            return
        self._done = True
        self.hide()
        self.finished.emit()
        #: 用完即弃 —— 不然每次换主题都留一个覆盖层在父窗口上
        self.deleteLater()

    # ---------------------------------------------------------------- 事件
    def mousePressEvent(self, event) -> None:      # noqa: N802 - Qt 命名
        """点一下跳过 —— 看腻了的人不想等 2.6 秒。"""
        self.skip()
        event.accept()

    def keyPressEvent(self, event) -> None:        # noqa: N802 - Qt 命名
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space,
                           Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.skip()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:          # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self.update()

    def eventFilter(self, obj, event) -> bool:     # noqa: N802 - Qt 命名
        """★ 父控件尺寸变了 → 跟着铺满。

        2026-10-30 踩的坑：``start()`` 里读 ``parent.rect()`` 时
        父窗口可能还没完成布局（拿到 100x30 的默认几何），
        结果是覆盖层只有 100x30、用户什么都看不到。
        这里补一条：父控件每次 resize 都重新铺。
        """
        try:
            if obj is self.parentWidget() and event.type() in (
                event.Type.Resize, event.Type.Show):
                if not self._done and self.isVisible():
                    self._parent_resized()
        except Exception:  # noqa: BLE001 - 过滤器不该抛
            pass
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:           # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        t = self._progress

        bg = QColor(self._style["bg"])
        rays = QColor(self._style["rays"])
        glow = QColor(self._style["glow"])
        star = QColor(self._style["star"])

        #: ═══ 背景：从透明到压黑（收尾再淡回去）
        #: 开头 0~0.15 渐入，结尾 0.9~1 渐出 —— 硬切会很突兀。
        fade_in = min(1.0, t / 0.15)
        fade_out = 1.0 if t < 0.9 else max(0.0, (1.0 - t) / 0.1)
        alpha = int(255 * fade_in * fade_out)
        if alpha > 0:
            bg.setAlpha(alpha)
            p.fillRect(self.rect(), bg)

        if t <= 0.0:
            p.end()
            return

        #: ═══ ① 蓄力：中心亮点 + 旋转星芒（越转越快）
        if t < PHASE_CHARGE:
            k = t / PHASE_CHARGE
            radius = 8.0 + 120.0 * _ease_in_quad(k)
            #: 星芒速度随进度加快（最后一下"唰"地转起来）
            spin = (k ** 2) * 220.0
            self._draw_rays(p, cx, cy, radius * 2.6, rays, glow,
                            spin=spin, alpha=0.75 * k, count=14)
            self._draw_glow(p, cx, cy, radius * 1.5, glow, 0.9 * k)
            p.end()
            return

        #: ═══ ② 绽放：光爆到全屏
        if t < PHASE_BLOOM:
            k = (t - PHASE_CHARGE) / (PHASE_BLOOM - PHASE_CHARGE)
            ek = _ease_out_cubic(k)
            max_r = math.hypot(cx, cy)
            radius = 120.0 + (max_r - 120.0) * ek
            self._draw_rays(p, cx, cy, radius, rays, glow,
                            spin=220.0 + 90.0 * k, alpha=0.9 * (1 - 0.55 * k),
                            count=18)
            self._draw_glow(p, cx, cy, radius * 0.85, glow, 0.85 * (1 - k * 0.5))
            #: 星尘粒子（金色小点向外飞）
            self._draw_sparks(p, cx, cy, radius, star, ek)
            p.end()
            return

        #: ═══ ③ 揭晓：**官方抽卡图铺满**（轻微推近 + 淡入）+ 星环扫过
        if t < PHASE_REVEAL:
            k = (t - PHASE_BLOOM) / (PHASE_REVEAL - PHASE_BLOOM)
            ek = _ease_out_cubic(k)
            #: ★ 立绘一出来就把光效压下去 —— 官方图本身就很亮很满，
            #: 再叠强光效会糊成一片看不清。
            self._draw_rays(p, cx, cy, math.hypot(cx, cy) * 1.2, rays, glow,
                            spin=310.0 + 20.0 * k,
                            alpha=0.30 * (1 - 0.8 * k), count=18)
            #: ★ 铺满型立绘从 1.06 收到 1.0（"推过去"的手感）——
            #: 从 0.82 放大会让人先看到一圈黑边再撑满，很别扭。
            self._draw_character(p, cx, cy, scale=1.06 - 0.06 * ek,
                                 alpha=min(1.0, k / 0.45))
            self._draw_ring(p, cx, cy, 180.0 + 260.0 * ek, glow,
                            alpha=0.9 * (1 - k))
            p.end()
            return

        #: ═══ ④ 收束：立绘**保持满屏**，只把光效淡掉
        #: （定格图要留到最后，不能跟着淡出 —— 那会让换主题瞬间闪黑）
        k = (t - PHASE_REVEAL) / (1.0 - PHASE_REVEAL)
        fade = 1.0 - _ease_out_cubic(k)
        self._draw_rays(p, cx, cy, math.hypot(cx, cy) * 1.2, rays, glow,
                        spin=330.0, alpha=0.30 * fade, count=18)
        self._draw_character(p, cx, cy, scale=1.0, alpha=1.0)
        p.end()

    # ---------------------------------------------------------------- 图元
    def _draw_rays(self, p: QPainter, cx: float, cy: float, radius: float,
                   rays: QColor, glow: QColor, *, spin: float,
                   alpha: float, count: int) -> None:
        """星芒：一圈细长的**三角楔**，绕中心旋转。

        这是开卡动画最标志性的元素 —— 鸣潮那个金色放射光就是它。
        """
        if alpha <= 0.01 or radius <= 1:
            return
        p.save()
        p.translate(cx, cy)
        p.rotate(spin)
        for i in range(count):
            p.save()
            p.rotate(360.0 / count * i)
            #: 长短交替，看起来更自然（不是规整的齿轮）
            length = radius * (1.0 if i % 2 == 0 else 0.62)
            half = max(1.4, radius * 0.012)
            grad = QLinearGradient(0, 0, 0, -length)
            c0 = QColor(glow)
            c0.setAlphaF(min(1.0, alpha))
            c1 = QColor(rays)
            c1.setAlphaF(0.0)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            path = QPainterPath()
            path.moveTo(0, 0)
            path.lineTo(-half, -length)
            path.lineTo(half, -length)
            path.closeSubpath()
            p.fillPath(path, grad)
            p.restore()
        p.restore()

    def _draw_glow(self, p: QPainter, cx: float, cy: float, radius: float,
                   color: QColor, alpha: float) -> None:
        """中心径向光晕。"""
        if alpha <= 0.01 or radius <= 1:
            return
        grad = QRadialGradient(QPointF(cx, cy), radius)
        c0 = QColor(color)
        c0.setAlphaF(min(1.0, alpha))
        c1 = QColor(color)
        c1.setAlphaF(0.0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(0.45, QColor(c1.red(), c1.green(), c1.blue(),
                                    int(255 * alpha * 0.35)))
        grad.setColorAt(1.0, c1)
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

    def _draw_sparks(self, p: QPainter, cx: float, cy: float, radius: float,
                     color: QColor, k: float) -> None:
        """星尘粒子：从中心向外飞的小金点（固定 24 个，角度均分）。"""
        if k <= 0.0:
            return
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(24):
            ang = math.radians(360.0 / 24 * i + 12.0)
            dist = radius * (0.35 + 0.65 * k) * (0.7 + 0.3 * ((i * 7) % 5) / 4)
            x = cx + math.cos(ang) * dist
            y = cy + math.sin(ang) * dist
            size = max(1.2, 4.2 * (1.0 - k * 0.7))
            c = QColor(color)
            c.setAlphaF(max(0.0, 1.0 - k * 0.85))
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), size, size)

    def _draw_ring(self, p: QPainter, cx: float, cy: float, radius: float,
                   color: QColor, alpha: float) -> None:
        """星环：一圈细亮环，从中心向外扫一次。"""
        if alpha <= 0.01 or radius <= 1:
            return
        c = QColor(color)
        c.setAlphaF(min(1.0, alpha))
        pen = QPen(c)
        pen.setWidthF(max(1.2, radius * 0.012))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

    def _draw_character(self, p: QPainter, cx: float, cy: float, *,
                        scale: float, alpha: float) -> None:
        """★ 定格：**官方抽卡立绘铺满全屏**（淡入 + 轻微放大）。

        ## ★★★ 2026-10-30 重写（用户要求）

        用户：

            > 背景图片也不是抽卡动画最后定格的爱弥斯图片

        原来把 240x320 的小头像缩放到屏幕 62% 高度、居中偏上 ——
        那既不是"抽卡立绘"（是小头像放大，糊），也不是"铺满背景"。

        现在换成官方 1920x1080 抽卡图（``skins.splash_image``）：
        **等比铺满整个屏幕**（多余的边裁掉），
        图上自带「鸣潮」logo、「爱弥斯」名字、五颗星、台词 ——
        **不需要再自己画名字**（画了会和图上的字重叠）。

        ## 缩放 / 淡入

        ``scale`` 从 0.88 长到 1.0（``_ease_out_cubic`` 缓出，有"推近"感），
        ``alpha`` 淡入。铺满用 ``KeepAspectRatioByExpanding``：
        保证不留黑边，牺牲一点边缘（抽卡图的主角都在中间）。
        """
        if alpha <= 0.01:
            return

        if self._pixmap is not None and not self._pixmap.isNull():
            w = max(1, int(self.width() * scale))
            h = max(1, int(self.height() * scale))
            #: ★★★ 2026-10-30 **不能直接 KeepAspectRatioByExpanding**
            #:
            #: 官方抽卡图是 **16:9**，图上左侧有「鸣潮」logo、
            #: 「爱弥斯」名字、五颗星、台词 —— **全在左边**。
            #:
            #: 窗口比例通常比 16:9 **更窄**（实测 1400x844 = 1.659 < 1.778），
            #: 这时 ``KeepAspectRatioByExpanding`` 会**裁掉左右** ——
            #: logo 和名字正好被切没了（实机截图看到「鸣潮」只剩一半）。
            #:
            #: 正确做法：**等比"包含"进窗口**（``KeepAspectRatio``），
            #: 让整张图完整可见，不足的部分用背景色补齐（或略微放大一点点
            #: 靠居中来吃掉极小的边 —— 这里直接补边更稳，信息不丢）。
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            #: 居中
            x = cx - scaled.width() / 2.0
            y = cy - scaled.height() / 2.0
            p.save()
            #: 先铺一层同色底 —— 不然等比缩放后上下/左右会有透明缝，
            #: 底下主界面的内容会透出来（很脏）。
            p.fillRect(self.rect(), QColor(self._style["bg"]))
            p.setOpacity(min(1.0, alpha))
            p.drawPixmap(int(x), int(y), scaled)
            p.restore()
            #: ★ 官方图上已经有名字/logo/星星了 —— 不再叠加文字
            return

        #: 没图才退化成"只画名字"（不留一块空洞）
        if alpha <= 0.35 or not self._character:
            return
        font = QFont()
        font.setPixelSize(max(20, int(self.height() * 0.05)))
        font.setBold(True)
        p.setFont(font)
        text = self._character
        metrics = p.fontMetrics()
        tw = metrics.horizontalAdvance(text)
        shadow = QColor(0, 0, 0, int(200 * alpha))
        p.setPen(shadow)
        p.drawText(QRectF(cx - tw / 2.0 + 2, cy + 2, tw + 8, 80),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                   text)
        fg = QColor(self._style["glow"])
        fg.setAlphaF(min(1.0, alpha))
        p.setPen(fg)
        p.drawText(QRectF(cx - tw / 2.0, cy, tw + 8, 80),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                   text)


def play_gacha_reveal(parent: QWidget, skin: dict, on_done=None) -> GachaReveal:
    """便捷入口：播一段开卡动画，播完调 ``on_done``。

    :param parent: 覆盖在哪个控件上（通常是主窗口）
    :param skin: 角色主题的 dict（要带 ``character`` / ``avatar`` / ``gacha``）
    :param on_done: 播完的回调（通常是"真正应用这个主题"）

    :return: 那个覆盖层控件（调用方一般不用管，它自己会清理）
    """
    reveal = GachaReveal(parent, skin)
    if on_done is not None:
        reveal.finished.connect(on_done)
    #: 兜底：万一父窗口正在缩放，等一下让几何稳定再铺满
    QTimer.singleShot(0, reveal.start)
    return reveal


def play_on_startup(window: QWidget, delay_ms: int = 1200) -> GachaReveal | None:
    """★ 启动时自动播一遍当前主题的开卡动画。

    ## 用户 2026-10-30

    > 我要在启动的就播放爱弥斯的抽卡动画

    ## 什么时候播

    只有**当前主题是角色主题、且 ``play_on_start`` 为真**时才播
    （见 :func:`src.core.skins.should_play_on_start`）。
    默认主题（晨雾玻璃）不会播 —— 不然每次启动都白等 2.6 秒。

    ## 为什么要延迟

    刚 ``window.show()`` 时窗口还在做首帧布局，几何可能还是默认尺寸
    （比如 640x480），这时候铺满会错位。等 1.2 秒让窗口稳定下来。

    ⚠ 延迟期间用户可能已经点了别的页面 —— 无所谓，动画是**覆盖层**，
    盖在窗口上不挡操作（可以点一下跳过）。

    :param window: 主窗口
    :param delay_ms: 延迟多少毫秒再播（默认 1200）
    :return: 那个覆盖层（不播则返回 None）
    """
    try:
        from ..core import skins  # noqa: PLC0415

        skin = skins.current_skin()
        if not skins.should_play_on_start(skin):
            logger.info("启动动画：当前主题不要求启动播放（%s）",
                        skin.get("id"))
            return None
    except Exception:  # noqa: BLE001 - 判不出来就不播，别影响启动
        logger.warning("启动动画：判断是否播放失败", exc_info=True)
        return None

    holder: dict = {}

    def _fire() -> None:
        try:
            #: ★ 2026-10-30 优先播**真实视频**（用户给了抽卡 CG）。
            #: 没视频才用本模块的 QPainter 光效版。
            try:
                from .gacha_video import has_video, play_video_reveal  # noqa: PLC0415

                if has_video(skin):
                    logger.info("启动动画：播放视频版 %s", skin.get("name"))
                    holder["reveal"] = play_video_reveal(window, skin)
                    return
            except Exception:  # noqa: BLE001 - 视频通路坏了退回 QPainter
                logger.warning("启动动画：视频版不可用，退回光效版", exc_info=True)

            logger.info("启动动画：开始播放 %s（光效版）", skin.get("name"))
            holder["reveal"] = play_gacha_reveal(window, skin)
        except Exception:  # noqa: BLE001 - 动画失败绝不能影响启动
            logger.warning("启动动画：播放失败", exc_info=True)

    QTimer.singleShot(max(0, int(delay_ms)), _fire)
    return None


def _noop() -> None:
    """占位（保持模块接口稳定，别删）。"""
