"""工具设置的持久化。

所有工具的设置都存在用户数据目录下的**同一个 JSON** 里，按工具 key 分节：

    <用户数据>/tool_settings.json          # 开发态 = <项目根>/data/tool_settings.json
    {"echo_enhance": {"core_stats": ["暴击", ...], ...}}

## 为什么要落盘

任务流程运行时**没有界面**（用户可能是刚开机就跑任务，根本没打开过工具页），
配置只能从盘上读。而且"任务运行时用了哪套规则"必须和用户在界面上看到的**是同一套**
—— 否则就会出现"它按自己的规则把声骸弃置了"。

## 为什么不塞进 ui_state.json

``ui_state.json`` 只放"侧栏顺序"这类纯界面状态；工具设置是**会改变行为**的东西，
混在一起以后不好迁移，也没法单独备份。

**纯逻辑**：core 层，不依赖 Qt。写盘用"先写临时文件再 replace"，中途崩了不会留半个坏文件。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 用户数据目录下的设置文件名
FILE_NAME = "tool_settings.json"


def settings_file() -> Path:
    """设置文件位置（跟用户数据目录走：开发态在项目里，打包后在 %LOCALAPPDATA%）。"""
    return paths.user_data_dir() / FILE_NAME


def load_all() -> dict:
    """读全部工具的设置。

    文件不存在 / 内容坏掉都返回空 dict —— **绝不让设置文件影响启动**。
    """
    path = settings_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("工具设置读不出来（%s）：%s —— 按默认值处理", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def load(key: str) -> dict:
    """读某个工具的设置；没有 / 类型不对就是空 dict。"""
    value = load_all().get(str(key))
    return value if isinstance(value, dict) else {}


def save(key: str, data: dict) -> None:
    """写某个工具的设置（其它工具的保持不动）。"""
    path = settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        everything = load_all()
        everything[str(key)] = dict(data)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(everything, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    except OSError as exc:
        # 写不下来（磁盘满 / 权限）不该让功能不可用，记一条日志即可
        logger.warning("工具设置写不进去（%s）：%s", path, exc)
