"""鸣潮资源库数据更新：后台拉取远端 → 对比本地 → 应用更新。

给「资源库更新」工具用，也可以命令行单跑：

    .venv\\Scripts\\python -m src.core.wuwa_update          # 只检查（打印差异）
    .venv\\Scripts\\python -m src.core.wuwa_update --apply  # 检查 + 应用

## 数据源与更新范围

| 数据 | 来源 | 检查 | 应用 |
|---|---|---|---|
| 套装效果 | bwiki「声骸合鸣」主页（1 个请求） | ✅ | ✅ 效果文字替换 / 新套装追加 |
| 声骸掉落池 | bwiki SMW 反查（1~2 个请求）∪ 库街区 getPage（1 个请求） | ✅ | ✅ 并集合并（不删已有） |
| 角色名单 | bwiki SMW 反查（``分类:共鸣者``，1~2 个请求） | ✅ | ✅ 新角色追加（不删已有） |
| 声骸技能说明 | bwiki 每个声骸页（一页一请求，慢） | ❌ 太重，不逐页查 | ✅ 只补**新增声骸**的页面 |

**并集**是刻意的：bwiki 的掉落池比库街区残缺，两边合并取并集才最全，
而且任何一边刷新都不能冲掉另一边补进来的条目（2026-09-22 踩过反向的坑）。
角色名单同理**只增不减** —— wiki 偶尔漏页，删掉会让用户已存的配置指向不存在的角色。

本模块和 ``tools/refresh_wuwa_data.py`` / ``tools/fetch_wuwa_echo_skills.py``
解析逻辑同源 —— 那两个是手动单跑的脚本，本模块给自动更新工具用。
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import game_data
from .game_data import DATA_ROOT

# --------------------------------------------------------------------- 常量

BWIKI_API = "https://wiki.biligame.com/wutheringwaves/api.php"
KUROBBS_PAGE = "https://api.kurobbs.com/wiki/core/catalogue/item/getPage"
SETS_PAGE = "声骸合鸣"
ECHO_ASK = "[[分类:声骸]]|?名称|?COST花费|?所属套装|limit=500"
#: 角色（共鸣者）SMW 反查 —— 「属性 / 武器」wiki 上有结构化字段，稀有度没有。
#: 稀有度本地若已有就保留（见 :func:`_merge_characters_data`），不拿 0 覆盖。
CHARACTER_ASK = "[[分类:共鸣者]]|?名称|?稀有度|?属性|?武器|limit=500"

SETS_FILE = DATA_ROOT / "wuwa_echo_sets.json"
SKILLS_FILE = DATA_ROOT / "wuwa_echo_skills.json"
CHARACTERS_FILE = DATA_ROOT / "wuwa_characters.json"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
#: 技能说明要逐页抓，对 bwiki 的礼貌间隔（秒）
DELAY = 0.35


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


# --------------------------------------------------------------------- 远端拉取

@dataclass
class RemoteSnapshot:
    """一次检查拉下来的全部远端数据（没拉到的字段是空容器，不报错）。"""

    #: ``{套装名: [{pieces, text}, ...]}`` —— bwiki 声骸合鸣表
    sets: dict[str, list[dict]] = field(default_factory=dict)
    #: ``{套装名: {4: [声骸名...]}}`` —— bwiki SMW 反查
    echoes_bwiki: dict[str, dict[int, list[str]]] = field(default_factory=dict)
    #: ``{套装名: {4: [声骸名...]}}`` —— 库街区（cost 键已转 int）
    echoes_kuro: dict[str, dict[int, list[str]]] = field(default_factory=dict)
    #: ``{声骸名: 官方图床 URL}`` —— 库街区
    icon_urls: dict[str, str] = field(default_factory=dict)
    #: ``{角色名: {rarity, element, weapon}}`` —— bwiki 分类:共鸣者
    characters: dict[str, dict] = field(default_factory=dict)


def fetch_remote(log=lambda _msg: None) -> RemoteSnapshot:
    """拉全部轻量数据源（套装表 + SMW 反查 + 库街区 getPage，共 3~4 个请求）。"""
    snapshot = RemoteSnapshot()
    snapshot.sets = _fetch_bwiki_sets(log)
    snapshot.echoes_bwiki = _fetch_bwiki_echo_index(log)
    snapshot.characters = _fetch_bwiki_characters(log)
    kuro_sets, icon_urls = _fetch_kurobbs(log)
    snapshot.echoes_kuro = kuro_sets
    snapshot.icon_urls = icon_urls
    return snapshot


def _get_json(url: str, headers: dict, data: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=45, context=_ssl()) as response:
        return json.loads(response.read().decode("utf-8"))


def _bwiki(**params) -> dict:
    params.setdefault("format", "json")  # 不加这个返回的是 HTML，json.loads 直接炸
    url = f"{BWIKI_API}?{urllib.parse.urlencode(params)}"
    return _get_json(url, {"User-Agent": _UA, "Referer": "https://wiki.biligame.com/"})


def _clean(text: str) -> str:
    text = htmllib.unescape(text).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _block_to_text(block: str) -> str:
    block = re.sub(r"<br\s*/?>", "\n", block)
    block = re.sub(r"</p>", "\n", block)
    block = re.sub(r"<[^>]+>", "", block)
    block = htmllib.unescape(block).replace("\xa0", " ")
    # wiki 模板没展开的 {11} → 11
    return re.sub(r"\{\s*(\d+(?:\.\d+)?)\s*\}", r"\1", block)


def _parse_effects(row_html: str) -> list[dict]:
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


def _fetch_bwiki_sets(log) -> dict[str, list[dict]]:
    log(f"拉取套装效果（bwiki {SETS_PAGE}）…")
    data = _bwiki(action="parse", page=SETS_PAGE, prop="text")
    parsed = data.get("parse")
    if not parsed:
        raise RuntimeError(f"bwiki 套装页解析失败：{data.get('error', {}).get('info', '')}")
    page = parsed["text"]["*"]
    result: dict[str, list[dict]] = {}
    for row in re.findall(r'<tr class="list">(.*?)</tr>', page, re.S):
        matched = re.search(r'title="声骸合鸣/([^"]+)"[^>]*>([^<]+)</a></center>', row)
        if not matched:
            continue
        result[_clean(matched.group(2))] = _parse_effects(row)
    log(f"  套装效果：{len(result)} 套")
    return result


def _fetch_bwiki_echo_index(log) -> dict[str, dict[int, list[str]]]:
    log("拉取声骸掉落池（bwiki SMW 反查）…")
    by_set: dict[str, dict[int, list[str]]] = {}
    offset = 0
    for _round in range(20):  # 防呆上限：正常 1~2 轮到底
        data = _bwiki(action="ask", query=ECHO_ASK, offset=offset)
        for item in data.get("query", {}).get("results", {}).values():
            out = item.get("printouts", {})
            name = (out.get("名称") or [""])[0]
            cost = str((out.get("COST花费") or [""])[0])
            if not name or cost not in ("1", "3", "4"):
                continue
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
    total = sum(len(names) for sets in by_set.values() for names in sets.values())
    log(f"  bwiki 掉落池：{len(by_set)} 套 / {total} 条")
    return by_set


def _fetch_bwiki_characters(log) -> dict[str, dict]:
    """拉角色名单（共鸣者）—— :data:`CHARACTER_ASK`  SMW 反查。

    用户 2026-09-28 要求："新角色的数据（能选到新角色）"。

    返回 ``{角色名: {"rarity": int, "element": str, "weapon": str}}``。

    ## 两个必须处理的坑（都是实测踩出来的）

    1. **同一角色有两个页面前缀**：wiki 上既有 ``共鸣者/景燃`` 也有 ``角色/景燃``，
       直接按「分类:共鸣者」反查会**同一个名字回来两次**。
       不合并的话名单里会出现重复项（下拉框里两个"景燃"）。
       这里按名字合并，字段取非空的那个。
    2. **``鸣潮:共鸣者预设``不是角色**，是模板页 —— 得跳过，
       否则名单里会混进一个叫「鸣潮:共鸣者预设」的假角色。

    稀有度 wiki 上**没有结构化字段**（返回空），所以这里可能是 0；
    合并时不会拿 0 覆盖本地已有的星级（见 :func:`_merge_characters_data`）。
    """
    log("拉取角色名单（bwiki 分类:共鸣者）…")
    merged: dict[str, dict] = {}
    offset = 0
    for _round in range(20):  # 防呆上限：正常 1~2 轮到底
        data = _bwiki(action="ask", query=CHARACTER_ASK, offset=offset)
        for key, item in data.get("query", {}).get("results", {}).items():
            if key.startswith("鸣潮:"):        # 模板页，不是角色
                continue
            out = item.get("printouts", {})
            name = (out.get("名称") or [""])[0] or key.split("/", 1)[-1]
            name = _clean(str(name))
            if not name or "/" in name:        # 名字里还带斜杠 → 不是角色条目
                continue
            info = {
                "rarity": _to_int((out.get("稀有度") or [0])[0]),
                "element": _clean(str((out.get("属性") or [""])[0])),
                "weapon": _clean(str((out.get("武器") or [""])[0])),
            }
            known = merged.get(name)
            if known is None:
                merged[name] = info
            else:
                # 同名（两个前缀）→ 字段取非空的，别让空值盖掉有值的
                for field_name, value in info.items():
                    if value and not known.get(field_name):
                        known[field_name] = value
        next_offset = data.get("query-continue-offset")
        if not next_offset:
            break
        offset = next_offset
    log(f"  角色名单：{len(merged)} 个")
    return merged


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fetch_kurobbs(log) -> tuple[dict[str, dict[int, list[str]]], dict[str, str]]:
    log("拉取库街区官方数据（getPage）…")
    body = urllib.parse.urlencode({"catalogueId": "1107", "page": "1", "limit": "1000"}).encode()
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "wiki_type": "9",
    }
    data = _get_json(KUROBBS_PAGE, headers, body)
    records = data["data"]["results"]["records"]

    # tagTree 是一棵树：根的 children 里有「套装」（34 个子节点才是套装标签）、
    # 「COST」（COST 4/3/1）、「级别」「异相声骸」等分组。
    # **只**把「套装」分组的子节点当套装 —— 不然 COST/级别标签会被当成套装名。
    set_tags: dict[str, str] = {}
    cost_tags: dict[str, int] = {}
    for group in data["data"].get("tagTree", {}).get("children", []) or []:
        group_name = str(group.get("name", "") or "")
        if group_name == "套装":
            for child in group.get("children", []) or []:
                node_id = str(child.get("id", "") or "")
                name = str(child.get("name", "") or "").strip()
                if node_id and name:
                    set_tags[node_id] = name
        elif group_name == "COST":
            for child in group.get("children", []) or []:
                node_id = str(child.get("id", "") or "")
                cost = str(child.get("name", "") or "").replace("COST", "").strip()
                if node_id and cost.isdigit():
                    cost_tags[node_id] = int(cost)

    by_set: dict[str, dict[int, list[str]]] = {}
    icon_urls: dict[str, str] = {}
    for record in records:
        name = str(record.get("name", "")).strip()
        content = record.get("content") or {}
        url = str(content.get("contentUrl", "") or "").strip()
        if name and url.startswith("http"):
            icon_urls.setdefault(name, url)

        tag_ids = [str(t) for t in (content.get("relateTagIds") or []) if t]
        set_names = [set_tags[t] for t in tag_ids if t in set_tags]
        cost = next((cost_tags[t] for t in tag_ids if t in cost_tags), 0)
        if not name or not set_names:
            continue
        for set_name in set_names:
            bucket = by_set.setdefault(set_name, {}).setdefault(cost, [])  # cost=0 是「记录没打 COST 标」
            if name not in bucket:
                bucket.append(name)
    log(f"  库街区：{len(records)} 条记录 / {len(icon_urls)} 个图标 URL / {len(set_tags)} 个套装标签")
    return by_set, icon_urls


# --------------------------------------------------------------------- 对比

@dataclass
class UpdateReport:
    """远端与本地的差异。"""

    #: 新套装（名字本地没有）
    new_sets: list[str] = field(default_factory=list)
    #: 套装效果文字有变化：``[(名字, 旧→新), ...]``（只记名字）
    effect_changed: list[str] = field(default_factory=list)
    #: 新声骸（远端有、本地掉落池里没有），含来源标注 ``名字（来源）``
    new_echoes: list[str] = field(default_factory=list)
    #: 新角色（远端有、本地名单里没有）—— 「能选到新角色」就是靠它
    new_characters: list[str] = field(default_factory=list)
    #: 远端**一个数据都没返回**（网络挂了 / wiki 页面结构变了）。
    #: 这时"没有更新"这个结论**不成立**，不能报"已是最新"。
    remote_empty: bool = False
    #: 本地数据文件是空的（没播种 / 被删 / 写坏）
    local_empty: bool = False

    #: 上面几项是否全空
    @property
    def has_updates(self) -> bool:
        return bool(self.new_sets or self.effect_changed or self.new_echoes
                    or self.new_characters)

    def summary(self) -> str:
        """给人看的变更摘要（界面 / 日志用）。"""
        lines: list[str] = []
        if self.remote_empty:
            return (
                "这次没从远端取到任何数据，所以无法判断有没有更新 —— "
                "多半是网络不通，或者 bwiki / 库街区的页面结构变了。\n"
                "请稍后点「重新检查」再试。"
            )
        if self.local_empty:
            lines.append(
                "⚠ 本地数据文件是空的（没播种 / 被删 / 写坏了），"
                "点「获取最新数据」可以重建。"
            )
        if self.new_sets:
            lines.append(f"新套装 {len(self.new_sets)} 个：{'、'.join(self.new_sets)}")
        if self.effect_changed:
            lines.append(f"效果更新 {len(self.effect_changed)} 套：{'、'.join(self.effect_changed)}")
        if self.new_echoes:
            shown = "、".join(self.new_echoes[:12])
            more = f" …等 {len(self.new_echoes)} 个" if len(self.new_echoes) > 12 else ""
            lines.append(f"新声骸 {len(self.new_echoes)} 个：{shown}{more}")
        if self.new_characters:
            lines.append(
                f"新角色 {len(self.new_characters)} 个："
                f"{'、'.join(self.new_characters)}"
            )
        return "\n".join(lines) if lines else "数据已是最新。"


def check_updates(snapshot: RemoteSnapshot, local_sets: dict | None = None,
                  local_characters: dict | None = None) -> UpdateReport:
    """对比远端快照和本地数据文件（``local_sets`` / ``local_characters`` 传了就用，方便测试）。"""
    if local_sets is None:
        local_sets = json.loads(SETS_FILE.read_text(encoding="utf-8")) if SETS_FILE.exists() else {}
    if local_characters is None:
        local_characters = (
            json.loads(CHARACTERS_FILE.read_text(encoding="utf-8"))
            if CHARACTERS_FILE.exists() else {}
        )
    local_by_name = {item.get("name"): item for item in local_sets.get("sets", [])}
    local_echo_names = {
        entry.get("name") for item in local_sets.get("sets", []) for entry in item.get("echoes", [])
    }

    report = UpdateReport()
    # 远端一条都没拉到 → 结论不成立。以前这里的表现是"安静地报数据已是最新"，
    # 明明什么都没查到却说没事，是**误导**。
    # ⚠ 角色也算一路数据源：只拉到角色、其它全挂时，仍应认为"取到了东西"。
    if (not snapshot.sets and not snapshot.echoes_bwiki
            and not snapshot.echoes_kuro and not snapshot.characters):
        report.remote_empty = True
        return report
    report.local_empty = not local_by_name

    for name, effects in snapshot.sets.items():
        local = local_by_name.get(name)
        if local is None:
            report.new_sets.append(name)
        elif local.get("effects") != effects:
            report.effect_changed.append(name)

    # ★ 库街区也带了套装名单（tagTree 的「套装」分组），而且**比 bwiki 全**。
    #   2026-09-30 实测：3.7 的「衔梦照世之心 / 镜影流电之瞬 / 茜染怀想之花」
    #   库街区**已经有**（37 套），bwiki 还停在上个版本（34 套）。
    #   以前只拿 bwiki 的套装修名单，于是"库街区明明同步了"却报「套装没有变化」
    #   —— 用户就是这么发现漏掉的（"现在更新了 3 套新的声骸套装，我怎么没看到呢"）。
    #   这里把库街区独有的套装也算进来；效果文字由用户手工补（见 _manual_effects）。
    for name in snapshot.echoes_kuro:
        if name not in local_by_name and name not in report.new_sets:
            report.new_sets.append(name)

    seen_new: set[str] = set()
    for source_label, remote in (("bwiki", snapshot.echoes_bwiki), ("库街区", snapshot.echoes_kuro)):
        for set_name, by_cost in remote.items():
            for _cost, names in by_cost.items():
                for echo_name in names:
                    if echo_name in local_echo_names or echo_name in seen_new:
                        continue
                    seen_new.add(echo_name)
                    report.new_echoes.append(f"{echo_name}（{source_label}）")

    # 角色：远端有、本地名单里没有 → 新角色（用户 2026-09-28 要求能选到）
    local_names = {
        str(item.get("name", "")).strip()
        for item in local_characters.get("characters", []) or []
        if isinstance(item, dict)
    }
    for name in snapshot.characters:
        if name not in local_names:
            report.new_characters.append(name)
    return report


# --------------------------------------------------------------------- 应用

def _merge_sets_data(local_sets: dict, snapshot: RemoteSnapshot) -> bool:
    """把远端数据并进 ``local_sets``（就地修改）。返回是否有变化。

    纯数据操作，不碰磁盘 —— 单测可以直接喂 dict。
    """
    sets: list[dict] = local_sets.setdefault("sets", [])
    by_name = {item.get("name"): item for item in sets}
    changed = False

    # 套装：新增追加到末尾（游戏数据加载时自己按版本排序），效果变化整表替换
    for name, effects in snapshot.sets.items():
        local = by_name.get(name)
        if local is None:
            by_name[name] = {"name": name, "effects": effects}
            sets.append(by_name[name])
            changed = True
        elif local.get("effects") != effects and effects:
            local["effects"] = effects
            changed = True

    # ★ 库街区独有的套装（bwiki 还没收录的）也要建出来 —— 否则它带的声骸
    #   会被 _union_echoes 因为"找不到这个套装"而**整批丢掉**（那正是新套装
    #   的声骸一条都进不来的原因）。效果文字这里留空：bwiki 才是效果文字的
    #   来源，库街区只给名单 + 声骸归属；空缺由手工补录兜底（见 set_effects）。
    for name in snapshot.echoes_kuro:
        if name not in by_name:
            by_name[name] = {"name": name, "effects": []}
            sets.append(by_name[name])
            changed = True

    # 声骸掉落池：bwiki ∪ 库街区，对本地取并集（只加不减）
    merged_names: set[str] = set()
    for set_name, by_cost in snapshot.echoes_bwiki.items():
        _union_echoes(by_name, set_name, by_cost)
        merged_names.add(set_name)
    for set_name, by_cost in snapshot.echoes_kuro.items():
        # 库街区的 COST 档在 getPage 里拿不到（记录没有 cost 字段），
        # 它的条目按名字并进 bwiki 给出的档位；bwiki 也没有的名字进 0 桶 → 跳过。
        _union_echoes(by_name, set_name, by_cost)
        merged_names.add(set_name)

    local_sets["_fetched"] = time.strftime("%Y-%m-%d")
    return changed


def _merge_characters_data(local_chars: dict, snapshot: RemoteSnapshot) -> bool:
    """把远端角色名单并进 ``local_chars``（就地修改）。返回是否有变化。

    纯数据操作，不碰磁盘 —— 单测可以直接喂 dict。

    ## 规则（与套装一致的"只增不减"思路）

    * **新角色追加**（这就是"能选到新角色"）；
    * **已有角色不删**：wiki 偶尔漏页 / 改名，删掉会让用户已存的配置和任务
      指向一个不存在的角色（``find_character`` 查不到 → 头像消失、名字报错）。
      宁可留着过时的，也不要删；
    * **属性 / 武器**：远端有值且和本地不同就更新（wiki 修正过的更可信）；
      远端为空时**保留本地的** —— 别拿空串盖掉已有信息；
    * **稀有度**：wiki 没有结构化字段（常返回 0），所以**只在本地为 0 时**才写入，
      绝不拿 0 覆盖本地已知的星级。
    """
    chars: list[dict] = local_chars.setdefault("characters", [])
    by_name = {
        str(item.get("name", "")).strip(): item
        for item in chars if isinstance(item, dict)
    }
    changed = False
    added: list[str] = []

    for name, info in snapshot.characters.items():
        local = by_name.get(name)
        if local is None:
            entry = {
                "name": name,
                "rarity": _to_int(info.get("rarity")),
                "element": str(info.get("element") or ""),
                "weapon": str(info.get("weapon") or ""),
            }
            by_name[name] = entry
            chars.append(entry)
            added.append(name)
            changed = True
            continue
        # 已有角色：只补空字段 / 更新非空且不同值
        for field_name in ("element", "weapon"):
            value = str(info.get(field_name) or "")
            if value and local.get(field_name) != value:
                local[field_name] = value
                changed = True
        rarity = _to_int(info.get("rarity"))
        if rarity and _to_int(local.get("rarity")) == 0:
            local["rarity"] = rarity
            changed = True

    if added:
        local_chars["_fetched"] = time.strftime("%Y-%m-%d")
    return changed


def _union_echoes(by_name: dict, set_name: str, by_cost: dict) -> None:
    target = by_name.get(set_name)
    if target is None:
        return
    old_by_cost: dict[int, list[str]] = {}
    for entry in target.get("echoes", []):
        old_by_cost.setdefault(int(entry.get("cost", 0) or 0), []).append(entry["name"])
    merged = {cost: list(names) for cost, names in old_by_cost.items()}
    for cost, names in by_cost.items():
        if cost == 0:
            # 未知档位：挂到本地已有的档位里（按名字找），找不到就 4C（最常见）
            for echo_name in names:
                if not any(echo_name in bucket for bucket in merged.values()):
                    known = _find_cost(by_name, echo_name)
                    merged.setdefault(known, []).append(echo_name)
            continue
        bucket = merged.setdefault(cost, [])
        for echo_name in names:
            if echo_name not in bucket:
                bucket.append(echo_name)
    target["echoes"] = [
        {"name": echo_name, "cost": cost}
        for cost in sorted(merged, reverse=True)
        for echo_name in merged[cost]
    ]


def _find_cost(by_name: dict, echo_name: str) -> int:
    """在其它套装的掉落池里查这个名字的档位；查不到返回 4。"""
    for item in by_name.values():
        for entry in item.get("echoes", []):
            if entry.get("name") == echo_name:
                return int(entry.get("cost", 4) or 4)
    return 4


def _fetch_skill(name: str) -> dict[str, str]:
    """抓一条声骸页的技能说明（拿不到返回空串，不抛异常）。"""
    try:
        title = f"声骸/{name}"
        data = _bwiki(action="parse", page=title, prop="text")
        page = data["parse"]["text"]["*"]
    except Exception:  # noqa: BLE001 - 页面不存在是常态（新声骸 bwiki 还没建页）
        return {"skill": "", "cooldown": ""}

    def clean(block: str) -> str:
        block = re.sub(r"<br\s*/?>", "\n", block)
        block = re.sub(r"<[^>]+>", "", block)
        return "\n".join(
            line.strip() for line in htmllib.unescape(block).replace("\xa0", " ").split("\n")
        ).strip(" \n")

    result = {"skill": "", "cooldown": ""}
    matched = re.search(r"声骸技能：.*?<p>(.*?)</p>", page, re.S)
    if matched:
        result["skill"] = clean(matched.group(1))
    matched = re.search(r"技能冷却：</b>\s*([^<\r\n]+)", page)
    if matched:
        result["cooldown"] = htmllib.unescape(matched.group(1)).strip()
    return result


def apply_updates(
    snapshot: RemoteSnapshot, report: UpdateReport, log=lambda _msg: None
) -> list[str]:
    """把远端数据写进本地 JSON，并**立刻让内存里的数据同步**。返回做了什么（给人看的行列表）。

    写盘之后会调 :func:`game_data.reload_data` 就地刷新内存数据 ——
    所以资源库页不用重启程序就能看到新数据（以前这里要求"重启 MyTools 才生效"）。
    """
    done: list[str] = []

    # 1) 套装 + 掉落池
    local_sets = json.loads(SETS_FILE.read_text(encoding="utf-8")) if SETS_FILE.exists() else {}
    if _merge_sets_data(local_sets, snapshot):
        SETS_FILE.write_text(
            json.dumps(local_sets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        done.append(
            f"套装/掉落池已更新（新套装 {len(report.new_sets)}、"
            f"效果 {len(report.effect_changed)}、新声骸 {len(report.new_echoes)}）"
        )
    else:
        done.append("套装/掉落池没有变化")

    # 1.5) 角色名单（用户 2026-09-28："新角色的数据（能选到新角色）"）
    #      只增不减：新角色追加，已有角色保留（wiki 漏页也不删）。
    local_chars = (
        json.loads(CHARACTERS_FILE.read_text(encoding="utf-8"))
        if CHARACTERS_FILE.exists() else {}
    )
    if _merge_characters_data(local_chars, snapshot):
        CHARACTERS_FILE.write_text(
            json.dumps(local_chars, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        done.append(
            f"角色名单已更新（新角色 {len(report.new_characters)} 个"
            f"：{'、'.join(report.new_characters) if report.new_characters else '无'}）"
        )
    elif snapshot.characters:
        done.append("角色名单没有变化")

    # 2) 技能说明 + 图标 URL：只补缺的（新声骸），老数据不动
    skills = json.loads(SKILLS_FILE.read_text(encoding="utf-8")) if SKILLS_FILE.exists() else {}
    skills.setdefault("echoes", {})
    if snapshot.icon_urls:
        skills["icon_urls"] = dict(snapshot.icon_urls)
        skills["_source"] = (
            "声骸技能/冷却来自 bwiki 每个声骸页的『声骸技能』段落（bwiki 标注仅收录 5 星数据）；"
            "icon_urls 来自库街区官方 wiki（api.kurobbs.com getPage，catalogueId=1107）。"
        )
        skills["_fetched"] = time.strftime("%Y-%m-%d")
        done.append(f"图标 URL 已刷新（{len(snapshot.icon_urls)} 个）")

    new_names = [item.split("（")[0] for item in report.new_echoes]
    if new_names:
        log(f"补抓 {len(new_names)} 个新声骸的技能说明（一页一个请求，稍等）…")
        got = 0
        for index, name in enumerate(sorted(new_names), 1):
            info = _fetch_skill(name)
            skills["echoes"].setdefault(name, {}).update(info)
            if info["skill"]:
                got += 1
            time.sleep(DELAY)
            if index % 10 == 0:
                log(f"  … {index}/{len(new_names)}")
        done.append(f"新声骸技能说明：{got}/{len(new_names)} 个抓到（其余 bwiki 还没建页）")

    if skills.get("echoes") or snapshot.icon_urls:
        SKILLS_FILE.write_text(
            json.dumps(skills, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    # 就地重载内存数据：资源库页在下次显示时会发现版本号变了并重建，不必重启程序
    game_data.reload_data()
    done.append("已写盘，并已就地刷新内存数据 —— 打开资源库页即可看到最新内容（不用重启）。")
    return done


# --------------------------------------------------------------------- 命令行

def main() -> int:
    parser = argparse.ArgumentParser(description="鸣潮资源库数据更新（检查 / 应用）")
    parser.add_argument("--apply", action="store_true", help="检查到更新后直接应用（默认只报告）")
    args = parser.parse_args()

    def log(message: str) -> None:
        print(message, flush=True)

    # 命令行入口同样要先把种子数据摆好 —— 否则首启动会对着一个不存在的文件做检查
    from . import paths

    seeded = paths.ensure_user_data()
    if seeded:
        log(f"首次运行，已初始化用户数据 {len(seeded)} 个文件 → {paths.user_data_dir()}")

    snapshot = fetch_remote(log)
    report = check_updates(snapshot)
    print("--- 检查结果 ---")
    print(report.summary())
    if report.has_updates and args.apply:
        print("--- 应用更新 ---")
        for line in apply_updates(snapshot, report, log):
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
