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
        from PySide6.QtGui import QAction
        from qfluentwidgets import FluentIcon

        tray = QSystemTrayIcon(parent)
        if icon is not None and not icon.isNull():
            tray.setIcon(icon)
        else:
            # 传进来的图标是空的（没调 setWindowIcon 就是这样）——
            # 退回 fluent 自带图标，总比任务栏里显示"没有图标"强
            tray.setIcon(FluentIcon.APPLICATION.icon())
        tray.setToolTip(APP_DISPLAY_NAME)

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
