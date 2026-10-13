# -*- coding: utf-8 -*-
"""★ 回归：找游戏窗口必须靠**类名**，不能只靠标题。

## 这个 bug 是 2026-10-11 实机抓到的

用户一边看 B 站攻略一边开游戏，浏览器标题是::

    【鸣潮】3.5版本玄方地界-无主的梁鸢60个全收集（1个彩蛋）… - Microsoft Edge

里面就有「鸣潮」—— 于是**两个窗口都命中**：:

    Chrome_WidgetWin_1  1536x816   ← 浏览器
    UnrealWindow        1536x864   ← 游戏

而 ``find()`` 取**面积最大**的。那次游戏恰好多 2 像素高才选中它 ——
**那是运气不是正确**：浏览器全屏、或游戏开成窗口化，就会抓到浏览器。

一旦抓错：截图全拍到浏览器、按键也发给了浏览器，
而**界面上一切正常（不报错）** —— 这种错最难查。

## 这批测试怎么测（不依赖真的开着游戏）

``find()`` 要读真实窗口，测不了。所以把**判据**抽出来测：

* 类名优先的逻辑（用假枚举数据）
* 两个常量表本身合理（类名得是 UE 的、标题表没退化）
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance.controller import (  # noqa: E402
    WINDOW_CLASS_NAMES,
    WINDOW_KEYWORDS,
    GameWindow,
)


def classify(windows, keywords=WINDOW_KEYWORDS, class_names=WINDOW_CLASS_NAMES):
    """把 :meth:`GameWindow.find` 的判据抽出来，用假窗口数据跑一遍。

    :param windows: ``[(hwnd, 标题, 类名, 面积), ...]``
    :return: 会选中的 hwnd（没命中返回 ``None``）
    """
    by_class, by_title = [], []
    for hwnd, title, cls, area in windows:
        if any(c.lower() == cls.lower() for c in class_names):
            by_class.append((hwnd, area))
            continue
        if title and any(k.lower() in title.lower() for k in keywords):
            by_title.append((hwnd, area))
    found = by_class or by_title
    if not found:
        return None
    return max(found, key=lambda t: t[1])[0]


class TestWindowClassConstants(unittest.TestCase):
    def test_class_names_has_unreal(self):
        """鸣潮是 UE 游戏 → 类名固定 ``UnrealWindow``。"""
        self.assertIn("UnrealWindow", WINDOW_CLASS_NAMES)

    def test_game_window_takes_class_names(self):
        w = GameWindow()
        self.assertEqual(w.class_names, WINDOW_CLASS_NAMES)
        self.assertEqual(w.keywords, WINDOW_KEYWORDS)

    def test_keywords_still_there_as_fallback(self):
        """标题判据**保留**当兜底（类名取不到时还要能用）。"""
        self.assertTrue(WINDOW_KEYWORDS)


class TestFindPrefersGameWindow(unittest.TestCase):
    """★ 类名命中优先 —— 这是修掉那个 bug 的核心。"""

    def test_browser_bigger_still_loses(self):
        """★★★ 关键用例：浏览器**更大**也必须选游戏。

        修之前是"取面积最大" → 浏览器全屏时就会抓错。
        """
        windows = [
            (1, "【鸣潮】3.5版本…全收集 - Microsoft Edge",
             "Chrome_WidgetWin_1", 1920 * 1080),      #: 浏览器，更大
            (2, "鸣潮", "UnrealWindow", 1280 * 720),   #: 游戏，更小
        ]
        self.assertEqual(classify(windows), 2,
                         "浏览器更大时抓错了 —— 那个 bug 又回来了")

    def test_game_bigger_still_wins(self):
        windows = [
            (1, "【鸣潮】攻略 - Edge", "Chrome_WidgetWin_1", 800 * 600),
            (2, "鸣潮", "UnrealWindow", 1920 * 1080),
        ]
        self.assertEqual(classify(windows), 2)

    def test_only_browser_falls_back_to_title(self):
        """游戏没开、只有浏览器 → 退回标题匹配（保持旧行为）。

        ⚠ 这时确实会"误报游戏在跑"，但那比"永远找不到"好：
        真正抓图时没有 ``UnrealWindow`` 会失败并报错，用户能看到。
        """
        windows = [(1, "【鸣潮】攻略 - Edge", "Chrome_WidgetWin_1", 100)]
        self.assertEqual(classify(windows), 1)

    def test_two_game_windows_pick_biggest(self):
        """多个游戏窗口（比如双开）→ 取面积最大的。"""
        windows = [
            (1, "鸣潮", "UnrealWindow", 800 * 600),
            (2, "鸣潮", "UnrealWindow", 1920 * 1080),
        ]
        self.assertEqual(classify(windows), 2)

    def test_no_match_returns_none(self):
        windows = [(1, "记事本", "Notepad", 100),
                   (2, "Chrome", "Chrome_WidgetWin_1", 200)]
        self.assertIsNone(classify(windows))

    def test_empty_title_game_still_found_by_class(self):
        """★ 游戏标题是空的时候也要能找到（靠类名）。

        实测游戏标题是 ``"鸣潮  "``（带尾空格）；
        某些情况下可能还没设标题 —— 那时标题判据完全失效，
        只有类名能救。
        """
        windows = [(1, "", "UnrealWindow", 1920 * 1080),
                   (2, "【鸣潮】攻略 - Edge", "Chrome_WidgetWin_1", 1920 * 1080)]
        self.assertEqual(classify(windows), 1, "标题为空时该靠类名找到游戏")

    def test_class_match_is_case_insensitive(self):
        windows = [(1, "鸣潮", "unrealwindow", 100)]
        self.assertEqual(classify(windows), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
