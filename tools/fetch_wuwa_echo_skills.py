"""抓声骸技能说明，顺带用官方图床补齐缺失的声骸图标。

    .venv\\Scripts\\python tools\\fetch_wuwa_echo_skills.py            # 技能说明 + 图标 URL
    .venv\\Scripts\\python tools\\fetch_wuwa_echo_skills.py --icons    # 顺带补缺失的图标

| 抓什么 | 从哪抓 | 写进哪 |
|---|---|---|
| 声骸技能 / 冷却 | bwiki 每个声骸页的「声骸技能」段落（action=parse，一页一个声骸） | ``echoes.<名>.skill`` / ``.cooldown`` |
| 图标 URL | 库街区 getPage（catalogueId=1107）记录里的 ``contentUrl``（官方图床，一次全拿） | ``icon_urls`` |

**默认只写技能数据。** 加 ``--icons`` 才下载图标，且**只覆盖占位图**：
占位图是 make_placeholders.py 确定性画的（同参数重画字节一致），
逐个重画对比字节就能认出来 —— 真图标（fetch_wuwa_assets.py 下的 / 用户自己放的）绝不碰。

技能说明 bwiki 标注了"仅收录 5 星声骸数据"，少数页面没写技能是正常的，存空串。
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import pathlib
import re
import ssl
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import (  # noqa: E402
    ASSETS_ROOT,
    ECHO_SETS,
    EchoInfo,
)

DATA_FILE = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"

KUROBBS_PAGE = "https://api.kurobbs.com/wiki/core/catalogue/item/getPage"
BWIKI_API = "https://wiki.biligame.com/wutheringwaves/api.php"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
BWIKI_HEADERS = {"User-Agent": UA, "Referer": "https://wiki.biligame.com/"}
#: 对 bwiki 的礼貌间隔（秒）—— 一页一个请求，181 页不快不慢
DELAY = 0.35


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


def unique_echoes() -> dict[str, EchoInfo]:
    """全部声骸（按名字去重 —— 同一条声骸会出现在多个套装里）。"""
    result: dict[str, EchoInfo] = {}
    for echo_set in ECHO_SETS:
        for item in echo_set.echoes:
            result.setdefault(item.name, item)
    return result


def fetch_icon_urls() -> dict[str, str]:
    """库街区 getPage 一次拿全部声骸记录，提取 名字 → 官方图床 URL。"""
    body = urllib.parse.urlencode(
        {"catalogueId": "1107", "page": "1", "limit": "1000"}
    ).encode()
    request = urllib.request.Request(
        KUROBBS_PAGE,
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "wiki_type": "9",
        },
    )
    with urllib.request.urlopen(request, timeout=30, context=_ssl()) as r:
        data = json.loads(r.read().decode("utf-8"))
    records = data["data"]["results"]["records"]
    urls: dict[str, str] = {}
    for record in records:
        name = str(record.get("name", "")).strip()
        url = str((record.get("content") or {}).get("contentUrl", "") or "").strip()
        if name and url.startswith("http"):
            urls.setdefault(name, url)
    print(f"库街区：{len(records)} 条记录，提取出 {len(urls)} 个图标 URL")
    return urls


def parse_echo_page(name: str) -> dict[str, str]:
    """解析 bwiki 声骸页，返回 ``{"skill": ..., "cooldown": ...}``（拿不到就是空串）。"""
    title = f"声骸/{name}"
    url = f"{BWIKI_API}?{urllib.parse.urlencode({'action': 'parse', 'page': title, 'prop': 'text', 'format': 'json'})}"
    request = urllib.request.Request(url, headers=BWIKI_HEADERS)
    with urllib.request.urlopen(request, timeout=30, context=_ssl()) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(f"页面不存在或解析失败：{data['error'].get('info', '')}")
    page = data["parse"]["text"]["*"]

    def clean(block: str) -> str:
        block = re.sub(r"<br\s*/?>", "\n", block)
        block = re.sub(r"<[^>]+>", "", block)
        block = htmllib.unescape(block).replace("\xa0", " ")
        return "\n".join(line.strip() for line in block.split("\n")).strip(" \n")

    result = {"skill": "", "cooldown": ""}
    matched = re.search(r"声骸技能：.*?<p>(.*?)</p>", page, re.S)
    if matched:
        result["skill"] = clean(matched.group(1))
    matched = re.search(r"技能冷却：</b>\s*([^<\r\n]+)", page)
    if matched:
        result["cooldown"] = htmllib.unescape(matched.group(1)).strip()
    return result


# --------------------------------------------------------------------- 图标

def _placeholder_bytes(item: EchoInfo) -> bytes:
    """按 make_placeholders.py 的逻辑重画一张占位图，返回它的字节。

    占位图是确定性的（crc32 取色、同参数绘制），所以"文件字节 == 重画字节"
    就能断定这个文件是占位图 —— 这是**唯一**安全的覆盖判据，
    绝不能用"文件存在"当判据（会冲掉真图，2026-09-21 踩过）。

    直接 import tools/make_placeholders.py 复用它的 make_echo ——
    两份手抄逻辑迟早漂移，漂移了就认不出占位图。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_placeholders", ROOT / "tools" / "make_placeholders.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # 只 import，main() 不会跑

    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "probe.png"
        module.make_echo(item, out)
        return out.read_bytes()


