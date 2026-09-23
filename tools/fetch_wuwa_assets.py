"""从 bwiki 下载游戏素材：角色头像 / 声骸套装图标 / 声骸图标。

    .venv\\Scripts\\python tools\\fetch_wuwa_assets.py                  # 三类都下
    .venv\\Scripts\\python tools\\fetch_wuwa_assets.py --list           # 只看有什么，不下载
    .venv\\Scripts\\python tools\\fetch_wuwa_assets.py --only avatars   # 只下角色头像
    .venv\\Scripts\\python tools\\fetch_wuwa_assets.py --skip-existing  # 已有的不重下

下载目标**按数据文件里的名单来**（`src/core/data/*.json`），不会去搬 wiki 上
几百个用不着的图。

## 原理

bwiki 是 MediaWiki，素材文件命名很规整：

    文件:角色 <角色名> 头像.png     ->  assets/game/avatars/<角色名>.png
    文件:声骸合鸣 <套装名>.png       ->  assets/game/echo_sets/<套装名>.png
    文件:声骸 <声骸名> 头像.png      ->  assets/game/echoes/<声骸名>.png

所以走 API 列一遍就拿到全部直链，不用一个个页面去爬。

> ⚠ 用 `generator=allpages` 分页，**别用 `generator=allimages`** ——
> 后者按文件名排序且 500 条截断，会漏掉排在后面的角色（实测漏了 6 个）。

## 关于版权

**这些都是库洛游戏的美术素材，版权归库洛。** 这个脚本只是把公开 wiki 上的图
拉到你自己机器上，供你本地这个工具显示用。**别把下载下来的图再分发或商用。**
也正因为如此，`assets/game/` 整个目录在 `.gitignore` 里 —— 素材不进仓库。

wiki 上的图是社区整理的，尺寸不统一（角色头像有 256 和 500 两种），
也可能和游戏内有差异。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import ssl
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import ASSETS_ROOT, CHARACTERS, ECHO_SETS  # noqa: E402

API = "https://wiki.biligame.com/wutheringwaves/api.php"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REFERER = "https://wiki.biligame.com/"

#: 下载间隔，别把 wiki 惹毛了
DELAY = 0.15

#: 别名兜底：先按精确名找，找不到才试这里。
#: 实测 4 个漂泊者形态各有各的头像，这只是历史命名变过的保底。
ALIASES: dict[str, str] = {
    "漂泊者·衍射": "漂泊者",
    "漂泊者·气动": "漂泊者",
    "漂泊者·湮灭": "漂泊者",
    "漂泊者·导电": "漂泊者",
}


def _open(url: str, timeout: int = 45):
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
    return urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context())


def api(**params) -> dict:
    params.setdefault("format", "json")
    url = f"{API}?{urllib.parse.urlencode(params)}"
    with _open(url) as response:
        return json.loads(response.read().decode("utf-8"))


def list_files(prefix: str, suffix: str) -> dict[str, str]:
    """列全 wiki 上 ``<prefix><名字><suffix>`` 的文件 → ``{名字: 图片直链}``。

    分页取到底（``gapcontinue``），这是不漏图的关键。
    """
    found: dict[str, str] = {}
    cont: str | None = None
    for _round in range(20):  # 兜底，别真出不来就一直转
        params = dict(
            action="query",
            generator="allpages",
            gapnamespace="6",
            gapprefix=prefix,
            gaplimit="500",
            prop="imageinfo",
            iiprop="url",
        )
        if cont:
            params["gapcontinue"] = cont
        data = api(**params)

        for page in data.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            if not (title.startswith(f"文件:{prefix}") and title.endswith(suffix)):
                continue
            name = title[len(f"文件:{prefix}"): len(title) - len(suffix) if suffix else None]
            if not name or name in found:
                continue
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("url"):
                found[name] = info["url"]

        cont = data.get("continue", {}).get("gapcontinue")
        if not cont:
            break
    return found


def resolve_url(table: dict[str, str], name: str) -> str | None:
    """精确名优先，找不到再走别名。"""
    if name in table:
        return table[name]
    alias = ALIASES.get(name)
    return table.get(alias) if alias else None


def download(url: str, target: pathlib.Path) -> int:
    with _open(url) as response:
        blob = response.read()
    if not blob.startswith(b"\x89PNG"):
        raise ValueError(f"返回的不是 PNG（前 8 字节 {blob[:8]!r}）")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return len(blob)


# --------------------------------------------------------------------- 三类目标

def _avatar_items() -> list[tuple[str, str]]:
    return [(c.name, c.avatar) for c in CHARACTERS]


def _set_items() -> list[tuple[str, str]]:
    return [(s.name, s.icon) for s in ECHO_SETS]


def _echo_items() -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for echo_set in ECHO_SETS:
        for item in echo_set.echoes:
            seen.setdefault(item.name, item.icon)
    return list(seen.items())


#: 类别 -> (显示名, wiki 前缀, wiki 后缀, 取下载清单)
KINDS: dict[str, tuple[str, str, str, object]] = {
    "avatars": ("角色头像", "角色 ", " 头像.png", _avatar_items),
    "sets": ("套装图标", "声骸合鸣 ", ".png", _set_items),
    "echoes": ("声骸图标", "声骸 ", " 头像.png", _echo_items),
}


def run_kind(kind: str, skip_existing: bool, list_only: bool) -> tuple[int, int, list]:
    label, prefix, suffix, build = KINDS[kind]
    items = build()
    print(f"\n【{label}】名单里 {len(items)} 个，查询 wiki ...")

    try:
        table = list_files(prefix, suffix)
    except Exception as exc:  # noqa: BLE001 - 网络问题原样报出来
        print(f"  查询失败：{type(exc).__name__}: {exc}")
        return 0, 0, [(name, "wiki 查询失败") for name, _ in items]

    print(f"  wiki 上有 {len(table)} 个「{prefix}…{suffix}」文件")
    if list_only:
        return 0, 0, []

    done, skipped, failed = 0, 0, []
    for name, relative in items:
        url = resolve_url(table, name)
        target = ASSETS_ROOT / relative

        if url is None:
            failed.append((name, "wiki 上没有这张图"))
            continue
        if target.exists() and skip_existing:
            skipped += 1
            continue

        try:
            size = download(url, target)
            done += 1
            print(f"  ✓ {name:14} {size / 1024:6.0f} KB")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, f"{type(exc).__name__}: {exc}"))
        time.sleep(DELAY)

    print(f"  → 下载 {done}｜跳过 {skipped}｜失败 {len(failed)}")
    for name, reason in failed:
        print(f"    ✗ {name}：{reason}")
    return done, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description="从 bwiki 下载游戏素材")
    parser.add_argument("--only", choices=sorted(KINDS), help="只下某一类")
    parser.add_argument("--list", action="store_true", help="只列出 wiki 上有什么，不下载")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="已有的不重下（默认覆盖 —— 占位图就是这么被换成真图的）",
    )
    args = parser.parse_args()

    kinds = [args.only] if args.only else list(KINDS)
    total_done, total_failed = 0, 0
    for kind in kinds:
        done, _skipped, failed = run_kind(kind, args.skip_existing, args.list)
        total_done += done
        total_failed += len(failed)

    if args.list:
        print("\n（--list：到此为止，没有下载）")
        return 0

    print()
    print(f"合计下载 {total_done} 张，失败 {total_failed} 张")
    if total_done:
        print(f"素材目录：{ASSETS_ROOT}")
        print("重启程序就能看到（界面按 <名字>.png 自动匹配）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
