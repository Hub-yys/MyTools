"""侧栏顶级项的自由排序（含持久化）。

需求：侧栏里「配置」和「工具」可以**上下拖动换位置**，但「主页」固定在最上面。

为什么能这么改：``NavigationPanel`` 把**顶级项**都塞在同一个 ``QVBoxLayout``
（``panel.topLayout``）里，而分组项的子项是挂在分组 widget **内部**的 ——
所以只要动 topLayout 里这几个顶级项，分组连同它的子项就是一整块在动。

交互细节：
- 按下后纵向移动超过阈值才进入拖动，避免把普通点击误判成拖动；
- 拖动中按"越过相邻项中线"逐个交换，位置实时跟着鼠标走；
- 拖动期间 ``grabMouse()``，否则鼠标一旦移出这一项就收不到 Move 事件了；
- 松手时**吞掉** mouseRelease —— 否则框架会顺手 emit clicked、把页面也切了。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt

#: 超过这个位移才算拖动（像素）
DRAG_THRESHOLD = 5

#: 存到 ui_state.json 里的键名
ORDER_KEY = "nav_order"


class NavReorderHelper(QObject):
    """把导航栏上的若干顶级项变成可拖拽排序。

    :param nav: ``FluentWindow.navigationInterface``
    :param movable_keys: 可自由拖动的 routeKey
    :param fixed_keys: 不参与排序、位置固定死的 routeKey（比如主页）
    :param on_order_changed: 顺序变化后的回调，收到新的 routeKey 列表
    """

    def __init__(
        self,
        nav,
        movable_keys,
        fixed_keys=(),
        on_order_changed=None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._nav = nav
        self._panel = nav.panel
        self._layout = self._panel.topLayout
        self._movable_keys = list(movable_keys)
        self._fixed_keys = list(fixed_keys)
        self._on_order_changed = on_order_changed

        self._dragging = False
        self._press_y = 0
        self._drag_widget = None

        for key in self._movable_keys:
            widget = self._widget(key)
            if widget is not None:
                widget.installEventFilter(self)
                widget.setToolTip("按住可以上下拖动，调整位置")

    # ------------------------------------------------------------ 基础
    def _widget(self, route_key: str):
        getter = getattr(self._nav, "widget", None)
        return getter(route_key) if callable(getter) else None

    def _top_widgets(self) -> list:
        """topLayout 里的顶级导航项，按当前布局顺序。"""
        result = []
        for i in range(self._layout.count()):
            widget = self._layout.itemAt(i).widget()
            if widget is None:
                continue
            key = widget.property("routeKey")
            if key and key in self._panel.items and self._panel.items[key].parentRouteKey is None:
                result.append(widget)
        return result

    def _movable_widgets(self) -> list:
        return [w for w in self._top_widgets() if w.property("routeKey") in self._movable_keys]

    @staticmethod
    def _center_y(widget) -> int:
        return widget.mapToGlobal(QPoint(0, 0)).y() + widget.height() // 2

    # ------------------------------------------------------------ 排序
    def current_order(self) -> list[str]:
        return [w.property("routeKey") for w in self._top_widgets()]

    def apply_order(self, order: list[str]) -> bool:
        """按 routeKey 顺序重排顶级项。没提到的项保持原有相对顺序、排在后面。"""
        widgets = self._top_widgets()
        if len(widgets) < 2:
            return False

        by_key = {w.property("routeKey"): w for w in widgets}
        ordered = [by_key[k] for k in order if k in by_key]
        ordered += [w for w in widgets if w not in ordered]
        if ordered == widgets:
            return False

        start = min(self._layout.indexOf(w) for w in widgets)
        for widget in widgets:
            self._layout.removeWidget(widget)
        for offset, widget in enumerate(ordered):
            self._layout.insertWidget(start + offset, widget, 0, Qt.AlignmentFlag.AlignTop)
        return True

    def _swap(self, first: int, second: int) -> None:
        """把布局里两个位置的顶级项对调（只动可拖动的那两个）。"""
        layout = self._layout
        a = layout.itemAt(first).widget()
        b = layout.itemAt(second).widget()
        if a is None or b is None:
            return
        layout.removeWidget(a)
        layout.removeWidget(b)
        low, high = min(first, second), max(first, second)
        layout.insertWidget(low, b if first == low else a, 0, Qt.AlignmentFlag.AlignTop)
        layout.insertWidget(high, a if first == low else b, 0, Qt.AlignmentFlag.AlignTop)

    def _handle_drag_move(self, dragged, global_y: int) -> None:
        layout = self._layout
        index = layout.indexOf(dragged)
        if index < 0:
            return

        movable = self._movable_widgets()

        previous = layout.itemAt(index - 1).widget() if index > 0 else None
        if previous in movable and global_y < self._center_y(previous):
            self._swap(index, index - 1)
            return

        nxt = layout.itemAt(index + 1).widget() if index + 1 < layout.count() else None
        if nxt in movable and global_y > self._center_y(nxt):
            self._swap(index, index + 1)

    # ------------------------------------------------------------ 事件
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 接口
        etype = event.type()

        if etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_y = event.globalPosition().toPoint().y()
                self._dragging = False
            return False

        if etype == QEvent.Type.MouseMove:
            if not (event.buttons() & Qt.MouseButton.LeftButton):
                return False
            y = event.globalPosition().toPoint().y()
            if not self._dragging:
                if abs(y - self._press_y) < DRAG_THRESHOLD:
                    return False
                self._dragging = True
                self._drag_widget = obj
                obj.setCursor(Qt.CursorShape.ClosedHandCursor)
                # 不 grabMouse 的话，鼠标一移出这一项就再也收不到 Move 事件，
                # 拖动只能生效一格
                obj.grabMouse()
            self._handle_drag_move(obj, y)
            return True

        if etype == QEvent.Type.MouseButtonRelease:
            if not self._dragging:
                return False
            self._dragging = False
            try:
                obj.releaseMouse()
            except RuntimeError:  # pragma: no cover - 控件已销毁
                pass
            obj.unsetCursor()
            # 框架的 mouseReleaseEvent 会无条件 emit clicked，吞掉它再手动复位按下态
            obj.isPressed = False
            obj.update()
            self._drag_widget = None
            if self._on_order_changed is not None:
                self._on_order_changed(self.current_order())
            return True

        return False
