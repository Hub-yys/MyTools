# -*- coding: utf-8 -*-
"""★ 资源库：角色按「实装版本」降序排（2026-10-24 用户要求，第二版）。

## 用户第一次说

> 资源库最新的角色图标为什么没排到前面
> （圈出排在 4 星角色后面的 5 星新角色「莉莉」）

我用了 ``content.updateAt`` —— **错的**。

## 用户第二次（截图指出排序完全错乱）

> 什么情况，这个排序完全有问题，
> 排序按照版本推出的新角色降序排列，
> **注意是新角色，不算复刻的角色**

截图里 `千咲`（V2.8）夹在 V3.5 和 V3.6 之间、
`今汐`/`长离`/`相里要` 这些 V1.x 的老角色跑到了第二三行。

**根因**：``content.updateAt`` 是**词条最后修改时间**，
wiki 批量改数据时会全刷新 → 老角色也"变新"了。

## 正确依据：库街区的「实装版本」标签

* 形如 ``V3.8`` / ``V3.7`` / … / ``V1.0``
* **复刻不改变它** → 天然排除复刻（正是用户强调的）
* 实测 61/61 全部有值
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import (  # noqa: E402
    CHARACTERS,
    CharacterInfo,
    _build_characters,
)

DATA = ROOT / "src" / "core" / "data" / "wuwa_characters.json"


class TestVersionKey(unittest.TestCase):
    """版本号解析。"""

    def _key(self, text: str):
        return CharacterInfo(name="x", avatar="a.png",
                             release_version=text).version_key

    def test_parses_standard(self):
        self.assertEqual(self._key("V3.8"), (3, 8))
        self.assertEqual(self._key("v3.8"), (3, 8))
        self.assertEqual(self._key("3.8"), (3, 8))

    def test_major_only(self):
        self.assertEqual(self._key("V3"), (3, 0))

    def test_empty(self):
        for empty in ("", None):
            with self.subTest(empty=empty):
                self.assertEqual(
                    CharacterInfo(name="x", avatar="a.png",
                                  release_version=empty or "").version_key,
                    (0, 0))

    def test_numeric_not_string_order(self):
        """★★ ``V3.10`` 必须 > ``V3.9``（按字符串排会错）。

        虽然当前游戏还没到 3.10，但下个版本就到了 ——
        现在就钉住，免得到时排序突然坏掉。
        """
        self.assertGreater(self._key("V3.10"), self._key("V3.9"))
        self.assertGreater(self._key("V4.0"), self._key("V3.99"))


class TestCharacterOrdering(unittest.TestCase):
    """``_build_characters`` 的排序规则。"""

    def _names(self, raw_chars):
        return [c.name for c in _build_characters({"characters": raw_chars})]

    def test_newer_version_first(self):
        """★★ 实装版本越新 → 排越前面。"""
        raw = [
            {"name": "老", "rarity": 5, "release_version": "V1.0"},
            {"name": "新", "rarity": 5, "release_version": "V3.8"},
            {"name": "中", "rarity": 5, "release_version": "V2.4"},
        ]
        self.assertEqual(self._names(raw), ["新", "中", "老"])

    def test_no_version_goes_last(self):
        """★ 没有版本信息的（手工补的）排最后。"""
        raw = [
            {"name": "手工", "rarity": 5},
            {"name": "官方", "rarity": 4, "release_version": "V1.0"},
        ]
        self.assertEqual(self._names(raw), ["官方", "手工"])

    def test_rarity_breaks_ties(self):
        raw = [
            {"name": "四星", "rarity": 4, "release_version": "V3.0"},
            {"name": "五星", "rarity": 5, "release_version": "V3.0"},
        ]
        self.assertEqual(self._names(raw), ["五星", "四星"])

    def test_name_breaks_remaining_ties(self):
        """★ 再同 → 按名字，保证顺序稳定。"""
        raw = [
            {"name": "B", "rarity": 5, "release_version": "V3.0"},
            {"name": "A", "rarity": 5, "release_version": "V3.0"},
        ]
        self.assertEqual(self._names(raw), ["A", "B"])

    def test_does_not_use_updateat(self):
        """★★ 排序**不能**依赖 ``released_at``（用户已否掉那个依据）。

        数据里就算有 ``released_at``，也不该影响顺序 ——
        唯一依据是 ``release_version``。
        """
        raw = [
            {"name": "新版", "rarity": 5, "release_version": "V3.8",
             "released_at": 100},          #: 时间很旧
            {"name": "老版", "rarity": 5, "release_version": "V1.0",
             "released_at": 9_999_999},    #: 时间很新
        ]
        self.assertEqual(self._names(raw), ["新版", "老版"],
                         "排序被 released_at 影响了 —— "
                         "那个字段是词条修改时间，不能用")


class TestRealDataFile(unittest.TestCase):
    """真实数据文件的状态。"""

    def test_all_have_release_version(self):
        """★ 61 个角色应全部有 ``release_version``。"""
        data = json.loads(DATA.read_text(encoding="utf-8"))
        chars = data.get("characters") or []
        self.assertGreater(len(chars), 0)
        missing = [c.get("name") for c in chars
                   if not str(c.get("release_version") or "").strip()]
        self.assertEqual(missing, [],
                         f"这些角色没有 release_version，会排到最后：{missing}")

    def test_no_stale_released_at(self):
        """★ 错的那个字段 ``released_at`` 应该已经清掉了。"""
        data = json.loads(DATA.read_text(encoding="utf-8"))
        left = [c.get("name") for c in data.get("characters") or []
                if "released_at" in c]
        self.assertEqual(left, [],
                         f"还在用错字段 released_at：{left[:5]} "
                         f"—— 那是词条修改时间，不是实装版本")

    def test_ordering_is_monotonic(self):
        """★★ 加载后的顺序必须**版本单调递减**。"""
        keys = [(c.name, c.version_key) for c in CHARACTERS]
        for i in range(len(keys) - 1):
            name, key = keys[i]
            nname, nkey = keys[i + 1]
            if key == (0, 0) or nkey == (0, 0):
                continue
            self.assertGreaterEqual(
                key, nkey,
                f"排序错了：{name}({key}) 在 {nname}({nkey}) 前面 —— "
                f"版本应该降序")

    def test_newest_character_is_first(self):
        """★ 最新版本的角色应该在最前面。"""
        newest = max(CHARACTERS, key=lambda c: c.version_key)
        self.assertEqual(CHARACTERS[0].version_key, newest.version_key,
                         f"第一位是 {CHARACTERS[0].name}"
                         f"({CHARACTERS[0].release_version})，"
                         f"但最新的是 {newest.name}"
                         f"({newest.release_version})")

    def test_user_cited_characters_are_in_right_places(self):
        """★★ 用户截图里点出的几个角色，位置要对。

        * ``千咲`` (V2.8) —— 原来夹在 V3.5/V3.6 中间，应该在其后
        * ``今汐`` / ``长离`` (V1.1)、``吟霖``/``忌炎`` (V1.0)
          —— 原来跑到第二三行，应该靠后（V3.x 都在前面）
        """
        order = [c.name for c in CHARACTERS]
        by_name = {c.name: c for c in CHARACTERS}

        qianxiao = by_name.get("千咲")
        if qianxiao:
            behind = [n for n in order if n in ("心", "锁暝", "景燃", "清宵")]
            for n in behind:
                self.assertGreater(
                    order.index("千咲"), order.index(n),
                    f"千咲(V2.8) 不该排在 {n}(V3.6+) 前面")

        for old in ("今汐", "长离"):
            c = by_name.get(old)
            if not c:
                continue
            self.assertLessEqual(
                c.version_key, (2, 0),
                f"{old} 版本是 {c.release_version}，不该是 V2 以上")
            self.assertGreater(
                order.index(old), 20,
                f"{old}({c.release_version}) 在第 {order.index(old) + 1} 位，"
                f"太靠前了 —— V3.x 应该都在它前面")


if __name__ == "__main__":
    unittest.main(verbosity=2)
