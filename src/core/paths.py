"""路径解析：开发态和打包后各走各的根目录。

**为什么要分开**：打成安装包之后，"程序文件"和"用户数据"不能再混在一个目录里 ——
装到 ``Program Files`` 时程序目录是**只读**的，往里面写配置会直接失败；
而且重装 / 升级会把用户的配置一起覆盖掉。

所以分两类：

* **只读资源**（跟着程序走，纯读）：``assets/``（头像、声骸图、图标）和
  ``src/core/data/``（图鉴 / 掉落池 JSON，**打包时随程序分发、首次运行拷一份到用户数据目录**）；
* **可写用户数据**：``data/loadouts.json``、``tasks.json``、``ui_state.json``、
  ``data/probe/``（探测产物），以及会被「鸣潮资源库更新」改写的图鉴 JSON。

落点：

============  ==========================  ==========================================
             开发态                       打包后
============  ==========================  ==========================================
只读资源      ``<项目根>/…``              PyInstaller 解包目录（``sys._MEIPASS``）
用户数据      ``<项目根>/data``、         ``%LOCALAPPDATA%\\MyTools\\…``
              ``<项目根>/src/core/data``
============  ==========================  ==========================================

**开发态行为与打包前完全一致**（关键：别让"为了打包"的改动影响日常开发）。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: 用户数据目录名（打包后落在 %LOCALAPPDATA%\<这个名字>）
APP_NAME = "MyTools"


def is_frozen() -> bool:
    """当前是不是打包后的可执行文件在跑。"""
    return bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    """开发态的项目根（本文件位于 ``src/core/``，往上两级）。"""
    return Path(__file__).resolve().parents[2]


def resource_dir(*parts: str) -> Path:
    """只读资源目录。

    打包后 = PyInstaller 的解包目录（onedir 布局下就是 exe 同级的 ``_internal``）；
    开发态 = 项目根。两边写法一样，所以调用处不用区分。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    root = Path(meipass) if meipass else _project_root()
    return root.joinpath(*parts)


def user_data_dir() -> Path:
    """可写的用户数据根目录。

    开发态 = ``<项目根>/data``（和以前一样）；
    打包后 = ``%LOCALAPPDATA%\\MyTools`` —— 与安装位置无关，装到 Program Files
    也能写，重装 / 升级也不会覆盖用户配置。
    """
    if not is_frozen():
        return _project_root() / "data"
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def game_data_dir() -> Path:
    """图鉴 / 掉落池等游戏数据 JSON 的目录。

    开发态 = ``<项目根>/src/core/data``；
    打包后 = ``<用户数据>/game_data`` —— 因为「鸣潮资源库更新」会**改写**这里的文件，
    所以它算用户数据，不能留在只读的程序目录里。
    """
    if not is_frozen():
        return _project_root() / "src" / "core" / "data"
    return user_data_dir() / "game_data"


def log_file() -> Path:
    """打包后的日志文件（用户数据目录下的 ``mytools.log``）。

    打包成 GUI 程序后**没有控制台**（``sys.stderr`` 是 None），日志写不出去，
    出问题时看不到任何线索 —— 所以这时改成写文件。
    """
    return user_data_dir() / "mytools.log"


def ensure_user_data() -> list[str]:
    """首次运行把随程序分发的默认数据拷到用户数据目录。

    返回这次拷过去的文件（``"<目录>/<文件名>"``）；没有要拷的就返回空列表。
    **已存在的文件绝不覆盖** —— 用户改过的配置比默认值重要。
    开发态里"种子位置"和"目标位置"本来就是同一个目录，直接跳过、什么都不做。
    """
    copied: list[str] = []
    seeds = (
        (("src", "core", "data"), game_data_dir()),
        (("data",), user_data_dir()),
    )
    for seed_parts, target in seeds:
        target.mkdir(parents=True, exist_ok=True)
        source = resource_dir(*seed_parts)
        if not source.is_dir():
            continue
        if source.resolve() == target.resolve():
            continue                      # 开发态：种子就在目标位置
        for item in sorted(source.glob("*.json")):
            dest = target / item.name
            if dest.exists():
                continue
            shutil.copy2(item, dest)
            copied.append(f"{target.name}/{item.name}")
    return copied
