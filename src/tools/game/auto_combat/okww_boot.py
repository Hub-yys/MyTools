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

#: vendored 的 ok-ww 根目录（开发态=仓库 vendor/okww；打包态=_MEIPASS/vendor/okww）
VENDOR_DIR = paths.resource_dir("vendor", "okww")

#: 页面上暴露的任务（name -> ok-ww 侧的完整任务名）
TASKS = {
    "4C 刷声骸": "FarmEchoTask",      # 🌀 Farm 4C Echo in Dungeon/World
    "自动战斗": "AutoCombatTask",      # ⚔️ Auto Combat（触发式：进战斗自动输出）
    # 声骸自动强化：流程是 ok-ww 的，判定条件换成 MyTools 工具页上那一套
    "声骸自动强化": "MyToolsEnhanceEchoTask",
}

#: 工具页点「启动」时固定跑的任务
DEFAULT_TASK_KEY = "4C 刷声骸"

_OK_LOGGER_NAME = "ok"


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
            ["okww.task.FarmEchoTask", "FarmEchoTask"],
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

    引擎**只在工具页点「启动」时**拉起（``start_task`` → ``boot``）；
    打开页面本身不会 boot。boot 失败后允许重试，并支持「引擎就绪后自动开任务」。
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
                self._ok = OK(config)
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
            return "找不到任务 %s" % task_key
        if configure is not None:
            try:
                configure(task)
            except Exception as e:  # noqa: BLE001
                return "注入任务配置失败：%s: %s" % (type(e).__name__, e)
        try:
            started = self._ok.headless_app.start_controller.do_start(task)
        except Exception as e:  # noqa: BLE001
            return "%s: %s" % (type(e).__name__, e)
        if not started:
            return ("启动失败（常见原因是没开游戏 / 不是管理员 / 窗口模式）；"
                    "详情见 %LOCALAPPDATA%\\MyTools\\okww\\logs\\ 当天日志")
        with self._lock:
            self._running_task = task_key
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
        with self._lock:
            self._running_task = None
        self._log("■ 已停止任务")
        return None

    def shutdown(self) -> None:
        """程序退出时调用：置退出事件（不调 OK.quit —— 它在 headless 下会碰 Qt）。"""
        with self._lock:
            ok = self._ok
            self._pending_start = None
            self._pending_configure = None
            self._booting = False
        if ok is not None:
            ok.exit_event.set()

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

    def poll_done(self) -> None:
        """工具页的定时器调用：检测一次性任务是否已结束。"""
        with self._lock:
            key, ok = self._running_task, self._ok
        if key and ok is not None:
            task = self.find_task(key)
            # 启动瞬间 running 还是 False：要等它跑过再结束（enabled 被任务自己清掉）
            # 才算完成，避免刚开就误判「已结束」。
            if task is not None and not task.running and not task.enabled:
                with self._lock:
                    self._running_task = None
                self._log("■ 任务结束：%s" % key)

    def _log(self, message: str) -> None:
        with self._lock:
            self._logs.append("[MyTools] " + message)


_host: OkwwHost | None = None
_host_lock = threading.Lock()


def get_host() -> OkwwHost:
    global _host
    with _host_lock:
        if _host is None:
            _host = OkwwHost()
        return _host


def shutdown_host_if_any() -> None:
    """程序退出时调用：宿主已创建过就收尾，没创建过则什么都不做。"""
    with _host_lock:
        host = _host
    if host is not None:
        host.shutdown()