def download_icons(icon_urls: dict[str, str], echoes: dict[str, EchoInfo]) -> None:
    """把是占位图的声骸图标换成官方图床的真图。"""
    replaced, kept_real, skipped = 0, 0, 0
    for name, item in echoes.items():
        path = ASSETS_ROOT / item.icon
        if not path.exists():
            skipped += 1
            continue
        if path.read_bytes() != _placeholder_bytes(item):
            kept_real += 1
            continue  # 真图，绝不碰
        url = icon_urls.get(name)
        if not url:
            skipped += 1
            continue
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=30, context=_ssl()) as r:
                payload = r.read()
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ 下载失败 {name}：{type(exc).__name__}: {exc}")
            skipped += 1
            continue
        path.write_bytes(payload)
        replaced += 1
        time.sleep(0.2)
    print(f"图标：替换占位图 {replaced} 张｜真图保留 {kept_real} 张｜跳过 {skipped} 个")


# --------------------------------------------------------------------- 主流程

def main() -> int:
    parser = argparse.ArgumentParser(description="抓声骸技能说明（bwiki）+ 官方图标 URL")
    parser.add_argument("--icons", action="store_true", help="顺带把占位图标换成官方图床的真图")
    args = parser.parse_args()

    echoes = unique_echoes()
    print(f"声骸共 {len(echoes)} 个（按名字去重）")

    print("=== 抓图标 URL（库街区 getPage，1 个请求）===")
    try:
        icon_urls = fetch_icon_urls()
    except Exception as exc:  # noqa: BLE001
        print(f"  失败（技能说明照抓）：{type(exc).__name__}: {exc}")
        icon_urls = {}

    print(f"=== 抓技能说明（bwiki，{len(echoes)} 页，间隔 {DELAY}s）===")
    skills: dict[str, dict[str, str]] = {}
    failures: list[str] = []
    for index, name in enumerate(sorted(echoes), 1):
        try:
            skills[name] = parse_echo_page(name)
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            skills[name] = {"skill": "", "cooldown": ""}
            print(f"  ⚠ {name}：{type(exc).__name__}: {exc}")
        if index % 30 == 0:
            print(f"  … {index}/{len(echoes)}")
        time.sleep(DELAY)

    got_skill = sum(1 for v in skills.values() if v["skill"])
    print(f"技能说明：{got_skill}/{len(echoes)} 个有内容" + (f"｜失败 {len(failures)} 个" if failures else ""))

    DATA_FILE.write_text(
        json.dumps(
            {
                "_source": (
                    "声骸技能/冷却来自 bwiki 每个声骸页的『声骸技能』段落（bwiki 标注仅收录 5 星数据）；"
                    "icon_urls 来自库街区官方 wiki（api.kurobbs.com getPage，catalogueId=1107）。"
                ),
                "_fetched": time.strftime("%Y-%m-%d"),
                "echoes": dict(sorted(skills.items())),
                "icon_urls": dict(sorted(icon_urls.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {DATA_FILE.relative_to(ROOT)}")

    if args.icons and icon_urls:
        print("=== 补图标（只覆盖占位图）===")
        download_icons(icon_urls, echoes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
