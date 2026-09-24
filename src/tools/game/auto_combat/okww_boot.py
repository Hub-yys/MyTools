# -*- coding: utf-8 -*-
"""ok-ww 引擎宿主：把 vendored 的 ok-ww（``vendor/okww``，AGPL-3.0）无 GUI 跑起来。

职责边界：
* MyTools 只做 **宿主**——构建 ok-script 的 config、在后台线程启动 :class:`ok.OK`、
  通过 ``start_controller`` 启停任务、收集日志。
* 战斗本体全部是 ok-ww 原代码（``okww.task.FarmEchoTask`` / ``AutoCombatTask``），
  模板匹配 / OCR / 后台按键（PostMessage）都走 ok-script 自己的体系，
  **不经过** MyTools 的 ``GameWindow``/``EchoController``。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

from ....core import paths

from . import report

#: vendored 的 ok-ww 根目录（开发态=仓库 vendor/okww；打包态=_MEIPASS/vendor/okww）
VENDOR_DIR = paths.resource_dir("vendor", "okww")

#: 页面上暴露的任务（name -> ok-ww 侧的完整任务名）
TASKS = {
    # 4C 刷声骸用 MyTools 的子类：只多一个「读拾取角标」的计数钩子（见 okww_farm.py），
    # 刷取流程本身还是 ok-ww 的。
    "4C 刷声骸": "MyToolsFarmEchoTask",
    "自动战斗": "AutoCombatTask",      # ⚔️ Auto Combat（触发式：进战斗自动输出）
    # 声骸自动强化：流程是 ok-ww 的，判定条件换成本工具页上那一套
    "声骸自动强化": "MyToolsEnhanceEchoTask",
}

#: 工具页点「启动」时固定跑的任务
DEFAULT_TASK_KEY = "4C 刷声骸"

#: 程序启动后多久**自动**拉起引擎（毫秒）。
#: 留出时间让主窗口先画出来 —— ``boot()`` 会 ``os.chdir`` 到 vendor 目录，
#: 晚一点做就不影响启动阶段的相对路径解析。
AUTOSTART_DELAY_MS = 2500

_OK_LOGGER_NAME = "ok"

#: NotificationManager 是否已打过「不建系统托盘」补丁（boot 重试时只 patch 一次）
_notification_patched = False


def _install_no_system_notifier() -> None:
    """让 ok 的 NotificationManager **永不创建** Windows 托盘通知窗口。

    为什么：``HeadlessApp.__init__`` 在 ``do_init`` 里就会建
    ``WindowsSystemNotifier``——一个隐藏 Win32 窗口 + 一个托盘图标
    （图标加载失败时是系统默认的「小窗口」）。MyTools 退出路径以前只
    ``exit_event.set()``，从不 ``NIM_DELETE``，于是每跑一次就残留一个，
    任务栏托盘区堆一排一模一样的图标。

    宿主不需要系统气泡通知（日志已按日期落盘），所以直接在构造参数里
    传 ``system_notifier=None``，图标根本不会注册。
    """
    global _notification_patched
    if _notification_patched:
        return
    try:
        from ok.notification import NotificationManager  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - ok 还没装好时静默，boot 自己会报错
        return
    if getattr(NotificationManager, "_mytools_no_tray", False):
        _notification_patched = True
        return
    original_init = NotificationManager.__init__

    def _init_without_tray(self, *args, **kwargs):
        kwargs["system_notifier"] = None
        original_init(self, *args, **kwargs)

    NotificationManager.__init__ = _init_without_tray  # type: ignore[method-assign]
    NotificationManager._mytools_no_tray = True  # type: ignore[attr-defined]
    _notification_patched = True


def _load_vendor_config_module():
    """加载 vendor 根目录的 ok-ww ``config.py``（它不在 okww 包内，按文件路径加载）。"""
    import importlib.util  # noqa: PLC0415

    path = VENDOR_DIR / "config.py"
    spec = importlib.util.spec_from_file_location("okww_root_config", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["okww_root_config"] = module
    spec.loader.exec_module(module)
    return module


def build_config() -> dict:
    """构建 ok-script 的 config dict（改编自 ok-ww ``config.py``，改动点见注释）。"""
    if str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))

    vendor_config = _load_vendor_config_module()
    key_config_option = vendor_config.key_config_option
    char_config_option = vendor_config.char_config_option
    monthly_card_config_option = vendor_config.monthly_card_config_option
    calculate_pc_exe_path = vendor_config.calculate_pc_exe_path

    user_dir = paths.user_data_dir() / "okww"
    return {
        "debug": False,
        "custom_tasks": True,
        # ok-ww 原配置是 gui qt；宿主是无 GUI 的（resolve_ui_config(None) → headless）
        "config_folder": str(user_dir / "configs"),
        "global_configs": [key_config_option, char_config_option, monthly_card_config_option],
        # ok-ww 原配置 use_openvino/use_npu=True；本机没装 openvino，
        # onnxocr 走 onnxruntime（MyTools 已装且声骸工具在用）
        "ocr": {
            "lib": "onnxocr",
            "auto_simplify": True,
            "params": {"use_openvino": False, "use_npu": False},
        },
        "my_app": ["okww.globals", "Globals"],
        "start_timeout": 120,
        "wait_until_settle_time": 0,
        "template_matching": {
            "coco_feature_json": str(VENDOR_DIR / "assets" / "coco_annotations.json"),
            "default_horizontal_variance": 0.002,
            "default_vertical_variance": 0.002,
            "default_threshold": 0.8,
            "feature_processor": None,   # 由 OK 侧从 okww.task.process_feature 解析，见下
            "vcenter_features": ["monthly_card", "skip_dialog_check"],
            "hcenter_features": ["monthly_card", "suisui_forte3", "message_dialog", "claim_stamina_sign",
                                 "skip_dialog_check", "login_close", "garden_confirm", "garden_continue_game",
                                 "garden_unpause", "garden_get_gold", "garden_get_purple", "garden_get_skip",
                                 "garden_not_interested_confirm", "garden_not_interested", "a_garden_back",
                                 "garden_get_confirm_gray", "the_garden_max", "garden_shop_close", "garden_new_stage",
                                 "a_garden_restart", "suisui_forte2", "suisui_e1", "e_forte", "f_break_full"],
        },
        "windows": {
            # ↓ 与 ok-ww config.py 原文一致（含登录弹窗的 top_hwnd_class 白名单）
            "top_hwnd_class": [re.compile("CAgreementDlg"), re.compile("CLoginDlg_P_"),
                               "CefBrowserWindow", "Chrome_RenderWidgetHostHWND", "#32770",
                               re.compile("CNativeLoginDlg"), "Static", "ComboBox", "ComboLBox", "Button"],
            "calculate_pc_exe_path": calculate_pc_exe_path,   # 注册表定位游戏 → 支持自动启动游戏
            "exe": "Client-Win64-Shipping.exe",
            "hwnd_class": "UnrealWindow",
            "interaction": "PostMessage",    # 后台按键，不抢前台
            "capture_method": ["WGC", "BitBlt_RenderFull"],
            "check_hdr": False,
            "force_no_hdr": False,
            "check_night_light": True,
            "force_no_night_light": False,
        },
        "supported_resolution": {
            "ratio": "16:9",
            "resize_to": [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720)],
            "min_size": (1280, 720),
        },
        "onetime_tasks": [
            # 4C 刷声骸走 MyTools 的子类（ok-ww 流程 + 拾取角标计数）。
            # vendored 的 okww.task.FarmEchoTask 不再单独注册 ——
            # 两个同名任务并存只会让人分不清跑的是哪个。
            ["src.tools.game.auto_combat.okww_farm", "MyToolsFarmEchoTask"],
            ["okww.task.MergeEchoTask", "MergeEchoTask"],
            # 声骸自动强化用 MyTools 的子类（ok-ww 流程 + 本工具筛选条件）。
            # vendored 的 okww.task.EnhanceEchoTask 不再单独注册 ——
            # 两套筛选条件并存只会让人分不清哪个在生效。
            ["src.tools.game.echo_enhance.okww_task", "MyToolsEnhanceEchoTask"],
            ["okww.task.ChangeEchoTask", "ChangeEchoTask"],
        ],
        "trigger_tasks": [
            ["okww.task.AutoCombatTask", "AutoCombatTask"],
            ["okww.task.AutoPickTask", "AutoPickTask"],
            ["okww.task.MouseResetTask", "MouseResetTask"],
        ],
        "scene": ["okww.scene.WWScene", "WWScene"],
        "screenshots_folder": str(user_dir / "screenshots"),
        "log_file": str(user_dir / "logs" / "ok-ww.log"),
        "error_log_file": str(user_dir / "logs" / "ok-ww_error.log"),
        "version": "ok-ww vendored (AGPL-3.0)",
        # MyTools 是宿主：mutex/自动更新都是 ok-ww 独立发行版的行为，这里关掉
        "check_mutex": False,
        "update_pyappify": None,
    }


def _wire_feature_processor(config: dict) -> None:
    """coco 的 feature_processor 需要真正导入 okww.task.process_feature。

    放在单独一步：build_config 保持可单测（不触发 okww 导入链）。
    """
    from okww.task.process_feature import process_feature  # noqa: PLC0415

    config["template_matching"]["feature_processor"] = process_feature


#: 日志保留天数（用户要求：按日期分区、每月定时清理）
LOG_RETENTION_DAYS = 31


def clean_old_logs(log_dir: Path, days: int = LOG_RETENTION_DAYS) -> int:
    """删除 ``log_dir`` 里超过 ``days`` 天没修改过的 .log 文件，返回删除数。

    ok-script 自己按天轮转且只留 7 天（``SafeFileHandler``）；这里兜底清理
    它不管的文件（error 日志、崩溃残留、legacy 命名等），保证日志目录
    **每月定期清一次**。目录不存在 / 无文件时静默返回 0。
    """
    import time as _time  # noqa: PLC0415

    cutoff = _time.time() - days * 86400
    removed = 0
    if not log_dir.is_dir():
        return 0
    for f in log_dir.rglob("*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue  # 被占用/权限问题：跳过，下次再清
    return removed


class _RingHandler(logging.Handler):
    """把 ok logger 的记录塞进定长队列（内存里留最近几百条，供诊断用）。"""

    def __init__(self, ring: deque):
        super().__init__()
        self.ring = ring

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = "%s %s" % (record.levelname[:4], record.getMessage())
        except Exception:  # noqa: BLE001
            return
        self.ring.append(msg)


def _force_disable_system_notification(ok) -> None:
    """双保险：配置层关掉系统通知，并拆掉可能已建好的托盘图标。

    构造参数补丁（:func:`_install_no_system_notifier`）是第一道闸；
    这里在 OK() 起来后再关一次 —— 覆盖「补丁没装上 / 旧配置文件仍为开」的情况。
    """
    try:
        headless = getattr(ok, "_headless_app", None)
        if headless is None:
            # do_init 正常路径已创建；属性访问会兜底建一次（同样会走补丁）
            headless = ok.headless_app
        nm = getattr(headless, "notification_manager", None)
        if nm is None:
            return
        try:
            # Config.__setitem__ 会写盘；System Notification=False → notify_system 直接短路
            nm.config["System Notification"] = False
        except Exception:  # noqa: BLE001 - 配置写失败不挡 boot
            pass
        notifier = getattr(nm, "system_notifier", None)
        if notifier is not None:
            try:
                notifier.close()  # NIM_DELETE + 销毁隐藏窗口
            except Exception:  # noqa: BLE001
                pass
            nm.system_notifier = None
    except Exception:  # noqa: BLE001 - 通知收尾失败不影响引擎就绪
        pass


def make_file_handler() -> logging.Handler:
    """ok 日志的**后台文件落盘**：按日期分区、保留 31 天（≈月度清理）。

    为什么不用 ok 自己的文件日志：它的 ``config_logger`` **忽略 config 里的
    ``log_file``**，写死相对 cwd 的 ``logs/ok-script.log``，还会清空 root
    logger 的 handlers（把 MyTools 自己的日志也干掉）。所以这里配置
    ``disable_file_log=True`` 关掉它的文件日志，由宿主接管：每天一个文件
    ``ok-ww.log.YYYY-MM-DD``，``TimedRotatingFileHandler`` 自己按 backupCount
    删旧的 —— 「每月定时清理」由 logging 机制天然完成。
    """
    log_dir = paths.user_data_dir() / "okww" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "ok-ww.log", when="midnight", interval=1,
        backupCount=31, encoding="utf-8", delay=True,
    )
    handler.suffix = "%Y-%m-%d"
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                                           datefmt="%Y-%m-%d %H:%M:%S"))
    return handler


class OkwwHost:
    """ok-ww 运行时的宿主。一次进程只 boot 一个 OK 实例（ok 的 og 是全局单例）。

    **2026-09-24 起：程序启动时默认就把引擎拉起来**（:func:`autostart_engine`，
    由 ``main.py`` 在主窗口显示后延迟调用）。工具页点「启动」变成**只负责开任务** ——
    引擎还没就绪时会兜底 ``boot``，失败态也能从这里重试；
    另外支持「引擎就绪后自动开任务」（排队启动）。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._booting = False
        self._ok = None                 # ok.OK 实例
        self._boot_error: str | None = None
        self._logs: deque[str] = deque(maxlen=500)
        self._running_task: str | None = None
        self._pending_start: str | None = None
        #: 与 _pending_start 配对的"注入回调"（见 start_task 的 configure 参数）
        self._pending_configure = None
        # --- 战斗报告（本次运行的统计）---
        #: 开跑前快照的 ok-ww 计数器：info 在同一进程里跨次累加，报告要的是差值
        self._report_baseline: dict[str, int] = {}
        #: 本次运行的起止时刻（0 = 没跑过 / 还没停）
        self._report_started_at = 0.0
        self._report_stopped_at = 0.0
        #: 报告读哪个任务 —— 跑完 _running_task 会清空，所以要单独记着
        self._report_task_key: str | None = None
        #: 最近一次"启动任务失败"的信息。工具页取走并弹一次 InfoBar ——
        #: 「引擎就绪后才开任务」那条路以前只有日志，页面上什么都看不到。
        self._last_start_error: str | None = None
        #: 任务**结束**时留下的最后一份 info（键=任务 key）。
        #: 框架结束一次性任务时会把它从列表里摘掉，之后 find_task 拿不到 ——
        #: 不存一份快照的话，结果报告会丢掉最后几百毫秒里的数字。
        self._finished_info: dict[str, dict] = {}

    # ------------------------------------------------------------ 状态查询
    @property
    def state(self) -> str:
        with self._lock:
            if self._booting or self._pending_start:
                return "booting"
            if self._boot_error and self._ok is None:
                return "error"
            if self._ok is None:
                return "idle"
            if self._running_task:
                return "running"
            return "ready"

    @property
    def boot_error(self) -> str | None:
        with self._lock:
            return self._boot_error

    @property
    def running_task(self) -> str | None:
        with self._lock:
            return self._running_task

    @property
    def pending_start(self) -> str | None:
        with self._lock:
            return self._pending_start

    def logs(self) -> list[str]:
        with self._lock:
            return list(self._logs)

    def task_summary(self, task_key: str) -> str:
        """任务当前配置的一行摘要（给日志/页面用）。"""
        task = self.find_task(task_key)
        if task is None:
            return ""
        cfg = getattr(task, "config", {}) or {}
        keep = [k for k in getattr(task, "default_config", {}) if not k.startswith("_")]
        return "，".join("%s=%s" % (k, cfg.get(k)) for k in keep if k in cfg)

    def battle_report(self) -> "report.BattleReport | None":
        """本次运行的战斗报告（还没跑过就返回 None）。

        数字全部来自 ok-ww 自己的计数器（见 :mod:`.report` 的模块文档），
        这里只负责把它们和宿主掐的时间拼起来。
        """
        with self._lock:
            key = self._report_task_key
            baseline = dict(self._report_baseline)
            started = self._report_started_at
            stopped = self._report_stopped_at
            running = bool(self._running_task)
        if not key or not started:
            return None
        task = self.find_task(key)
        if task is None:
            return None
        return report.read_report(task, baseline=baseline, started_at=started,
                                  stopped_at=stopped, running=running)

    def take_start_error(self) -> str | None:
        """取出并清空"最近一次启动失败"（取过即清，不会重复弹）。

        为什么需要：如果任务只是因为引擎还没就绪而排队，失败信息以前**只进日志**，
        页面上什么都看不到 —— 用户看到的现象就是"点了运行，没反应"。
        """
        with self._lock:
            message = self._last_start_error
            self._last_start_error = None
            return message

    def registered_task_names(self) -> list[str]:
        """引擎里**真正注册**了的任务类名 —— 排查"任务找不到"的第一手信息。"""
        with self._lock:
            ok = self._ok
        if ok is None:
            return []
        executor = ok.task_executor
        return [t.__class__.__name__
                for t in list(executor.onetime_tasks) + list(executor.trigger_tasks)]

    def _not_registered_message(self, task_key: str) -> str:
        """任务没注册时的报错 —— 把"为什么会这样"一起说出来。

        （2026-09-24：ok-script 会因为 supported_languages 与引擎语言不符而
        **静默跳过**任务。只说一句"找不到任务"，排查起来要翻半天源码。）
        """
        return ("任务「%s」（类名 %s）没有注册到 ok-ww 引擎里。已注册：%s。"
                "常见原因：任务类的 supported_languages 与引擎语言不符 —— "
                "ok-script 会静默跳过这类任务；或任务模块导入失败。"
                "详情见 %s 当天日志。"
                % (task_key, TASKS.get(task_key),
                   "、".join(self.registered_task_names()) or "（无）",
                   paths.user_data_dir() / "okww" / "logs"))

    # ------------------------------------------------------------ 启动 / 停止
    def boot(self) -> None:
        """在后台启动 ok 运行时（幂等；失败后可重试）。"""
        with self._lock:
            if self._ok is not None or self._booting:
                return
            self._boot_error = None      # 允许从 error 态重试
            self._booting = True
            self._thread = threading.Thread(target=self._boot_in_thread,
                                            name="okww-boot", daemon=True)
            self._thread.start()

    def _boot_in_thread(self) -> None:
        try:
            # ok 的一些资源按「exe 目录 → cwd」兜底查找；把 cwd 固定到 vendor 目录
            os.chdir(VENDOR_DIR)
            # 兜底清理：ok 自己不管的旧日志 / 崩溃残留（正常按日期的日志由
            # make_file_handler 的 backupCount=31 自动删）
            removed = clean_old_logs(paths.user_data_dir() / "okww" / "logs")
            if removed:
                self._log("已清理 %d 个过期日志文件" % removed)
            config = build_config()
            # 关掉 ok 自己的文件日志（它写死相对 cwd 的路径，还会清空 root handlers）
            config["disable_file_log"] = True
            _wire_feature_processor(config)
            ok_logger = logging.getLogger(_OK_LOGGER_NAME)
            root_handlers = list(logging.getLogger().handlers)   # ok 会清空 root，先留底
            try:
                from ok import OK  # noqa: PLC0415  # cwd 就位后再导入
                # 必须在 OK() 之前：HeadlessApp 在 do_init 里就会建托盘通知
                _install_no_system_notifier()
                self._ok = OK(config)
                _force_disable_system_notification(self._ok)
            finally:
                root = logging.getLogger()
                if not root.handlers and root_handlers:
                    root.handlers.extend(root_handlers)
                    self._log("已恢复 MyTools 的根日志 handlers")
            # ⚠ ok 的 config_logger 会**重置 ok logger 的 handlers**，
            # 所以宿主的 handler 必须在 OK() 之后挂（每次 boot 只有一次 OK()，不会重复）
            ok_logger.addHandler(make_file_handler())
            ok_logger.addHandler(_RingHandler(self._logs))
            with self._lock:
                self._booting = False
                self._boot_error = None
            self._log("ok-ww 运行时就绪；日志按日期写 %s"
                      % (paths.user_data_dir() / "okww" / "logs"))
            self._log("已关闭系统托盘通知（不需要气泡，避免退出后残留图标）")
            self._flush_pending_start()
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._booting = False
                self._boot_error = "%s: %s" % (type(e).__name__, e)
                self._pending_start = None
            self._log("✗ ok-ww 启动失败：%s" % self.boot_error)

    def _flush_pending_start(self) -> None:
        """引擎就绪后，把点「启动」时排队的任务真正开起来。"""
        with self._lock:
            key = self._pending_start
            configure = self._pending_configure
            self._pending_start = None
            self._pending_configure = None
        if not key:
            return
        err = self.start_task(key, configure=configure)
        if err:
            self._log("✗ 引擎就绪后自动开任务失败：%s" % err)
            with self._lock:
                self._last_start_error = err      # 页面上也要能看到

    def start_task(self, task_key: str, configure=None) -> str | None:
        """启动任务。引擎未就绪时先 boot，并在就绪后自动开（返回 None=已受理）。

        ``configure`` 是可选回调：在**任务实例拿到之后、真正开跑之前**调用一次，
        用来把宿主这边的运行时配置注入任务（例如声骸强化的判定条件 ——
        那是工具页上用户配的，ok-ww 的任务本身不知道）。

        返回错误信息（None=成功受理 / 已排队）。
        """
        with self._lock:
            if task_key not in TASKS:
                return "找不到任务 %s" % task_key
            if self._running_task:
                return "已有任务在跑：%s" % self._running_task
            if self._pending_start:
                if self._pending_start == task_key:
                    return None      # 同一任务已在排队，重复点启动视为已受理
                return "引擎启动中，正在准备任务：%s" % self._pending_start
            if self._ok is None:
                # 点「启动」才拉引擎；失败态也走这里重试
                self._pending_start = task_key
                self._pending_configure = configure
                self.boot()
                self._log("▶ 引擎未就绪，后台启动中；就绪后自动开始：%s" % task_key)
                return None

        task = self.find_task(task_key)
        if task is None:
            return self._not_registered_message(task_key)
        if configure is not None:
            try:
                configure(task)
            except Exception as e:  # noqa: BLE001
                return "注入任务配置失败：%s: %s" % (type(e).__name__, e)
        # ★ 战斗报告：必须在**开跑之前**取基线 —— ok-ww 的 info 跨次累加，
        #   差值才是「本次运行」的数量。
        baseline = report.snapshot_counters(task)
        report.reset_pickup_tally()   # 拾取角标计数同样按「本次运行」清零
        with self._lock:
            self._finished_info.pop(task_key, None)   # 新一次运行 → 旧快照作废
        try:
            started = self._ok.headless_app.start_controller.do_start(task)
        except Exception as e:  # noqa: BLE001
            return "%s: %s" % (type(e).__name__, e)
        if not started:
            return ("启动失败（常见原因是没开游戏 / 不是管理员 / 窗口模式）；"
                    "详情见 %s 当天日志" % (paths.user_data_dir() / "okww" / "logs"))
        with self._lock:
            self._running_task = task_key
            self._report_baseline = baseline
            self._report_started_at = time.time()
            self._report_stopped_at = 0.0
            self._report_task_key = task_key
        self._log("▶ 已启动任务：%s" % task_key)
        return None

    def stop_task(self) -> str | None:
        with self._lock:
            # 取消尚未执行的排队启动
            if self._pending_start and not self._running_task:
                self._pending_start = None
                self._pending_configure = None
                self._log("■ 已取消排队中的启动")
                return None
            if self._ok is None:
                if self._running_task:
                    self._running_task = None
                return "ok-ww 还没启动"
            if not self._running_task:
                return None
        try:
            executor = self._ok.task_executor
            if executor.current_task is not None:
                executor.stop_current_task()
            executor.pause()
            executor.start()   # 恢复 executor 循环，便于下次直接再启动
            for t in executor.trigger_tasks:
                t.disable()
        except Exception as e:  # noqa: BLE001
            return "%s: %s" % (type(e).__name__, e)
        task = self.find_task(self._report_task_key) if self._report_task_key else None
        info = getattr(task, "info", None) if task is not None else None
        with self._lock:
            if isinstance(info, dict) and info:
                self._finished_info[self._report_task_key] = dict(info)
            self._running_task = None
            if self._report_started_at and not self._report_stopped_at:
                self._report_stopped_at = time.time()   # 时长就地冻结，别再走字
        self._log("■ 已停止任务")
        return None

    def shutdown(self) -> None:
        """程序退出时调用：停通知（删托盘图标）并置退出事件。

        **不要**调 ``OK.quit()`` —— 它在 Qt 路径下会 ``QMetaObject.invokeMethod``；
        这里只走 ``HeadlessApp.quit()``：``notification_manager.stop()`` 会
        ``NIM_DELETE`` 托盘图标，再 ``exit_event.set()``。以前只 set 事件，
        托盘图标会留在任务栏直到资源管理器刷新。
        """
        with self._lock:
            ok = self._ok
            self._pending_start = None
            self._pending_configure = None
            self._booting = False
        if ok is None:
            return
        headless = getattr(ok, "_headless_app", None)
        if headless is not None:
            try:
                headless.quit()   # 删托盘 + disconnect 通知 + set exit_event
                return
            except Exception:  # noqa: BLE001 - 收尾失败也要保证进程能退
                logging.getLogger(__name__).debug("headless quit 失败", exc_info=True)
        # 兜底：没 headless 或 quit 抛错时，至少再试一次删托盘 + 置退出事件
        try:
            nm = getattr(headless, "notification_manager", None) if headless else None
            if nm is not None:
                nm.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            ok.exit_event.set()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 内部
    def find_task(self, task_key: str):
        name = TASKS.get(task_key)
        if name is None or self._ok is None:
            return None
        executor = self._ok.task_executor
        for t in list(executor.onetime_tasks) + list(executor.trigger_tasks):
            if t.__class__.__name__ == name:
                return t
        return None

    def finished_info(self, task_key: str) -> dict:
        """任务结束后留下的最后一份统计（没有则空 dict）。"""
        with self._lock:
            return dict(self._finished_info.get(task_key) or {})

    def poll_done(self) -> None:
        """工具页的定时器调用：检测一次性任务是否已结束。"""
        with self._lock:
            key, ok = self._running_task, self._ok
        if key and ok is not None:
            task = self.find_task(key)
            # 启动瞬间 running 还是 False：要等它跑过再结束（enabled 被任务自己清掉）
            # 才算完成，避免刚开就误判「已结束」。
            if task is not None and not task.running and not task.enabled:
                info = getattr(task, "info", None)
                with self._lock:
                    if isinstance(info, dict) and info:
                        self._finished_info[key] = dict(info)   # 摘掉前留一份
                    self._running_task = None
                    if self._report_started_at and not self._report_stopped_at:
                        self._report_stopped_at = time.time()
                self._log("■ 任务结束：%s" % key)

    def _log(self, message: str) -> None:
        with self._lock:
            self._logs.append("[鸣潮工具箱] " + message)


