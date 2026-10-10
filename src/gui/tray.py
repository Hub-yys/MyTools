"""托盘图标 + 关闭确认。

## 为什么单独一个模块

`main_window.py` 已经 300+ 行；而「哪个工具在跑 → 该弹哪种确认框」是**纯决策**，
单独放这里可以被 `tests/` 直接覆盖，不用起 GUI。

## 三件事

1. **托盘常驻**：主窗口能隐藏到托盘，工具/任务继续在后台跑。
2. **关闭确认（无任务）**：问「隐藏到托盘」还是「直接退出」。
3. **关闭确认（有任务在跑）**：先点明**是哪个工具/任务**在跑，再问「停止并退出」。

## 设计取舍

* **没有托盘就退化成最小化**：极少数环境（无头会话）拿不到系统托盘，
  这时不能因为"没托盘"就把关闭确认也一起废掉 —— 确认框照弹，
  只是「隐藏到托盘」退化成「最小化到任务栏」。
* **点运行后自动缩到托盘**由界面层接线（见 ``main_window`` 注册的
  ``add_task_started_listener``）—— 本模块不关心谁触发。
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..app_config import APP_DISPLAY_NAME

logger = logging.getLogger(__name__)

#: 关闭确认的三种结果
CLOSE_HIDE = "hide"       # 隐藏到托盘 / 最小化（不退出）
CLOSE_QUIT = "quit"       # 真正退出程序
CLOSE_CANCEL = "cancel"   # 什么都不做，留在原地


def tray_available() -> bool:
    """系统托盘能不能用。

    无头 / 某些远程会话里是 False。**不抛异常** —— 拿不到就当没有。
    """
    try:
        return bool(QSystemTrayIcon.isSystemTrayAvailable())
    except Exception:  # noqa: BLE001
        return False


def running_task_name(host) -> str | None:
    """有任务在跑就返回它的可读名字，否则 None。

    纯逻辑、不依赖 Qt，可单测。``host`` 传 None（引擎没起来）也安全。
    """
    if host is None:
        return None
    try:
        running = host.running_task
    except Exception:  # noqa: BLE001 - 宿主状态异常不该挡住关闭流程
        return None
    return str(running) if running else None


def close_question(running_task: str | None,
                   *, allow_hide: bool = True) -> tuple[str, str, str, str]:
    """按「有没有任务在跑」生成关闭确认框的文案。

    返回 ``(标题, 正文, 主按钮文字, 次按钮文字)``。

    ``allow_hide=False``（系统托盘拿不到）时，**两个按钮都不能提"托盘"** ——
    那条路走不通，劝用户去点就是坑。这时"隐藏"统一说成"最小化到任务栏"。

    抽成纯函数是为了能直接断言文案 —— 这段最容易写错却最难人工覆盖
    （要真的关一次窗口、还得正好有任务在跑）。
    """
    hide_word = "隐藏到托盘" if allow_hide else "最小化到任务栏"

    if running_task:
        return (
            "工具/任务正在执行",
            f"「{running_task}」正在执行。\n\n"
            f"退出会先停止它（当前这一轮已经强化的声骸不会回退，"
            f"但剩余未处理的就留在原地了）。\n\n"
            f"要停止并退出，还是{hide_word}让它继续跑？",
            "停止并退出",
            hide_word,
        )
    return (
        f"关闭 {APP_DISPLAY_NAME}",
        f"要{hide_word}（程序继续在后台运行，任务和引擎都不受影响），"
        f"还是直接退出程序？",
        hide_word,
        "直接退出",
    )


def ask_close(parent, running_task: str | None, *, allow_hide: bool = True) -> str:
    """弹关闭确认框，返回 :data:`CLOSE_HIDE` / :data:`CLOSE_QUIT` / :data:`CLOSE_CANCEL`。

    三个出口分别对应：

    * ``yesButton``    —— 主按钮（用户最可能想要的那个）
    * ``cancelButton`` —— 次按钮
    * **右上角 X / Esc** —— :data:`CLOSE_CANCEL`：什么都不做，留在原地

    把 X/Esc 映射成「取消」而不是「退出」是刻意的：误按 X 的代价必须最小。
    """
    from qfluentwidgets import MessageBox

    title, text, yes_text, cancel_text = close_question(
        running_task, allow_hide=allow_hide)

    box = MessageBox(title, text, parent)
    box.yesButton.setText(yes_text)
    box.cancelButton.setText(cancel_text)

    # ⚠ qfluentwidgets 的 MessageBox **没有 clickedButton()**（实测），
    #   而 exec() 对"点 cancelButton"和"按 X / Esc"都返回假 —— 两者必须分开：
    #   前者是用户明确选了次按钮，后者是什么都没选（应当视为取消）。
    #   所以自己挂一个标记。
    pressed: dict[str, bool] = {"secondary": False}
    try:
        box.cancelButton.clicked.connect(
            lambda *_: pressed.__setitem__("secondary", True)
        )
    except Exception:  # noqa: BLE001 - 挂不上就退化成"只有两种结果"
        pass

    accepted = bool(box.exec())

    if accepted:
        primary = True                      # 主按钮
    elif pressed.get("secondary"):
        primary = False                     # 明确点了次按钮
    else:
        return CLOSE_CANCEL                 # X / Esc

    # ⚠ CLOSE_HIDE 的含义是「别退出，去后台」，**不是**「一定有托盘」。
    #   到底缩托盘还是最小化到任务栏，由调用方按 tray_available() 决定 ——
    #   这里只管用户想不想退出。allow_hide 只影响上面那几句文案。
    if running_task:
        # 主按钮 = 停止并退出；次按钮 = 去后台继续跑
        return CLOSE_QUIT if primary else CLOSE_HIDE
    # 无任务：主按钮 = 去后台；次按钮 = 直接退出
    return CLOSE_HIDE if primary else CLOSE_QUIT


def _menu_palette() -> tuple[str, str, str]:
    """托盘菜单的 ``(底色, 文字色, 高亮底)`` —— 跟着当前皮肤走。

    ## ⚠⚠ 为什么必须**显式钉死**（用户 2026-10-09："托盘退出怎么都看不见"）

    菜单是 ``QMenu``（**裸 Qt 控件**），它的文字走 ``ButtonText`` 角色。
    皮肤只把调色板设成"深色皮肤对应的浅字"，看着没错 —— 但**实测渲染出来
    是深字压深底**，整块几乎纯色：

        深空玻璃（用户在用的）: 背景 rgb(11,16,38) / 最亮像素 rgb(1,2,4)
                                → 反差 **19/255**，字完全糊在底里
        晨雾玻璃（浅色）:       反差 223/255 → 正常

    ⚠ 我试过 ``app.setStyleSheet("")``、去掉窗口级 QSS、换 parent ——
    **都改不了它**；只有**给菜单自己**设配色才生效
    （四种组合的实测数据见 :func:`style_menu`）。
    所以这里不依赖调色板继承，直接把颜色算出来写上去。

    :return: ``(背景, 文字, 选中项背景)``，都是 ``#rrggbb``。
    """
    from ..core import skins

    try:
        skin = skins.active_skin()
        dark = skin["mode"] == "dark"
        #: 底色用**实心卡片色** —— 半透明的玻璃色铺在菜单上会透出桌面，很脏
        bg = skins.solid_card_on(skin["card"], skin["bg"][0][1], dark)
        text = skin["text"]
        hi = skin["primary"]
    except Exception:  # noqa: BLE001 - 皮肤坏了也得有个能看的菜单
        logger.debug("取皮肤色失败，托盘菜单退回深色默认", exc_info=True)
        return "#2b2b2b", "#f0f0f0", "#4a9eff"
    return bg, text, hi


def _rgb_tuple(color: str) -> tuple[int, int, int] | None:
    """``"#rrggbb"`` → ``(r, g, b)``；解析不出来返回 None。"""
    s = str(color or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _alpha(color: str, alpha: float) -> str:
    """把 ``#rrggbb`` + 透明度 → QSS 认的 ``rgba(r,g,b,a)``。

    ## ⚠⚠ 不能用 8 位十六进制 ``#rrggbbaa``

    Qt 的 QSS 把 8 位十六进制当 **``#AARRGGBB``**（alpha 在前），
    不是 CSS 的 ``#RRGGBBAA``。我第一版写成 ``{hi}40``（想加 25% 透明），
    实测被解析成 alpha=0x4A、R=0x9E、G=0xFF、B=0x40 —— 菜单边框变成
    **一条绿线**（像素 rgb(63,95,54)）。

    同一个坑本仓已经踩过一次（见 ``core/skins._rgba`` 的注释）。
    所以这里统一走 ``rgba()``。
    """
    rgb = _rgb_tuple(color)
    if rgb is None:
        return color
    return "rgba(%d, %d, %d, %.2f)" % (rgb[0], rgb[1], rgb[2], alpha)


def style_menu(menu) -> None:
    """把托盘菜单的配色**钉死**（见 :func:`_menu_palette`）。

    ## ⚠ 为什么调色板和样式表**两个都设**（实测数据，别删任何一个）

    在 Windows 平台下把四种组合都量了一遍（深空玻璃，渲染出来的反差）::

        都不设           19   ← 用户报的现象（深字压深底）
        只设调色板      206   ← 单独就够
        只设样式表      203   ← 单独也够
        两个都设        203   ← 现在这样

    → **任一个单独就能修好**，这里两个都写是**故意的冗余**：
    样式表负责底/选中条/圆角/分隔线（``QMenu::item`` 那些），
    调色板兜住"QSS 被覆盖 / 换肤时序错开"的情况。
    删掉任一条都不会立刻坏，所以更要留着这段注释说明**为什么**。
    """
    from PySide6.QtGui import QColor, QPalette

    bg, text, hi = _menu_palette()
    menu.setStyleSheet(
        f"QMenu {{ background: {bg}; color: {text};"
        f" border: 1px solid {_alpha(hi, 0.45)}; border-radius: 6px;"
        f" padding: 4px; }}"
        f"QMenu::item {{ padding: 6px 24px 6px 16px;"
        f" background: transparent; color: {text}; }}"
        f"QMenu::item:selected {{ background: {hi}; color: #ffffff; }}"
        f"QMenu::separator {{ height: 1px; background: {_alpha(text, 0.25)};"
        f" margin: 4px 10px; }}"
    )

    pal = menu.palette()
    for role, color in (
        (QPalette.ColorRole.Window, bg),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.ButtonText, text),
        (QPalette.ColorRole.Base, bg),
        (QPalette.ColorRole.Highlight, hi),
        (QPalette.ColorRole.HighlightedText, "#ffffff"),
    ):
        pal.setColor(role, QColor(color))
    menu.setPalette(pal)


def build_menu(parent, on_show, on_quit):
    """建托盘右键菜单（**不依赖系统托盘**，方便单测）。

    ⚠ 单独抽出来是有原因的：托盘本身在无头/远程会话里拿不到
    （``make_tray`` 直接返回 None），如果菜单只在 ``make_tray`` 里建，
    那"配色有没有刷上、换肤跟不跟"就**永远测不到** ——
    默认的 offscreen 测试环境下这两条只能 skip，等于没有护栏。
    """
    from PySide6.QtGui import QAction

    menu = QMenu(parent)
    act_show = QAction(f"显示 {APP_DISPLAY_NAME}", menu)
    # ⚠ triggered 会带一个 checked 参数，直接 connect 裸回调会 TypeError。
    #   用 lambda 吃掉它。
    act_show.triggered.connect(lambda *_: on_show())
    act_quit = QAction("退出", menu)
    act_quit.triggered.connect(lambda *_: on_quit())
    menu.addAction(act_show)
    menu.addSeparator()
    menu.addAction(act_quit)

    #: ★★ 菜单配色**显式钉死**，否则深色皮肤下"深字压深底"看不见
    #: （用户 2026-10-09："托盘退出怎么都看不见"，见 :func:`_menu_palette`）
    #:
    #: ⚠ 每次弹出前**重刷一遍**，不只在这里设一次：换肤后要跟着变。
    #:   挂 ``aboutToShow`` 比注册回调更稳 —— 那套 ``refresh_skin_colors``
    #:   机制依赖"菜单挂在窗口下、且换肤时窗口已存在"，
    #:   而这里无论什么时候右键，用的都是**当下**的皮肤色。
    menu.aboutToShow.connect(lambda _m=menu: style_menu(_m))
    style_menu(menu)
    return menu


def make_tray(parent, on_show, on_quit, icon=None) -> QSystemTrayIcon | None:
    """建托盘图标。拿不到托盘返回 None（调用方退化成"最小化"）。

    ``on_show`` / ``on_quit`` 是两个回调：显示主窗口、退出程序。

    ⚠ **失败一定要记日志**。第一版这里写的是 ``except Exception: return None``
    （本意"托盘建不起来不该拖垮程序"），结果把 ``QMenu`` 漏导入导致的
    ``NameError`` 一起吞了 —— 表现是**托盘永远建不出来、界面永远最小化到任务栏**，
    而日志里一个字都没有，全靠手工逐步复现才查出来。
    "不该拖垮程序"不等于"不该留下痕迹"。
    """
    if not tray_available():
        logger.info("系统托盘不可用，托盘图标跳过（关闭/缩小时退化成最小化）")
        return None
    try:
        from qfluentwidgets import FluentIcon

        tray = QSystemTrayIcon(parent)
        if icon is not None and not icon.isNull():
            tray.setIcon(icon)
        else:
            # 传进来的图标是空的（没调 setWindowIcon 就是这样）——
            # 退回 fluent 自带图标，总比任务栏里显示"没有图标"强
            tray.setIcon(FluentIcon.APPLICATION.icon())
        tray.setToolTip(APP_DISPLAY_NAME)

        menu = build_menu(parent, on_show, on_quit)   #: 见 :func:`build_menu`
        tray.setContextMenu(menu)
        # 菜单得挂在 tray 上，否则可能被 GC 掉（右键点不出来）
        tray._menu_ref = menu          # noqa: SLF001 - 仅为了持有引用

        # 左键单击托盘图标 → 直接把窗口叫回来（比让用户找右键菜单顺手）
        tray.activated.connect(
            lambda reason: on_show()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.show()
        logger.info("托盘图标已创建")
        return tray
    except Exception:  # noqa: BLE001 - 托盘建不起来也不该拖垮程序
        logger.warning("托盘图标创建失败，退化成最小化到任务栏", exc_info=True)
        return None
