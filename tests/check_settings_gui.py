"""GUI 验证：
① 声骸工具页的配置会存盘、重开页面会回填；
② 资源库页在数据版本变化后会**就地重建**（不用重启程序）；
③ 顺手出两张截图。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QShowEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from qfluentwidgets import Theme, setTheme  # noqa: E402

SHOTS = ROOT / "tests" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

from src.core import tool_settings  # noqa: E402
from src.core import game_data  # noqa: E402
from src.gui.main_window import MainWindow  # noqa: E402
from src.gui.library_interface import _AvatarTile, WuwaLibraryInterface  # noqa: E402
import src.tools as tool_pkg  # noqa: E402
from src.core.registry import ToolRegistry  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def main() -> int:
    # 设置文件指到临时目录：绝不碰用户真正的配置
    tmp = tempfile.TemporaryDirectory()
    settings_path = Path(tmp.name) / "tool_settings.json"
    tool_settings.settings_file = lambda: settings_path

    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    ToolRegistry.discover(tool_pkg)

    win = MainWindow()
    win.setMicaEffectEnabled(False)
    win.resize(1150, 760)
    win.show()
    app.processEvents()

    echo_tool = ToolRegistry.make("echo_enhance")
    # 用主窗口里**真正挂着的**那个页面（不是另建一个游离控件，否则截不到图）
    page = win._tool_hosts["echo_enhance"].ensure_panel()

    print("--- ① 工具页：默认值 → 改一下 → 存盘（但不回填，每次进入都是默认）---")
    # 联动：核心 = 双爆 2 条 → 有效词条默认就是 2（不是老的固定 3）
    check(page.valid_stepper.value() == 2,
          f"默认有效词条 = 核心条数 2（实际 {page.valid_stepper.value()}）")
    check(page.maxroll_switch.isChecked(), "满值保护默认开")
    check(settings_path.exists() is False or True, "（设置文件此时可能还没写）")

    # ⚠ 顺序要紧：**先**勾可选属性（集合变 3 条、上限才升到 3）**再**设值，
    #   反过来的话 3 会被夹到 2（联动规则见 settings.valid_count_range）
    page._optional_boxes["共鸣效率"].setChecked(True)
    page.valid_stepper.set_value(3)
    page.crit_field.set_value(9.5)
    page.maxroll_switch.setChecked(False)
    page._update_optional_count()
    app.processEvents()

    saved = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    echo_saved = saved.get("echo_enhance", {})
    print(f"  存盘内容：{echo_saved}")
    check(echo_saved.get("min_valid_count") == 3, "有效词条 3 已存盘")
    check("共鸣效率" in echo_saved.get("optional_stats", []), "可选属性已存盘")
    check(echo_saved.get("crit_min") == 9.5, "暴击下限 9.5 已存盘")
    check(echo_saved.get("enable_max_roll_lock") is False, "满值保护关已存盘")

    # ★ 新语义（2026-09-24 用户要求："不要遗留上次的东西，每次进入都是默认配置"）：
    #   页面**不再回填**，但改动照旧存盘 —— 任务流程读的就是存下来那份。
    fresh = echo_tool.create_widget(win)
    check(fresh.valid_stepper.value() == 2,
          f"★ 新页面回到默认有效词条 2（实际 {fresh.valid_stepper.value()}）")
    check(not fresh._optional_boxes["共鸣效率"].isChecked(), "★ 可选项不回填（默认不勾）")
    check(abs(fresh.crit_field.value() - 7.5) < 1e-6,
          f"★ 暴击下限回默认 7.5（实际 {fresh.crit_field.value()}）")
    check(fresh.maxroll_switch.isChecked() is True, "★ 满值保护回默认开")
    check(len(fresh._checked_core()) == 2, f"★ 核心回默认双爆（实际 {fresh._checked_core()}）")
    check(fresh._core_boxes["暴击"].isChecked(), "双爆仍是强制勾选")
    # 盘上仍然是刚才改的那套（任务流程依赖它，不能因为页面不回填就丢）
    still = json.loads(settings_path.read_text(encoding="utf-8"))["echo_enhance"]
    check(still.get("min_valid_count") == 3 and abs(still.get("crit_min", 0) - 9.5) < 1e-6,
          f"底盘上仍是改过的配置（任务流程用）：{still}")

    win.switchTo(win._tool_hosts["echo_enhance"])
    for _ in range(6):
        app.processEvents()
        time.sleep(0.05)
    win.grab().save(str(SHOTS / "echo_tool_settings.png"))
    print("  截图 → echo_tool_settings.png")

    print("--- ② 资源库页：数据版本变化后重建 ---")
    library = win.wuwa_library  # 主窗口里那个资源库页面实例
    before_tiles = len(library.findChildren(_AvatarTile))
    before_version = game_data.DATA_VERSION
    print(f"  当前头像卡 {before_tiles} 张，数据版本 {before_version}")
    check(before_tiles > 0, "资源库页有内容（不是空白）")

    # 换一套很小的临时数据 → 重载 → 页面显示时应自动重建
    tmp_data = Path(tmp.name) / "game_data"
    tmp_data.mkdir()
    (tmp_data / "wuwa_characters.json").write_text(
        json.dumps({"characters": [{"name": "临时角色", "rarity": 5}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_data / "wuwa_echo_sets.json").write_text('{"sets": []}', encoding="utf-8")
    (tmp_data / "wuwa_set_versions.json").write_text('{"versions": {}}', encoding="utf-8")
    (tmp_data / "wuwa_echo_skills.json").write_text('{"echoes": {}}', encoding="utf-8")

    original_root = game_data.DATA_ROOT
    game_data.DATA_ROOT = tmp_data
    try:
        game_data.reload_data()
        library.showEvent(QShowEvent())        # 模拟"页面被显示"
        app.processEvents()
        after_tiles = len(library.findChildren(_AvatarTile))
        after_version = game_data.DATA_VERSION
        print(f"  重建后头像卡 {after_tiles} 张，数据版本 {after_version}")
        check(after_version > before_version, "版本号递增")
        check(after_tiles == 1, f"页面按新数据重建了（{before_tiles} → {after_tiles}）")
    finally:
        game_data.DATA_ROOT = original_root
        game_data.reload_data()
        library.showEvent(QShowEvent())
        app.processEvents()
    restored = len(library.findChildren(_AvatarTile))
    check(restored == before_tiles, f"数据换回来后又重建回 {before_tiles} 张（实际 {restored}）")

    win.switchTo(win.wuwa_library)
    for _ in range(6):
        app.processEvents()
        time.sleep(0.05)
    win.grab().save(str(SHOTS / "library_rebuilt.png"))
    print("  截图 → library_rebuilt.png")

    win.close()
    time.sleep(0.3)
    tmp.cleanup()
    print(f"\n=== 结果：{'全部通过' if not failures else f'{len(failures)} 项失败'} ===")
    for item in failures:
        print(f"  - {item}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
