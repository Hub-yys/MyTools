"""从游戏日志里读抽卡链接：解密 + 提取 + 容错。

    python tests/test_gacha_link.py

不打网络、不碰真实游戏目录 —— 全用临时文件构造。

★ 这里钉住两个**实测踩过**的坑：

1. **必须整块解密，不能逐行** —— ``Client.log`` 里记录不保证一行一条，
   按行解密会**一条都匹配不到**（实测 42663 行全落空，而整块解开立刻就找到了）。
2. **提取出的 URL 要补回 ``https://``** —— 匹配点在 ``"url":"`` 之后，
   不补的话得到 ``aki-gm-resources...`` 开头的残缺串。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import gacha_link  # noqa: E402

#: 一条形状正确的抽卡链接（真实结构）
SAMPLE = (
    "https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?"
    "svr_id=SVR123&player_id=PLAYER456&lang=zh-Hans&gacha_id=100084"
    "&gacha_type=1&svr_area=cn&record_id=REC789&resources_id=POOL000"
    "&platform=PC"
)


def _encrypt_byte(plain: int) -> int:
    """找一个密文字节 ``c``，使 :func:`gacha_link.decrypt_log_line` 把它还原成 ``plain``。

    ## 为什么需要这个"反函数"

    解密规则是 ``out = (c & 1) ? c ^ 165 : c ^ 239`` —— 按**密文自身**的最低
    位选异或值。它**不是自逆的**（165 / 239 都是奇数，异或会翻转最低位），
    所以不能拿同一个函数去"造数据"。

    反解：要 ``decrypt(c) == p``，则 ``c`` 必须满足
    「``c`` 是奇数且 ``c ^ 165 == p``」或「``c`` 是偶数且 ``c ^ 239 == p``」，
    即候选 ``p ^ 165`` / ``p ^ 239``，取其中能让等式成立的那个。

    ⚠ **不要凭推理写这段** —— 我推错过两次。这里直接**暴力验一遍**
    （见 ``tests`` 里的 ``test_inverse_covers_all_bytes``：
    256 个字节逐个验证 ``decrypt(encrypt(p)) == p``，实测全通过）。
    """
    for candidate in (plain ^ 165, plain ^ 239):
        if gacha_link.decrypt_log_line(bytes([0, 0, 0, candidate]))[3] == plain:
            return candidate
    raise AssertionError(f"{plain:#04x} 没有合法密文（不该发生）")


def obfuscate(data: bytes) -> bytes:
    """把明文**混淆**成日志里的样子（解密的反函数）。

    前 3 字节原样（日志头部不参与混淆），其余逐字节反解。
    """
    out = bytearray(data[:3])
    for byte in data[3:]:
        out.append(_encrypt_byte(byte))
    return bytes(out)


class TestDecryptRoundTrip(unittest.TestCase):
    def test_inverse_covers_all_bytes(self):
        """★ 256 个字节逐个验证 ``decrypt(obfuscate(p)) == p``。

        ⚠ 这条是**防我自己推错**的：加密/解密这对函数不可自逆，
        我推理错过两次，所以改成暴力穷举验证（推不如验）。
        """
        for value in range(256):
            with self.subTest(value=value):
                raw = bytes([0x00, 0x00, 0x00, value])
                self.assertEqual(
                    gacha_link.decrypt_log_line(obfuscate(raw)), raw,
                    f"字节 {value:#04x} 往返失败")

    def test_first_three_bytes_untouched(self):
        """前 3 字节原样 —— 日志头部不参与混淆。"""
        raw = b"ABCdefghij"
        self.assertEqual(gacha_link.decrypt_log_line(obfuscate(raw)), raw)
        # 第 4 个字节确实被混淆过（证明规则真的在起作用）
        self.assertNotEqual(obfuscate(raw)[3:], raw[3:])

    def test_handles_chinese(self):
        raw = "声骸抽卡记录".encode("utf-8")
        self.assertEqual(gacha_link.decrypt_log_line(obfuscate(raw)), raw)


class TestExtractUrl(unittest.TestCase):
    def test_extracts_and_restores_scheme(self):
        """★ 提取出来的 URL 必须带 ``https://``。"""
        text = 'blah "url":"' + SAMPLE + '" blah'
        url = gacha_link.extract_url(text)
        self.assertEqual(url, SAMPLE)
        self.assertTrue(url.startswith("https://"))

    def test_returns_none_without_url(self):
        self.assertIsNone(gacha_link.extract_url("nothing here"))
        self.assertIsNone(gacha_link.extract_url(""))

    def test_rejects_url_missing_key_params(self):
        """缺关键参数的链接不认（可能是别的页面的 URL）。"""
        text = '"url":"https://x.com/a?foo=1&platform=PC"'
        self.assertIsNone(gacha_link.extract_url(text))

    def test_takes_the_last_one(self):
        """★ 取**最后一个** —— 日志追加写，最新的在末尾。

        旧的链接更容易过期（接口回 code=-1），所以必须拿最新的。
        """
        old = SAMPLE.replace("PLAYER456", "OLDPLAYER")
        new = SAMPLE.replace("PLAYER456", "NEWPLAYER")
        text = f'"url":"{old}"\n中间一堆别的\n"url":"{new}"'
        self.assertIn("NEWPLAYER", gacha_link.extract_url(text))


