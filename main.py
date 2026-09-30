"""鸣潮工具箱（WutheringWavesTools）入口。

    python main.py
    python main.py --debug     # 打开调试日志
"""

from __future__ import annotations

import argparse
import logging
import sys


def setup_logging(debug: bool) -> None:
    """配日志。

    打包成 GUI 程序（``console=False``）后**没有控制台**，``sys.stderr`` 是 None，
    日志等于直接丢掉 —— 所以打包版改成写文件到用户数据目录
    （用户数据目录下的 ``<APP_NAME>.log``，见 ``src/core/paths.py``），出问题时让用户把这个文件发过来。

    文件日志和屏幕日志的取舍不同，所以格式分开配：

    * 屏幕（开发态）：只有时分秒就够，看的是刚刚发生的事；
    * 文件（打包版）：**必须带日期**（隔天再看也认得出是哪天），
      并且**轮转**（``maxBytes`` + 备份 1 份）—— 否则一个长期在用的程序会把日志写到无限大。
    """
    import logging.handlers

    from src.core import paths

    # ⚠ **开发态也写文件**（2026-09-27 改）。
    #   原来只有打包后才写 —— 结果"任务跑失败了"这种情况在开发态**一点痕迹都不留**
    #   （stderr 在 GUI 里看不到），只能靠用户口述。日志是排查的前提。
    log_path = paths.log_file()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handlers: list[logging.Handler] = [file_handler]
    if not paths.is_frozen():
        # 开发态另外挂一个控制台出口 —— 光写文件的话在本机跑脚本时看不到实时输出
        console = logging.StreamHandler()
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                              datefmt="%H:%M:%S")
        )
        handlers.append(console)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger(__name__).info("日志文件：%s", paths.log_file())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # 版本号只有一个真源（src/app_config.APP_VERSION），别在这儿再写死一遍。
    # 这个导入是安全的：app_config 全是常量、不读任何数据文件，
    # 而且它在 parse_args() 里，不在 main() 顶层 —— 不会插到 ensure_user_data 前面
    # （tests/check_frozen_fixes.py 就扫 main() 顶层那一层）。
    from src.app_config import APP_DISPLAY_NAME, APP_NAME, APP_VERSION

    parser = argparse.ArgumentParser(description=f"{APP_DISPLAY_NAME}（{APP_NAME}）")
    parser.add_argument("--debug", action="store_true", help="打开调试日志")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def _check_admin() -> bool:
    """启动前的权限闸门：**不是管理员就拒绝启动**，返回是否放行。

    用户 2026-09-30 要求："增加应用启动时，如果不是管理员权限，启动失败，
    并提示需要以管理模式启动"。

    ## 为什么是"拒绝启动"而不是"提醒一下"

    鸣潮带反外挂（ACE），游戏自身跑在**高完整性级别**。Windows 的 UIPI 会
    静默丢掉低权限进程发往高权限窗口的**全部输入**（``PostMessage`` 也一样）——
    表现是"点了游戏没反应"，**而且不报错**。

    以前这里是"提醒 + 用户可以点『仍然继续』"：用户选了继续，进去之后每个游戏
    工具都点不动，还会去查"坐标是不是错了"。**与其让他带着一个注定不工作的
    状态往下走，不如当场拒绝。**

    ⚠ 打包版带了 ``requireAdministrator`` 清单（``packaging/mytools.spec``
    的 ``uac_admin=True``），正常情况下走不到这里；这段兜底的是
    **开发态直接 ``python main.py``**（用户明确要求开发态也拦）。

    ## 返回值

    ``True`` = 放行；``False`` = 不放行，调用方要**以非 0 退出**。

    非 Windows 直接放行（本项目只支持 Windows，但别让别的平台起不来）。
    """
    from src.core import elevation

    if not elevation.is_windows():
        return True

    level = elevation.own_integrity_level()
    if elevation.is_elevated():
        logging.getLogger(__name__).info(
            "已以管理员权限运行（%s）", elevation.level_name(level))
        return True

    logging.getLogger(__name__).error(
        "启动被拒绝：当前不是管理员权限（%s）—— 游戏在高完整性级别运行，"
        "本工具的点击/按键会被 UIPI 静默丢掉",
        elevation.level_name(level),
    )

    # Qt 已经起来了（调用点在 QApplication 之后），所以可以弹框。
    # 万一 Qt 没起好，也不能因为"弹不出框"就把闸门放过去 —— 那就白拦了。
    try:
        from PySide6.QtWidgets import QMessageBox

        restart = _ask_restart_as_admin()
    except Exception:  # noqa: BLE001 - 界面起不来时按下"不放行"处理
        logging.getLogger(__name__).exception("权限提示框弹不出来")
        restart = False

    if restart and elevation.relaunch_as_admin():
        logging.getLogger(__name__).info("已发起提权重启，本进程退出")
        return False

    return False


