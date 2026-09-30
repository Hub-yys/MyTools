"""从 **bwiki（主力）+ 库街区（兜底）** 下载游戏素材：角色头像 / 声骸套装图标 / 声骸图标。

⚠ 为什么要两个源：bwiki 只收录了 181 个声骸里的 **130** 个，
剩下 51 个（风鳞蜃甲 / 霜鳞蜃甲 / 影烁者 …）一直缺图、界面上是空白。
用户 2026-09-27 指出"这些图片库街区应该全部都是有的" —— 核实：
「资源库更新」抓下来的 199 条库街区 ``icon_urls`` 里，**51 个缺的全都在**。
所以 bwiki 查不到时自动改走库街区（图片规格实测一致：256×256 RGBA 透明 PNG）。

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


#: ★ 库街区兜底（2026-09-27）
#: bwiki 只收录了 181 个声骸里的 **130** 个，剩下 51 个（风鳞蜃甲 / 霜鳞蜃甲 / 影烁者 …）
#: 一直缺图；用户指出"这些图片库街区应该全部都是有的" —— 去核了一下，
#: 库里那份 ``icon_urls`` **199 条、51 个缺的全都在**。
#: 这些 URL 是「资源库更新」（``src/core/wuwa_update.py``）抓下来的，存在下面这个文件里。
#: 实测图床给的是 **256×256 RGBA 透明 PNG，和 bwiki 那批完全同规格**，可以放心混用。
KUROBBS_ICON_JSON = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"
KUROBBS_REFERER = "https://www.kurobbs.com/"


def kurobbs_icons() -> dict[str, str]:
    """``{名字: 库街区图床 URL}``。读不到就返回空表 —— 不影响原来走 bwiki 那条路。"""
    try:
        raw = json.loads(KUROBBS_ICON_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    urls = raw.get("icon_urls")
    return {str(k): str(v) for k, v in urls.items()} if isinstance(urls, dict) else {}


#: 库街区 wiki 的 getPage 接口（和 ``src/core/wuwa_update.py`` 用的是同一个）
KUROBBS_PAGE = "https://api.kurobbs.com/wiki/core/catalogue/item/getPage"
#: catalogueId 映射（实测）：1105 角色 / 1106 武器 / 1107 声骸 / 1219 套装
KUROBBS_CATALOGUES = {"1105": "角色", "1106": "武器", "1107": "声骸",
                      "1219": "套装"}


def kurobbs_records(catalogue_id: str) -> tuple[list[dict], dict]:
    """拉库街区某一类的全部条目：``(records, tagTree)``。

    ⚠ 网页 URL 是 ``?fid=1099&sid=1219`` —— **``sid`` 才是 catalogueId**；
    传 ``fid`` 会返回 0 条且 ``code=200``（静默空，不报错）。
    """
    body = urllib.parse.urlencode(
        {"catalogueId": str(catalogue_id), "page": "1", "limit": "1000"}
    ).encode()
    request = urllib.request.Request(
        KUROBBS_PAGE, data=body,
        headers={"User-Agent": UA, "Referer": KUROBBS_REFERER,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "wiki_type": "9"})
    with urllib.request.urlopen(request, timeout=60,
                                context=ssl.create_default_context()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data") or {}
    records = (data.get("results") or {}).get("records") or []
    return list(records), data.get("tagTree") or {}


def _open(url: str, timeout: int = 45, referer: str = REFERER):
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": referer})
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


def download(url: str, target: pathlib.Path, referer: str = REFERER) -> int:
    with _open(url, referer=referer) as response:
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


def _weapon_items() -> list[tuple[str, str]]:
    """武器图标的下载清单。

    ⚠ 武器**没有**本地数据文件（不像角色有 ``wuwa_characters.json``），
    所以名单**直接问库街区**（catalogue 1106「武器」，实测 123 把）——
    这比"从 icon_urls 里猜哪些是武器"准得多（那份是混在一起的，
    分不出武器 / 声骸 / 角色）。

    路径：``assets/game/weapons/<武器名>.png``
    """
    try:
        records, _tree = kurobbs_records("1106")
    except Exception:  # noqa: BLE001 - 拿不到就当没有（不影响别的类别）
        return []
    items: list[tuple[str, str]] = []
    for record in records:
        name = str(record.get("name", "")).strip()
        if name:
            items.append((name, f"weapons/{name}.png"))
    return items


#: 类别 -> (显示名, wiki 前缀, wiki 后缀, 取下载清单)
KINDS: dict[str, tuple[str, str, str, object]] = {
    "avatars": ("角色头像", "角色 ", " 头像.png", _avatar_items),
    "sets": ("套装图标", "声骸合鸣 ", ".png", _set_items),
    "echoes": ("声骸图标", "声骸 ", " 头像.png", _echo_items),
    "weapons": ("武器图标", "武器 ", ".png", _weapon_items),
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

    # 声骸图缺得多（bwiki 只收了 181 个里的 130 个）→ 用库街区兜底；
    # ★ 套装图标同理（2026-09-30 补）：bwiki 的套装图标页不全，
    #   而库街区那份 icon_urls 里**有全部套装图标**（catalogue 1219）。
    #   ★ 武器同理（2026-09-30 再补）：抽卡卡片墙要显示武器图。
    #   原来这里写的是 `if kind == "echoes"`，于是套装/武器永远只走 bwiki、
    #   缺的那些就一直是占位图 —— 用户发现"明明有图标为什么不加上去"。
    kuro = kurobbs_icons() if kind in ("echoes", "sets", "weapons") else {}
    if kuro:
        print(f"  库街区兜底表里 {len(kuro)} 个图标 URL（wiki 查不到的会走它）")

    done, skipped, failed = 0, 0, []
    for name, relative in items:
        url = resolve_url(table, name)
        referer, source = REFERER, "wiki"
        if url is None and name in kuro:
            url, referer, source = kuro[name], KUROBBS_REFERER, "库街区"
        target = ASSETS_ROOT / relative

        if url is None:
            failed.append((name, "wiki 上没有、库街区也没有"))
            continue
        if target.exists() and skip_existing:
            skipped += 1
            continue

        try:
            size = download(url, target, referer=referer)
            done += 1
            print(f"  ✓ {name:14} {size / 1024:6.0f} KB  [{source}]")
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
