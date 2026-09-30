"""缺的**图标文件**自动补齐（从库里存的 URL 下载）。

## 为什么单独一个模块

「资源库更新」以前**只写图标 URL，从不下载图片** —— 下载一直是
``tools/fetch_wuwa_assets.py`` 那个手动脚本干的。

于是用户 2026-09-30 遇到："资源库已经更新了，这图片为什么没自动补上？"
数据（名单 / URL）更新了，但**图还是不会自己出现** —— 两个环节脱节了。

现在把"按 URL 下载到 assets/game/"这段抽到 core，
**更新和数据下载脚本共用同一份**（别再各写一份）。

## 只补缺的

``ensure_assets()`` **只下载磁盘上还没有的文件**，已有的绝不覆盖 ——
用户可能自己换过图（README 里就是这么教的），覆盖会毁掉他的替换。

## 素材版权

图标是库洛的美术素材。这里只是把**公开图床上的图拉到用户本机**供本地
工具显示用（和手动跑脚本性质一样）。``assets/game/`` 在 ``.gitignore`` 里，
**不进仓库、不分发**。
"""

from __future__ import annotations

import logging
import ssl
import time
import urllib.request
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 下载间隔（秒）—— 别把图床惹毛了
DELAY = 0.15
#: 图床挑 Referer；库街区要自己的域名
KUROBBS_REFERER = "https://www.kurobbs.com/"
#: PNG 文件头
_PNG_MAGIC = b"\x89PNG"
#: 单张图的上限（正常 40~300KB，给足余量防跑飞）
MAX_BYTES = 8 * 1024 * 1024


class AssetError(Exception):
    """下载失败（消息给日志/调用方看）。"""


def assets_root() -> Path:
    """素材根目录 ``assets/game/``（只读资源，见 core/paths.py）。"""
    return paths.resource_dir("assets", "game")


def download_icon(url: str, relative: str, *, timeout: int = 45) -> int:
    """把 ``url`` 下载到 ``assets/game/<relative>``。返回字节数。

    ⚠ 只接受 **PNG**（校验文件头）—— 图床偶尔会回 HTML 错误页，
    直接落盘会变成一个打不开的"图片"，界面上表现为空白，很难查。
    """
    target = assets_root() / relative
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": KUROBBS_REFERER})
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=context) as response:
            blob = response.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - 网络问题变成一句话
        raise AssetError(f"下载失败：{exc}") from exc

    if len(blob) > MAX_BYTES:
        raise AssetError(f"文件太大（>{MAX_BYTES // 1024 // 1024}MB），像是下错了")
    if not blob.startswith(_PNG_MAGIC):
        raise AssetError(f"返回的不是 PNG（前 8 字节 {blob[:8]!r}）")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return len(blob)


def ensure_assets(wanted: dict[str, str], *, log=lambda _m: None,
                  should_stop=lambda: False) -> tuple[int, list[str]]:
    """按 ``{项目内相对路径: 图片 URL}`` 把**缺的**图补下来。

    返回 ``(下载张数, 失败说明列表)``。

    * **已有的跳过**（用户可能自己换过图，不覆盖）；
    * 没有 URL 的跳过（不报错 —— 可能只是那一条没收录）；
    * 单张失败**不影响其余**（记一句继续下）。

    ⚠ 下载是**串行 + 间隔**的：一次可能补上百张，并发会把图床惹毛。
    调用方若要放在界面里跑，请自己丢到后台线程（这里的 ``should_stop``
    供中途取消用）。
    """
    done = 0
    failed: list[str] = []
    items = [(rel, url) for rel, url in wanted.items() if url]
    if not items:
        return 0, failed

    root = assets_root()
    for index, (relative, url) in enumerate(items, 1):
        if should_stop():
            log("已取消")
            break
        if (root / relative).exists():
            continue          # 已有就不动（可能是用户自己换的图）
        try:
            size = download_icon(url, relative)
            done += 1
            log(f"  ✓ {relative}（{size / 1024:.0f} KB）")
        except AssetError as exc:
            failed.append(f"{relative}：{exc}")
            logger.warning("图标下载失败 %s：%s", relative, exc)
        if index % 10 == 0:
            log(f"  … {index}/{len(items)}")
        time.sleep(DELAY)
    return done, failed
