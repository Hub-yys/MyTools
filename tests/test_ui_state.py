"""界面状态持久化的单元测试（容错部分是最容易写错的地方）。"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.ui_state import UiState  # noqa: E402


class TestUiState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "ui_state.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_gives_empty(self):
        self.assertEqual(UiState(self.path).get_list("nav_order"), [])

    def test_set_and_get_roundtrip(self):
        state = UiState(self.path)
        state.set_list("nav_order", ["HomeInterface", "tool_group"])
        self.assertEqual(
            UiState(self.path).get_list("nav_order"), ["HomeInterface", "tool_group"]
        )

    def test_corrupted_file_gives_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{不是 json", encoding="utf-8")
        self.assertEqual(UiState(self.path).get_list("nav_order"), [])

    def test_wrong_type_gives_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"nav_order": "不是列表"}), encoding="utf-8")
        self.assertEqual(UiState(self.path).get_list("nav_order"), [])

    def test_not_a_dict_gives_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
        self.assertEqual(UiState(self.path).get_list("nav_order"), [])

    def test_missing_key_gives_empty(self):
        self.assertEqual(UiState(self.path).get_list("不存在"), [])

    def test_saved_file_is_readable_json(self):
        state = UiState(self.path)
        state.set_list("nav_order", ["HomeInterface"])
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["nav_order"], ["HomeInterface"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
