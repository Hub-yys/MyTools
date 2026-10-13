# -*- coding: utf-8 -*-
"""端到端：**真的上传一个视频** → 建库 → 库里能查到它。

## 这个脚本验什么

前面的单测都是拆开测的（catalog 测命名、upload 测界面、library 测存读）。
但用户做的是一整条动作::

    上传视频 → 等建库 → 看列表里出现了它 → 以后能跑它

这里就用**真视频**把这条链走一遍，且**不注入任何假数据** ——
走的是界面真正会走的那条路（``on_video_chosen`` → ``BuildThread``）。

⚠ 用一段**短视频**跑（可指定），因为建库是重活（27 分钟视频要 77 秒）。
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".")
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication          # noqa: E402

from src.core import paths                          # noqa: E402
from src.tools import discover_tools                # noqa: E402

discover_tools()
app = QApplication.instance() or QApplication([])

VIDEO = sys.argv[1] if len(sys.argv) > 1 else r"D:\DeepSeek Work\_vid\head.mp4"

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


if not os.path.isfile(VIDEO):
    print(f"没有测试视频 {VIDEO} —— 跳过")
    raise SystemExit(0)

#: ★ 把"用户数据目录"指到临时目录 —— 项目约定：测试**绝不碰真实配置**，
#: 也不该往用户的库里塞东西（这条链会真的建一个库出来）。
import tempfile                                      # noqa: E402
from pathlib import Path                             # noqa: E402

_tmp = tempfile.TemporaryDirectory()
_real_user_dir = paths.user_data_dir
paths.user_data_dir = lambda: Path(_tmp.name)
print(f"（用临时用户数据目录：{_tmp.name}）")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl   # noqa: E402
from PySide6.QtGui import QDropEvent                     # noqa: E402

from src.core.explore_gap import list_entries           # noqa: E402
from src.tools.game.explore_gap.tool import ExploreGapPanel  # noqa: E402

panel = ExploreGapPanel()
print("=" * 72)
print("① 模拟用户**拖入**视频")
print("=" * 72)
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(VIDEO)])
event = QDropEvent(QPoint(10, 10), Qt.MoveAction, mime,
                   Qt.LeftButton, Qt.NoModifier)
panel.drop_zone.dropEvent(event)
app.processEvents()
print(f"  拖入 {os.path.basename(VIDEO)}")
check(panel.video_edit.text() != "", "路径回填到输入框了")
check(panel.build_button.isEnabled(), "「开始建库」点亮了")
check("已选" in panel.build_status.text(), "状态行提示已选")

print()
print("=" * 72)
print("② 点「开始建库」（后台线程，真跑）")
print("=" * 72)
before = len(list_entries(paths.user_data_dir()))
panel.start_build()
waited = 0.0
while waited < 600:
    app.processEvents()
    if panel._thread is not None and not panel._thread.isRunning():
        break
    time.sleep(0.1)
    waited += 0.1
app.processEvents()
print(f"  等待 {waited:.0f} 秒")
print(f"  状态行：{panel.build_status.text()}")
check("建好" in panel.build_status.text(), "建库成功")

print()
print("=" * 72)
print("③ 列表里出现了它，而且能跑")
print("=" * 72)
entries = list_entries(paths.user_data_dir())
after = len(entries)
print(f"  库数量 {before} → {after}")
for e in entries:
    print(f"    · {e.name}  —— {e.status_text()}")
check(after >= 1, "列表里有库")
target = next((e for e in entries if e.video == os.path.normpath(VIDEO)),
              None)
check(target is not None, "能按视频路径找到它")
if target is not None:
    check(target.runnable, "标成「能跑」（库在 且 源视频在）")
    check(target.frames > 0, f"参考帧数 > 0（实测 {target.frames}）")

print()
print("=" * 72)
print("④ 面板列表里画出来了")
print("=" * 72)
from src.tools.game.explore_gap.tool import VideoRow    # noqa: E402

panel.refresh_list()
app.processEvents()
rows = panel._list_host.findChildren(VideoRow)
print(f"  列表行数：{len(rows)}")
check(len(rows) == after, f"行数（{len(rows)}）与库数（{after}）一致")

panel._shutdown_thread()
panel.close()
paths.user_data_dir = _real_user_dir
_tmp.cleanup()

print()
print("=" * 72)
if FAILURES:
    print(f"结论：**{len(FAILURES)} 项不通过**")
    for f in FAILURES:
        print("  ✗", f)
    raise SystemExit(1)
print("结论：上传 → 建库 → 列表 → 能跑，整条链通过")
