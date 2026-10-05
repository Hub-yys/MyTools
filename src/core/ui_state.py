"""界面状态的本地持久化（侧栏顺序这类小东西）。

存在 ``data/ui_state.json``，和配置数据同一层目录。读写都容错 ——
文件没了 / 坏了就当没存过，绝不让它影响启动。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths

#: 用户数据目录下的 ui_state.json（见 core/paths.py）
DEFAULT_PATH = paths.user_data_dir() / "ui_state.json"


class UiState:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self._data: dict = {}
        self.load()

    # ------------------------------------------------------------ 读写
    def load(self) -> None:
        self._data = {}
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self._data = raw

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------ 存取
    def get_list(self, key: str) -> list[str]:
        """取一个字符串列表；类型不对就返回空列表。"""
        value = self._data.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def set_list(self, key: str, values: list[str]) -> None:
        self._data[key] = [str(v) for v in values]
        self.save()

    #: ★ 通用取值 —— 「检查更新」的"启动时自动检查"开关要用
    #: （原来只有 get_list/set_list，存个 bool 都不行）
    def get(self, key: str, default=None):
        """取任意值；没有就返回 ``default``。"""
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        """存任意值（bool / str / 数字都行）并落盘。"""
        self._data[key] = value
        self.save()