_host: OkwwHost | None = None
_host_lock = threading.Lock()


def get_host() -> OkwwHost:
    global _host
    with _host_lock:
        if _host is None:
            _host = OkwwHost()
        return _host


def autostart_engine() -> None:
    """启动应用时自动拉起 ok-ww 引擎（用户要求：启动该应用就默认启动）。

    ``boot()`` 自己就在后台守护线程里跑，不会卡界面；``boot()`` 也是幂等的
    （已在启动/已就绪时直接返回），所以重复调用无害。

    这里**吞掉异常只记日志**：引擎起不来不该挡住整个程序启动 ——
    游戏没开时 boot 其实也能成功（只是稍后开不了任务），真失败也只体现在
    工具页的状态行里，用户可以点「启动」重试。
    """
    try:
        get_host().boot()
    except Exception:  # noqa: BLE001 - 自启失败不能影响程序启动
        logging.getLogger(__name__).warning("ok-ww 引擎自启失败", exc_info=True)


def shutdown_host_if_any() -> None:
    """程序退出时调用：宿主已创建过就收尾，没创建过则什么都不做。

    收尾包含 **删系统托盘通知图标**（见 ``OkwwHost.shutdown``），
    避免每跑一次工具就在任务栏残留一个默认「小窗口」图标。
    """
    with _host_lock:
        host = _host
    if host is not None:
        host.shutdown()