class TestScanLog(unittest.TestCase):
    def _write_log(self, payload: bytes) -> pathlib.Path:
        tmp = pathlib.Path(tempfile.mkdtemp()) / "Client.log"
        tmp.write_bytes(payload)
        return tmp

    def test_finds_url_in_single_line(self):
        log = self._write_log(obfuscate(
            f'some log\n"url":"{SAMPLE}"\nmore log\n'.encode("utf-8")))
        self.assertEqual(gacha_link.scan_log(log), SAMPLE)

    def test_finds_url_when_not_line_aligned(self):
        """★ 关键回归：链接**不在行首/前后有别的内容**时也要找得到。

        这正是逐行解密会失败的场景 —— 记录不保证一行一条。
        这里模拟真实日志的样子：``"url":"<链接>"`` 夹在别的内容中间。
        """
        body = ('some earlier log line\n'
                '[Info] payload: {"url":"' + SAMPLE + '"} | trailing\n'
                'another line\n').encode("utf-8")
        log = self._write_log(obfuscate(body))
        self.assertEqual(gacha_link.scan_log(log), SAMPLE)

    def test_finds_url_without_any_newlines(self):
        """整个文件**没有换行**时也要找得到（逐行方案会直接失效）。"""
        body = ('prefix {"url":"' + SAMPLE + '"} suffix').encode("utf-8")
        log = self._write_log(obfuscate(body))
        self.assertEqual(gacha_link.scan_log(log), SAMPLE)

    def test_no_url_returns_none(self):
        log = self._write_log(obfuscate(b"nothing interesting here\n"))
        self.assertIsNone(gacha_link.scan_log(log))

    def test_missing_file_raises_grab_error(self):
        missing = pathlib.Path(tempfile.mkdtemp()) / "nope.log"
        with self.assertRaises(gacha_link.GrabError):
            gacha_link.scan_log(missing)

    def test_binary_garbage_does_not_crash(self):
        """日志是二进制混杂的，解出来不是合法 UTF-8 也不能炸。"""
        log = self._write_log(obfuscate(bytes(range(256)) * 40))
        self.assertIsNone(gacha_link.scan_log(log))


class TestRememberedDir(unittest.TestCase):
    """记住游戏目录：第一次找到后写进用户数据目录，下次直接读。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = unittest.mock.patch.object(
            gacha_link, "_config_path",
            return_value=pathlib.Path(self._tmp.name) / "cfg.json")
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_remember_and_recall(self):
        game_dir = pathlib.Path(self._tmp.name) / "game"
        (game_dir / gacha_link.LOG_RELATIVE).parent.mkdir(parents=True)
        (game_dir / gacha_link.LOG_RELATIVE).write_text("x", encoding="utf-8")

        self.assertIsNone(gacha_link.remembered_dir(), "一开始不该有记忆")
        gacha_link.remember_dir(game_dir)
        self.assertEqual(gacha_link.remembered_dir(), game_dir)

    def test_stale_memory_is_ignored(self):
        """★ 记住的目录如果日志没了（游戏被卸载/移动），要当作没记住。

        不然会一直指着一个不存在的路径报错，而不去重新找。
        """
        game_dir = pathlib.Path(self._tmp.name) / "gone"
        game_dir.mkdir()
        gacha_link.remember_dir(game_dir)
        self.assertIsNone(gacha_link.remembered_dir())

    def test_corrupt_config_is_ignored(self):
        path = pathlib.Path(self._tmp.name) / "cfg.json"
        path.write_text("{ 不是 json", encoding="utf-8")
        self.assertIsNone(gacha_link.remembered_dir())

    def test_missing_config_is_none(self):
        self.assertIsNone(gacha_link.remembered_dir())


class TestGrabLink(unittest.TestCase):
    """``grab_link()`` 的整体行为（日志用临时文件替身）。"""

    def test_success(self):
        tmp = pathlib.Path(tempfile.mkdtemp()) / "Client.log"
        tmp.write_bytes(obfuscate(f'"url":"{SAMPLE}"'.encode("utf-8")))
        with unittest.mock.patch.object(gacha_link, "find_log",
                                        return_value=tmp):
            self.assertEqual(gacha_link.grab_link(), SAMPLE)

    def test_no_url_gives_actionable_message(self):
        """★ 日志里没有链接时，提示要告诉用户**具体怎么做**。

        用户最容易卡在这一步（忘了先在游戏里打开唤取记录页）。
        """
        tmp = pathlib.Path(tempfile.mkdtemp()) / "Client.log"
        tmp.write_bytes(obfuscate(b"no url here"))
        with unittest.mock.patch.object(gacha_link, "find_log",
                                        return_value=tmp):
            with self.assertRaises(gacha_link.GrabError) as ctx:
                gacha_link.grab_link()
        message = str(ctx.exception)
        self.assertIn("唤取记录", message)

    def test_find_log_failure_gives_manual_fallback(self):
        """找不到游戏目录时，要提示可以**手动取链接**（不能只说失败）。"""
        with unittest.mock.patch.object(gacha_link, "remembered_dir",
                                        return_value=None), \
             unittest.mock.patch.object(gacha_link, "_common_candidates",
                                        return_value=[]), \
             unittest.mock.patch.object(gacha_link, "_scan_drives",
                                        return_value=None):
            with self.assertRaises(gacha_link.GrabError) as ctx:
                gacha_link.find_log()
        self.assertIn("手动", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
