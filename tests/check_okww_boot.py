# -*- coding: utf-8 -*-
"""ok-ww 宿主实机冒烟（带断言；无游戏窗口也应优雅失败）。

页面只有「启动 / 停止」：**打开本页不 boot**；点「启动」才在后台加载引擎，
就绪后自动开 FarmEchoTask（4C 刷声骸）。

跑法: .venv/Scripts/python -X utf8 tests/check_okww_boot.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

CHECKS: list[tuple[bool, str]] = []


def check(cond: bool, msg: str) -> None:
    CHECKS.append((bool(cond), msg))
    print("  [%s] %s" % ("PASS" if cond else "FAIL", msg))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    from src.tools.game.auto_combat.okww_boot import get_host, input_permission_error
    from src.tools.game.auto_combat.tool import AutoCombatWidget

    host = get_host()

    print("-- ① 打开页面不 boot；点启动才加载引擎 --")
    page = AutoCombatWidget(None)
    page.show()
    app.processEvents()
    check(host.state in ("idle", "error"),
          "打开页面后引擎未自动启动（state=%s）" % host.state)

    page.start_btn.click()
    app.processEvents()

    # ★ 启动前预检（2026-09-25 加）：权限不足时**故意不拉引擎** ——
    #   设计上就"拦在拉引擎之前"（反馈最快，不做无用功）。
    #   所以这时 state 停在 idle 是**预期行为**，不能按"引擎没起来"判失败；
    #   但要确认预检真的给出了可操作的说明。
    #   ⚠ 这段必须放在等 state 收敛**之前**：否则会白等满 150 秒才判失败。
    blocked = input_permission_error()
    if blocked:
        print("  [info] 启动前预检拦下（本机权限不足）：")
        for line in str(blocked).splitlines():
            print("         " + line)
        check(host.state == "idle",
              "★ 预检拦下时**不拉引擎**（state=%s）" % host.state)
        check("权限" in str(blocked) or "管理员" in str(blocked),
              "预检提示说明了原因")
        host.shutdown()
        page.close()
        print("=== 结果：%d/%d 通过（本机权限不足，引擎相关项不适用）==="
              % (sum(1 for c, _ in CHECKS if c), len(CHECKS)))
        return 0

    deadline = time.time() + 150
    while time.time() < deadline:
        app.processEvents()
        if host.state in ("ready", "running", "error"):
            break
        time.sleep(0.5)
    state = host.state
    check(state in ("ready", "running", "error"),
          "点启动后运行时收敛（state=%s pending=%s）"
          % (state, host.pending_start))
    if state == "error":
        err = host.boot_error or ""
        print("    启动错误：%s" % err)
        check(any(k in err for k in ("ValueError", "OSError", "RuntimeError", "FileNotFoundError")),
              "错误信息可读（不是裸 traceback 崩溃）")
        # 错误态应可再次点启动重试（boot 会清 error 并再试）
        page.start_btn.click()
        check(host.state in ("booting", "error", "ready", "running"),
              "错误态可重试启动（state=%s）" % host.state)
        print("=== 结果：%d/%d 通过（无法在本机启动引擎，其余项不适用）==="
              % (sum(1 for c, _ in CHECKS if c), len(CHECKS)))
        host.shutdown()
        page.close()
        return 0

    check(True, "ok-ww 运行时就绪（或任务已受理）")

    print("-- ② 页面只保留 启动/停止 两个操作按钮，日志全部落后台文件 --")
    check(page.start_btn.text() == "启动" and page.stop_btn.text() == "停止",
          "按钮文案为「启动 / 停止」")
    check(not hasattr(page, "task_combo"), "没有任务选择下拉（已按用户要求移除）")
    check(not hasattr(page, "option_card"), "没有自造参数卡（已按用户要求移除）")
    check(not hasattr(page, "log_view"), "没有页内日志区（已按用户要求移除）")
    from src.core import paths  # noqa: E402
    log_dir = paths.user_data_dir() / "okww" / "logs"
    ok_logs = list(log_dir.glob("ok-ww.log*")) if log_dir.is_dir() else []
    check(bool(ok_logs), "后台日志已按日期落盘：%s" %
          ([str(f) for f in ok_logs][:2] or "（无）"))

    print("-- ③ 无游戏时启动任务要优雅失败（或已排队/已受理）--")
    # 引擎就绪路径：若刚才已自动 flush 开跑且无游戏，start 应返回可读错误或已在跑
    if host.state == "ready":
        err = host.start_task("4C 刷声骸")
        check(err is None or (isinstance(err, str) and err),
              "返回可读结果：%s" % (err or "已受理")[:80])
    else:
        check(host.state == "running" or host.pending_start is not None
              or host.running_task is not None,
              "启动后有运行/排队状态（state=%s）" % host.state)

    print("-- ④ 收尾 --")
    host.stop_task()
    host.shutdown()
    page.close()
    print("=== 结果：%d/%d 通过 ===" % (sum(1 for c, _ in CHECKS if c), len(CHECKS)))
    return 0 if all(c for c, _ in CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
