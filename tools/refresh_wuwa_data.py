"""从公开 wiki（bwiki）刷新鸣潮资料。

    .venv\\Scripts\\python tools\\refresh_wuwa_data.py              # 只刷新套装效果（快）
    .venv\\Scripts\\python tools\\refresh_wuwa_data.py --echoes     # 顺带刷新声骸明细（34 个页面，慢）
    .venv\\Scripts\\python tools\\refresh_wuwa_data.py --all --write

| 刷什么 | 抓什么 | 写进 JSON 的哪个字段 |
|---|---|---|
| 套装效果 | 「声骸合鸣」主页 | 每套的 ``effects``（2/5 件套原文）|
| 声骸明细 | 每套的详情页 ``声骸合鸣/<套装名>`` | 每套的 ``echoes``（4C/3C/1C 各有哪些声骸）|

**默认只预览，加 `--write` 才写盘。**

角色的属性 / 武器不在这里刷 —— 那份是从攻略站整理的，wiki 页面上没有结构化数据。
角色名会打印出来供比对（wiki 上有一部分是缩写名，自动覆盖会弄坏名单）。

⚠ 这是第三方 wiki，不是官方接口。页面结构改版了，正则要跟着改。
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import pathlib
import re
import ssl
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "src" / "core" / "data"
SETS_FILE = DATA_DIR / "wuwa_echo_sets.json"

API = "https://wiki.biligame.com/wutheringwaves/api.php"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
REFERER = "https://wiki.biligame.com/"

SETS_PAGE = "声骸合鸣"


def api(**params) -> dict:
    params.setdefault("format", "json")
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
    with urllib.request.urlopen(request, timeout=45, context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode("utf-8"))


def page_html(page: str) -> str:
    data = api(action="parse", page=page, prop="text")
    parsed = data.get("parse")
    if not parsed:
        raise RuntimeError(f"页面解析失败：{page}（{data.get('error', {}).get('info', '无详情')}）")
    return parsed["text"]["*"]


def clean(text: str) -> str:
    text = htmllib.unescape(text).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


# --------------------------------------------------------------------- 套装效果

def _block_to_text(block: str) -> str:
    block = re.sub(r"<br\s*/?>", "\n", block)
    block = re.sub(r"</p>", "\n", block)
    block = re.sub(r"<[^>]+>", "", block)
    block = htmllib.unescape(block).replace("\xa0", " ")
    # wiki 模板没展开的 {11} → 11
    block = re.sub(r"\{\s*(\d+(?:\.\d+)?)\s*\}", r"\1", block)
    return block


def parse_effects(row_html: str) -> list[dict]:
    """从一行 ``<tr class="list">`` 里抠出 ``[{pieces, text}, ...]``。

    同一条效果里可能有 ``<br>`` 分段（比如"拥有【落雪】效果时："后面跟几个
    ``·`` 开头的子条），这些续行要并回上一条。
    """
    cells = re.findall(r"<td>(.*?)</td>", row_html, re.S)
    if not cells:
        return []

    effects: list[dict] = []
    for line in _block_to_text(cells[-1]).split("\n"):
        line = line.strip()
        if not line:
            continue
        matched = re.match(r"^(\d+)\s*件套[：:]\s*(.+)$", line)
        if matched:
            effects.append({"pieces": int(matched.group(1)), "text": matched.group(2).strip()})
        elif effects:
            effects[-1]["text"] = f"{effects[-1]['text']}\n{line}"
    return effects


def parse_sets(page: str) -> list[dict]:
    rows = re.findall(r'<tr class="list">(.*?)</tr>', page, re.S)
    result: list[dict] = []
    for row in rows:
        matched = re.search(r'title="声骸合鸣/([^"]+)"[^>]*>([^<]+)</a></center>', row)
        if not matched:
            continue
        result.append({"name": clean(matched.group(2)), "effects": parse_effects(row)})
    return result


# --------------------------------------------------------------------- 声骸明细
#
# 早期是去每个套装的详情页（``声骸合鸣/<套装名>``）按 COST 分段抓的 —— **抓不全**：
# 详情页上列的是编辑手工挑的一小撮，2.2~3.3 的套装尤其残缺
# （比如「雪落无声之愿」页面上 3C 只有 1 个、1C 一个都没有）。
#
# 更全的源头在**声骸自己的页面**：每个声骸页都写了 ``所属套装``（英文逗号分隔）
# 和 ``COST花费``。这个 wiki 开了 SemanticMediaWiki，所以能用 ``action=ask``
# 一次把 139 个声骸全查下来，再反过来拼出「套装 → 声骸」。
#
# 实测同一条声骸经常属于好几个套装（例如「重工铁蹄」同时属于
# 逆光跃彩之约 / 雪落无声之愿 / 剪心辑梦之影），所以必须走反向索引。
#
# ⚠ 即便如此也不是全的：wiki 只给 1.0 / 2.0 / 3.5 的套装填了完整的掉落池，
#   2.2~3.3 只登记了「该版本新增的专属声骸」。缺的部分已用**官方库街区 wiki**
#   （api.kurobbs.com，POST getPage，catalogueId=1107，请求头 wiki_type: 9）
#   补全，原始数据在 src/core/data/kurobbs_echoes_raw.json。
#   合并是并集：这里刷新只会追加，不会冲掉官方补充的条目。

ECHO_ASK = "[[分类:声骸]]|?名称|?COST花费|?所属套装|?实装版本|limit=500"


def fetch_echo_index() -> dict[str, dict[int, list[str]]]:
    """一次查全部声骸，反拼成 ``{套装名: {4: [...], 3: [...], 1: [...]}}``。"""
    by_set: dict[str, dict[int, list[str]]] = {}
    offset = 0
    pages = 0
    while pages < 20:  # 上限只是防呆：正常情况下 1~2 轮就到底
        data = api(action="ask", query=ECHO_ASK, offset=offset)
        pages += 1
        for item in data.get("query", {}).get("results", {}).values():
            out = item.get("printouts", {})
            name = (out.get("名称") or [""])[0]
            cost = str((out.get("COST花费") or [""])[0])
            if not name or cost not in ("1", "3", "4"):
                continue  # 分类里混着个别没填完的条目，跳过
            raw_sets = (out.get("所属套装") or [""])[0]
            for set_name in (part.strip() for part in raw_sets.split(",")):
                if not set_name:
                    continue
                bucket = by_set.setdefault(set_name, {}).setdefault(int(cost), [])
                if name not in bucket:
                    bucket.append(name)
        next_offset = data.get("query-continue-offset")
        if not next_offset:
            break
        offset = next_offset
    print(f"  （声骸索引：{pages} 次请求，覆盖 {len(by_set)} 套）")
    return by_set


# --------------------------------------------------------------------- 合并

def merge_sets(existing: dict, fetched: list[dict], echoes: dict[str, dict] | None) -> bool:
    sets: list[dict] = existing.setdefault("sets", [])
    by_name = {item.get("name"): item for item in sets}

    added: list[str] = []
    effect_changed: list[str] = []
    echo_changed: list[str] = []

    for item in fetched:
        old = by_name.get(item["name"])
        if old is None:
            old = {"name": item["name"], "effects": item["effects"]}
            sets.append(old)
            by_name[item["name"]] = old
            added.append(item["name"])
        elif old.get("effects") != item["effects"]:
            old["effects"] = item["effects"]
            effect_changed.append(item["name"])

    if echoes:
        # 并集合并，不是整表替换：声骸明细里可能已经有官方库街区补充的条目
        # （kurobbs_echoes_raw.json → wuwa_echo_sets.json），bwiki 的掉落池比官方残缺，
        # 直接替换会把官方补的 43 条冲掉。
        for name, by_cost in echoes.items():
            target = by_name.get(name)
            if target is None:
                continue
            old_by_cost: dict[int, list[str]] = {}
            for entry in target.get("echoes", []):
                old_by_cost.setdefault(entry["cost"], []).append(entry["name"])
            merged = {cost: list(names) for cost, names in old_by_cost.items()}
            for cost, names in by_cost.items():
                bucket = merged.setdefault(cost, [])
                for echo_name in names:
                    if echo_name not in bucket:
                        bucket.append(echo_name)
            new_list = [
                {"name": echo_name, "cost": cost}
                for cost in sorted(merged, reverse=True)
                for echo_name in merged[cost]
            ]
            if target.get("echoes") != new_list:
                target["echoes"] = new_list
                echo_changed.append(f"{name}({len(new_list)})")

    order = {item["name"]: index for index, item in enumerate(fetched)}
    sets.sort(key=lambda s: order.get(s.get("name"), 10**6))

    print(f"  套装 {len(fetched)} 套｜新增 {len(added)}｜效果变化 {len(effect_changed)}")
    if added:
        print(f"    新增：{'、'.join(added)}")
    if effect_changed:
        print(f"    效果更新：{'、'.join(effect_changed)}")
    if echoes:
        print(f"  声骸明细更新 {len(echo_changed)} 套：{'、'.join(echo_changed)}")

    return bool(added or effect_changed or echo_changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="从 bwiki 刷新鸣潮资料")
    parser.add_argument("--echoes", action="store_true", help="顺带刷新声骸明细（34 个页面）")
    parser.add_argument("--all", action="store_true", help="同 --echoes")
    parser.add_argument("--write", action="store_true", help="真正写回 JSON（默认只预览）")
    args = parser.parse_args()

    print(f"=== 抓套装效果（{SETS_PAGE}）===")
    try:
        fetched = parse_sets(page_html(SETS_PAGE))
    except Exception as exc:  # noqa: BLE001
        print(f"  失败：{type(exc).__name__}: {exc}")
        return 1
    print(f"  解析出 {len(fetched)} 套")
    empty = [item["name"] for item in fetched if not item["effects"]]
    if empty:
        print(f"  ⚠ 没解析出效果（页面可能改版了）：{'、'.join(empty)}")

    want_echoes = args.echoes or args.all
    echoes: dict[str, dict] = {}
    if want_echoes:
        print("=== 抓声骸明细（反查每条声骸的『所属套装』）===")
        try:
            echoes = fetch_echo_index()
        except Exception as exc:  # noqa: BLE001
            print(f"  失败：{type(exc).__name__}: {exc}")
            return 1
        for item in fetched:
            name = item["name"]
            got = echoes.get(name, {})
            counts = " ".join(
                f"{cost}C×{len(names)}" for cost, names in sorted(got.items(), reverse=True)
            )
            print(f"  {name}：{counts or '空（wiki 还没收录）'}")

    print("=== 合并进现有数据 ===")
    existing = json.loads(SETS_FILE.read_text(encoding="utf-8"))
    before = json.dumps(existing, ensure_ascii=False, sort_keys=True)
    changed = merge_sets(existing, fetched, echoes if want_echoes else None)
    after = json.dumps(existing, ensure_ascii=False, sort_keys=True)

    if before == after:
        print("  内容和磁盘上一致，没有需要写的。")
        return 0
    if not args.write:
        print("  ↑ 预览。要写盘请加 --write")
        return 0
    if not changed:
        return 0

    SETS_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  已写入 {SETS_FILE.relative_to(ROOT)}")
    print("  提示：声骸名单变了之后，跑 tools/make_placeholders.py 补占位图，")
    print("        或 tools/fetch_wuwa_assets.py --only echoes 下真图标。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
