"""多连接分段下载 wheel（pip 单连接被限速到 18KB/s，多线程实测能到 ~85KB/s）。

用法（可反复运行，已下好的分片会跳过，天然断点续传）：

    python fetch_wheels.py                 # 下载默认依赖集
    python fetch_wheels.py SomePackage     # 追加下载指定包

产物落在 wheels/ 下，之后用
    pip install --no-index --find-links wheels <包名>
离线安装。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = "wheels"
PARTS = os.path.join(OUT, ".parts")
THREADS = 16
CHUNK = 256 * 1024
RETRIES = 4

DEFAULT_PACKAGES = [
    "PySide6-Essentials",
    "shiboken6",
    "PySide6-Fluent-Widgets",
    "PySideSix-Frameless-Window",
    "darkdetect",
    "pywin32",
]


def pick_url(package: str) -> tuple[str, int] | None:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=40) as r:
        data = json.load(r)
    candidates = [
        u
        for u in data["urls"]
        if u["filename"].endswith(".whl")
        and ("cp313" in u["filename"] or "abi3" in u["filename"] or "py3-none-any" in u["filename"])
        and ("win_amd64" in u["filename"] or "none-any" in u["filename"])
        # cp313t 是 free-threading 构建，装不到标准 CPython 上，必须排除
        and "cp313t" not in u["filename"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda u: u["upload_time"], reverse=True)
    return candidates[0]["url"], candidates[0]["size"]


def head_size(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=40) as r:
        return int(r.headers["Content-Length"])


def download_part(url: str, start: int, end: int, path: str) -> None:
    """下载 [start, end]（含端点）。已完成的分片直接跳过。"""
    expected = end - start + 1
    if os.path.exists(path) and os.path.getsize(path) == expected:
        return
    tmp = path + ".tmp"
    for attempt in range(RETRIES):
        try:
            got = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            req = urllib.request.Request(
                url, headers={"Range": f"bytes={start + got}-{end}"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "ab") as f:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
            if os.path.getsize(tmp) >= expected:
                os.replace(tmp, path)
                return
        except Exception as exc:  # noqa: BLE001
            print(f"    retry {attempt + 1} ({exc})", flush=True)
            time.sleep(1.5)
    raise RuntimeError(f"分片失败 {path}")


def download_one(package: str) -> None:
    info = pick_url(package)
    if info is None:
        print(f"[SKIP] {package}: 没有适配 cp313/win_amd64 的 wheel")
        return
    url, _ = info
    filename = url.rsplit("/", 1)[-1]
    target = os.path.join(OUT, filename)
    size = head_size(url)

    if os.path.exists(target) and os.path.getsize(target) == size:
        print(f"[OK  ] {filename} 已存在")
        return

    part_dir = os.path.join(PARTS, filename)
    os.makedirs(part_dir, exist_ok=True)

    per = max(1, size // THREADS)
    ranges = []
    pos = 0
    while pos < size:
        end = min(pos + per - 1, size - 1)
        ranges.append((pos, end))
        pos = end + 1

    done = sum(
        1
        for i, (s, e) in enumerate(ranges)
        if os.path.exists(os.path.join(part_dir, f"p{i:03d}"))
        and os.path.getsize(os.path.join(part_dir, f"p{i:03d}")) == e - s + 1
    )

    print(f"[GET ] {filename}  {size/1e6:.1f} MB  ({done}/{len(ranges)} 已就绪)", flush=True)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = [
            pool.submit(
                download_part,
                url,
                s,
                e,
                os.path.join(part_dir, f"p{i:03d}"),
            )
            for i, (s, e) in enumerate(ranges)
        ]
        for f in futures:
            f.result()

    with open(target, "wb") as out:
        for i in range(len(ranges)):
            with open(os.path.join(part_dir, f"p{i:03d}"), "rb") as p:
                out.write(p.read())

    elapsed = time.time() - t0
    got = os.path.getsize(target)
    print(
        f"[DONE] {filename}  {got/1e6:.1f} MB / {elapsed:.0f}s "
        f"({got/elapsed/1024:.0f} KB/s)",
        flush=True,
    )


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    packages = sys.argv[1:] or DEFAULT_PACKAGES
    for package in packages:
        download_one(package)
    print("\n全部 wheel 就绪，目录：", os.path.abspath(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