def _ask_restart_as_admin() -> bool:
    """弹"权限不足"框，返回用户是否选择以管理员身份重启。

    ⚠ 这里**不再提供"仍然继续"**（用户要求启动失败）—— 只给两个出口：
    提权重启，或退出。想继续就得先拿到权限。
    """
    from PySide6.QtWidgets import QMessageBox

    from src.app_config import APP_DISPLAY_NAME

    box = QMessageBox()
    box.setWindowTitle("权限不足，无法启动")
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(f"{APP_DISPLAY_NAME} 需要管理员权限才能启动。")
    box.setInformativeText(
        "鸣潮带反外挂（ACE），游戏本身运行在管理员权限下。\n"
        "Windows 会拦掉普通权限程序发出的点击和按键，表现是"
        "「点了游戏没反应」—— 而且不报错。\n\n"
        "所以本工具**必须**以管理员身份运行，否则所有游戏功能都用不了。\n\n"
        "点「以管理员身份重启」会弹出 UAC 确认框。"
    )
    restart = box.addButton("以管理员身份重启", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("退出", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(restart)
    box.exec()
    return box.clickedButton() is restart


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from src.core import paths

    # ⚠ 顺序是硬要求：**必须在任何 src.* 子模块被导入之前**把种子数据拷到位。
    #
    # 原因：src.core.game_data 是在 **import 的那一刻**就把 JSON 读进内存常量的。
    # 首启动时用户数据目录还不存在 → 它把"空数据"快照进内存，之后就算把种子拷进去
    # 也不会重读 → **这一轮资源库页面永远是空的**；而「资源库更新」读的是盘上的
    # 文件（那时已被拷好），内容与远端一致 → 它会说"数据已是最新"。
    # 一个看内存快照、一个看磁盘文件，于是两边看着自相矛盾。
    seeded = paths.ensure_user_data()

    # 日志要写到用户数据目录，所以放在 ensure 之后
    setup_logging(args.debug)
    if seeded:
        logging.getLogger(__name__).info(
            "首次运行，已初始化用户数据 %d 个文件 → %s", len(seeded), paths.user_data_dir()
        )

    # Qt 必须在任何 Widget 之前起来；导入顺序不能省这一点。
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme

    from src.core.registry import ToolRegistry
    from src.gui.compat import app_icon
    from src.gui.main_window import MainWindow
    from src.tools import discover_tools

    app = QApplication(sys.argv)
    # 应用级图标：任务栏、Alt+Tab、以及所有以 app 为父的对话框都用它。
    # 主窗口自己也设了一份（SetWindowIcon 会覆盖），但应用级这份不能省 ——
    # 否则没有主窗口时（如启动早期的报错框）又回到 python.exe 的默认图标。
    app.setWindowIcon(app_icon())

    # ★ 权限闸门（用户 2026-09-30 要求）：不是管理员就**启动失败**。
    #   放在 QApplication 之后（要弹框）、但在发现工具/建主窗口之前 ——
    #   权限不够时连主窗口都不该出现，免得用户以为"能用了"。
    if not _check_admin():
        return 1

    imported = discover_tools()
    metas = ToolRegistry.all_metas()
    logging.getLogger(__name__).info(
        "工具发现完成：%d 个模块，%d 个工具", len(imported), len(metas)
    )

    setTheme(Theme.AUTO)

    window = MainWindow()
    window.show()

    # ★ 主线程卡死看门狗（2026-09-27 用户报「应用卡死」后加的）。
    #   GUI 卡住时日志只会停在**某一行**，说明不了卡在哪个线程的哪一行 ——
    #   那次只能靠猜（猜了七八轮全是错的）。这里让主线程每 200ms 打一次点，
    #   超时没打点就把**所有线程的栈**写到 data/stall-*.txt。
    from PySide6.QtCore import QTimer

    from src.core.watchdog import HEARTBEAT_MS, StallWatchdog

    watchdog = StallWatchdog(dump_dir=paths.user_data_dir())
    watchdog.start()
    # parent 给 window：不靠局部变量保命，窗口一没定时器就跟着停
    _heartbeat = QTimer(window)
    _heartbeat.setInterval(HEARTBEAT_MS)
    _heartbeat.timeout.connect(watchdog.beat)
    _heartbeat.start()

    # ★ 启动即默认拉起 ok-ww 引擎（2026-09-24 用户要求）。
    #   延迟一点再调：boot 会 os.chdir 到 vendor 目录，
    #   别和「主窗口首帧 / 启动阶段的相对路径解析」抢。
    from src.tools.game.auto_combat.okww_boot import AUTOSTART_DELAY_MS

    QTimer.singleShot(AUTOSTART_DELAY_MS, _autostart_okww_engine)

    # 退出前收尾 ok-ww 宿主（引擎启动过就要收）
    app.aboutToQuit.connect(_shutdown_okww_host)

    return app.exec()


def _autostart_okww_engine() -> None:
    """启动后自动拉起 ok-ww 引擎（用户要求：启动应用就默认启动）。

    由 ``QTimer.singleShot`` 在**主窗口显示之后**调用 —— ``boot()`` 会
    ``os.chdir`` 到 vendor 目录，启动阶段还有相对路径要解析。
    boot 本身在后台守护线程里跑；失败只记日志，不挡程序启动。
    """
    try:
        from src.tools.game.auto_combat.okww_boot import autostart_engine

        autostart_engine()
    except Exception:  # noqa: BLE001 - 自启失败不能挡住程序启动
        logging.getLogger(__name__).warning("ok-ww 引擎自启失败", exc_info=True)


def _shutdown_okww_host() -> None:
    """Qt 退出钩子：置 ok-ww 的 exit_event，避免后台线程/任务残留。"""
    try:
        from src.tools.game.auto_combat.okww_boot import shutdown_host_if_any

        shutdown_host_if_any()
    except Exception:  # noqa: BLE001 - 收尾失败不能挡住退出
        logging.getLogger(__name__).debug("okww host shutdown 失败", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(main())
