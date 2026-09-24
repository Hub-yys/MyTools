"""路径解析：开发态和打包后各走各的根目录。

**为什么要分开**：打成安装包之后，"程序文件"和"用户数据"不能再混在一个目录里 ——
装到 ``Program Files`` 时程序目录是**只读**的，往里面写配置会直接失败；
而且重装 / 升级会把用户的配置一起覆盖掉。

所以分两类：

* **只读资源**（跟着程序走，纯读）：``assets/``（头像、声骸图、图标）和
  ``src/core/data/``（图鉴 / 掉落池 JSON，**打包时随程序分发、首次运行拷一份到用户数据目录**）；
* **可写用户数据**：``data/loadouts.json``、``tasks.json``、``ui_state.json``、
  ``data/probe/``（探测产物），以及会被「资源库更新」改写的图鉴 JSON。

落点：

============  ==========================  ==========================================
             开发态                       打包后
============  ==========================  ==========================================
只读资源      ``<项目根>/…``              PyInstaller 解包目录（``sys._MEIPASS``）
用户数据      ``<项目根>/data``、         ``%LOCALAPPDATA%\\WutheringWavesTools\\…``
              ``<项目根>/src/core/data``
============  ==========================  ==========================================

**开发态行为与打包前完全一致**（关键：别让"为了打包"的改动影响日常开发）。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from ..app_config import APP_NAME

logger = logging.getLogger(__name__)

#: 用户数据目录名（打包后落在 %LOCALAPPDATA%\<这个名字>）。
#: **从 app_config 导入，不在这里再写一份** —— 名字有两份真源，
#: 迟早会出现"程序以为自己叫什么"和"数据实际落在哪"对不上。
#: 换成新名字之前用过的目录名列在下面：首次以新名字启动时整树继承过来。
LEGACY_APP_NAMES: tuple[str, ...] = ("MyTools",)


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
    打包后 = ``%LOCALAPPDATA%\\WutheringWavesTools`` —— 与安装位置无关，装到 Program Files
    也能写，重装 / 升级也不会覆盖用户配置。
    """
    if not is_frozen():
        return _project_root() / "data"
    base = _local_appdata()
    if base:
        return base / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _local_appdata() -> Path | None:
    """``%LOCALAPPDATA%``；取不到退回 ``%APPDATA%``，都没有则 None。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    return Path(base) if base else None


def game_data_dir() -> Path:
    """图鉴 / 掉落池等游戏数据 JSON 的目录。

    开发态 = ``<项目根>/src/core/data``；
    打包后 = ``<用户数据>/game_data`` —— 因为「资源库更新」会**改写**这里的文件，
    所以它算用户数据，不能留在只读的程序目录里。
    """
    if not is_frozen():
        return _project_root() / "src" / "core" / "data"
    return user_data_dir() / "game_data"


def log_file() -> Path:
    """打包后的日志文件（用户数据目录下的 ``<APP_NAME>.log``）。

    打包成 GUI 程序后**没有控制台**（``sys.stderr`` 是 None），日志写不出去，
    出问题时看不到任何线索 —— 所以这时改成写文件。
    """
    return user_data_dir() / f"{APP_NAME.lower()}.log"


def migrate_legacy_user_data(
    base: Path,
    target: Path,
    legacy_names: Sequence[str] = LEGACY_APP_NAMES,
) -> list[str]:
    """把改名前的用户数据目录整树继承到新目录下。

    **只在新目录还不存在时**（= 首次以新名字启动）做一次。之后用户改的东西都在
    新目录里，所以绝不会拿旧文件回过头覆盖新配置。

    用**复制**而不是移动是刻意的：老目录原样留着当兜底 —— 万一副制中途失败，
    用户的数据仍然完整（只是暂时没被读到）。确认新版本一切正常后，老目录可自行删除。

    返回做过的事（给日志用）；不需要迁移时返回空列表。
    """
    if target.exists():
        return []
    for legacy_name in legacy_names:
        legacy = base / legacy_name
        if not legacy.is_dir():
            continue
        shutil.copytree(legacy, target, dirs_exist_ok=True)
        return [f"{legacy.name}/ → {target.name}/"]
    return []


def ensure_user_data() -> list[str]:
    """首次运行把随程序分发的默认数据拷到用户数据目录。

    返回这次拷过去的文件（``"<目录>/<文件名>"``）；没有要拷的就返回空列表。
    **已存在的文件绝不覆盖** —— 用户改过的配置比默认值重要。
    开发态里"种子位置"和"目标位置"本来就是同一个目录，直接跳过、什么都不做。
    """
    copied: list[str] = []

    # 改名后首启动：把老目录整树继承过来。
    # **必须早于下面的种子播种** —— 否则种子会以为"目录是空的"，
    # 往新目录铺一套默认值，把该继承的旧配置挡在外面。
    if is_frozen():
        base = _local_appdata()
        if base:
            for done in migrate_legacy_user_data(base, user_data_dir()):
                logger.info("已继承改名前的用户数据：%s", done)

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
