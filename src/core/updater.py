# -*- coding: utf-8 -*-
"""自动更新 —— 查 GitHub Releases、下载安装包、启动安装。

## 用户要求（2026-10-05）

    "增加检查更新功能，如果有更新，可以自动更新"

## 怎么拿"有没有新版本"

走 **GitHub Releases API**（仓库是公开的，不用 token）::

    GET https://api.github.com/repos/Hub-yys/MyTools/releases/latest
    → {"tag_name": "v0.6.0",
       "body": "更新说明…",
       "assets": [{"name": "WutheringWavesToolsSetup-0.6.0.exe",
                   "browser_download_url": "...", "size": 12345678}]}

## ⚠ 版本比较**不能用字符串比**

``"0.10.0" < "0.9.0"``（字符串比是 True，但**版本上 0.10 更新**）。
必须**按数字逐段比**（见 :func:`parse_version` / :func:`is_newer`）。

## ⚠ 为什么先下载再让用户点"安装"

不能直接 ``QDesktopServices.openUrl(下载地址)`` 了事 ——
那样用户拿到的是浏览器里的一个 exe，还得自己找、自己点。
**下载到本地 + 校验大小 + 启动它**，用户只点一次。

安装包是 Inno Setup 做的，**双击就装**（它会自己关掉正在运行的旧版——
见 ``installer/mytools.iss`` 的 ``CloseApplications``）。

## 网络失败**不抛异常**

检查更新是个"锦上添花"的功能 —— 断网 / GitHub 抽风 / 限流
都不该让界面炸掉。所有入口都返回结构化的结果，把错误放在里边。
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: 仓库（发 Release 的地方）
REPO = "Hub-yys/MyTools"

#: GitHub API —— 只要"最新那个 release"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

#: 也接受 ``v1.2.3`` / ``1.2.3`` / ``v1.2.3-beta`` 这些写法
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)")

#: 网络超时（秒）—— 检查更新不该让界面卡太久
TIMEOUT = 20


@dataclass
class ReleaseInfo:
    """一次"有没有新版本"的结果。

    :param ok:        这次**检查本身**成没成功（网络通不通）
    :param current:   当前版本（如 ``"0.5.3"``）
    :param latest:    远端最新版本（拿不到就是空）
    :param has_update: 有没有更新（``ok`` 为假时恒为 False）
    :param notes:     更新说明（Release 的 body）
    :param url:       下载地址（安装包 asset）
    :param size:      安装包字节数（拿不到是 0）
    :param error:     失败原因（给界面显示用，成功时是空）
    """

    ok: bool = False
    current: str = ""
    latest: str = ""
    has_update: bool = False
    notes: str = ""
    url: str = ""
    size: int = 0
    error: str = ""

    @property
    def download_name(self) -> str:
        """从 URL 猜出文件名（给保存用）。"""
        if not self.url:
            return ""
        return self.url.rsplit("/", 1)[-1].split("?")[0]


def parse_version(text: str) -> tuple[int, ...]:
    """``"v0.10.2"`` → ``(0, 10, 2)``；解析不了返回 ``()``。

    ⚠ **必须按数字比** —— 字符串比会把 ``0.10.0`` 判成比 ``0.9.0`` 旧。
    """
    m = _VERSION_RE.match(str(text or "").strip())
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """``latest`` 是不是比 ``current`` 新。

    ## ⚠⚠ 为什么不用字符串比较（这条是**真的会被坑**）

    ::

        "0.10.0" < "0.9.0"   # True（字符串）
        (0, 10, 0) > (0, 9, 0)  # True（数字）← 对的

    所以 ``0.10.0`` 发布时，字符串比会认为"没有更新" —— 用户永远收不到。

    段数不一样也能比：``(0, 6)`` vs ``(0, 6, 0)`` —— 短的补 0。
    """
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False                           #: 解析不了 → 不当有更新
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def _ssl_context():
    """默认 SSL 上下文；证书出问题时不至于把整个功能打死。"""
    try:
        return ssl.create_default_context()
    except Exception:                          # noqa: BLE001 - 极老的 Python
        return None


def _get_json(url: str, timeout: int = TIMEOUT) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": f"MyTools/{_current_version()}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout,
                               context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _current_version() -> str:
    """当前版本 —— 从 :mod:`src.app_config` 拿（**唯一真源**）。

    ⚠ 别在这儿再写一份版本号 —— 项目之前就出过
    "安装包 0.3.0 / 界面 v0.1.0 对不上"的事（见 app_config 的注释）。
    """
    try:
        from ..app_config import APP_VERSION

        return str(APP_VERSION)
    except Exception:                          # noqa: BLE001
        return "0.0.0"


def pick_asset(assets: list) -> tuple[str, int]:
    """从 release 的 assets 里挑出**安装包**，返回 ``(下载地址, 字节数)``。

    优先 ``*Setup*.exe``（Inno 安装包），其次任意 ``.exe``。
    找不到返回 ``("", 0)``。
    """
    def _url(a) -> str:
        return str((a or {}).get("browser_download_url") or "")

    def _size(a) -> int:
        try:
            return int((a or {}).get("size") or 0)
        except (TypeError, ValueError):
            return 0

    exes = [a for a in (assets or [])
            if str((a or {}).get("name") or "").lower().endswith(".exe")]
    for a in exes:
        if "setup" in str(a.get("name") or "").lower():
            return _url(a), _size(a)
    if exes:
        return _url(exes[0]), _size(exes[0])
    return "", 0


def check_for_update(current: str = "") -> ReleaseInfo:
    """查有没有新版本。**永不抛异常** —— 失败也返回 :class:`ReleaseInfo`。

    :param current: 当前版本；留空则从 ``app_config`` 取
    """
    cur = str(current or _current_version())
    try:
        data = _get_json(API_LATEST)
    except urllib.error.HTTPError as exc:
        #: 404 = 仓库还没有任何 release（很常见，不是错误）
        if exc.code == 404:
            return ReleaseInfo(ok=True, current=cur,
                               error="")   #: 没有 release = 没有更新
        return ReleaseInfo(current=cur,
                           error=f"GitHub 返回 {exc.code}")
    except urllib.error.URLError as exc:
        return ReleaseInfo(current=cur, error=f"连不上 GitHub：{exc.reason}")
    except Exception as exc:                   # noqa: BLE001 - 兜底不炸界面
        logger.debug("检查更新失败", exc_info=True)
        return ReleaseInfo(current=cur, error=f"检查失败：{exc}")

    tag = str(data.get("tag_name") or "")
    url, size = pick_asset(data.get("assets") or [])
    return ReleaseInfo(
        ok=True,
        current=cur,
        latest=tag,
        has_update=is_newer(tag, cur),
        notes=str(data.get("body") or ""),
        url=url,
        size=size,
    )


def download(url: str, *, dest_dir: Path | str | None = None,
             on_progress=None, timeout: int = 120) -> Path:
    """下载安装包，返回本地路径。

    :param on_progress: ``fn(已下载字节, 总字节)`` —— 界面拿它画进度条；
        总字节未知时第二个参数是 0
    :raises RuntimeError: 下载失败（网络 / 写盘）
    """
    if not url:
        raise RuntimeError("没有下载地址")

    name = url.rsplit("/", 1)[-1].split("?")[0] or "update.exe"
    folder = Path(dest_dir) if dest_dir else Path(tempfile.mkdtemp(
        prefix="mytools_update_"))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name

    req = urllib.request.Request(url, headers={
        "User-Agent": f"MyTools/{_current_version()}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_ssl_context()) as resp:
            total = 0
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            done = 0
            with open(target, "wb") as fp:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        try:
                            on_progress(done, total)
                        except Exception:      # noqa: BLE001 - 回调不该炸下载
                            logger.debug("进度回调出错", exc_info=True)
    except Exception as exc:                   # noqa: BLE001
        raise RuntimeError(f"下载失败：{exc}") from exc

    return target


def launch_installer(path: Path | str) -> None:
    """启动安装包，然后**退出本程序**（让安装器能覆盖文件）。

    ⚠ Windows 上正在运行的 exe 是**锁着**的 —— 不退出的话安装器
    覆盖不了（Inno 会提示"文件正在使用"）。

    用 ``os.startfile``（Windows 特有）而不是 ``subprocess`` ——
    它**不等**子进程、也不继承控制台，正合适。
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"安装包不见了：{p}")

    if sys.platform == "win32":
        os.startfile(str(p))                   # noqa: S606 - 就是要点开它
    else:
        #: 非 Windows（开发机上跑测试用）—— 退化成"用系统打开"
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
