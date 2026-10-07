"""鸣潮资源库数据更新：后台拉取远端 → 对比本地 → 应用更新。

给「资源库更新」工具用，也可以命令行单跑：

    .venv\\Scripts\\python -m src.core.wuwa_update          # 只检查（打印差异）
    .venv\\Scripts\\python -m src.core.wuwa_update --apply  # 检查 + 应用

## 数据源：**只从库街区官方 wiki 拿**（2026-10-01 起）

用户明确要求："除去一切其他来源数据，只从库街区拿"。

| 数据 | 来源（全部库街区） | 检查 | 应用 |
|---|---|---|---|
| 声骸名单 + 套装归属 | ``getPage`` catalogueId=**1107** | ✅ | ✅ 并集合并（不删已有） |
| 套装名单 + 图标 | ``getPage`` catalogueId=**1219** | ✅ | ✅ 新套装追加 |
| 角色名单 + 属性 + 稀有度 | ``getPage`` catalogueId=**1105** | ✅ | ✅ 新角色追加（不删已有） |
| 角色 / 武器图标 | ``getPage`` catalogueId=1105 / **1106** | ✅ | ✅ |
| **套装效果原文** | ``getEntryDetail``（1219 条目的详情） | ✅ | ✅ 效果文字替换 |
| **声骸技能说明** | ``getEntryDetail``（1107 条目的详情） | ✅ | ✅ 只补缺的 |

> ⚠ **bwiki 已经整个拿掉了**（``BWIKI_API`` / ``_fetch_bwiki_*`` / ``_fetch_skill``
> 全部删除）。理由是实测它**没有独占数据**：库街区 37 套 / 205 声骸 / 60 角色，
> bwiki 只有 34 / 255 条 / 58，**全是子集**；留着它只会因为两个源的**文字措辞
> 不同**而永远报"效果更新 30 套"（用户报的假报就是这个）。
> 顺带每次检查少打 3 个请求。

**只增不减**是刻意的：数据源偶尔漏页 / 改名，删掉会让用户已存的配置和任务
指向一个不存在的角色或套装。宁可留着过时的，也不要删。

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

from . import game_data
from .game_data import DATA_ROOT

# --------------------------------------------------------------------- 常量

#: ★ 数据**只从这里拿**（用户 2026-10-01："除去一切其他来源数据，只从库街区拿"）。
#: 原来的 ``BWIKI_API`` / ``SETS_PAGE`` / ``ECHO_ASK`` / ``CHARACTER_ASK``
#: 已随 bwiki 一起删掉 —— 实测它**没有独占数据**，只会带来文字差异（假报根源）。
KUROBBS_PAGE = "https://api.kurobbs.com/wiki/core/catalogue/item/getPage"
#: 条目**详情**（套装效果原文 / 声骸技能说明都在这里）。
#: ⚠ ``getPage`` 只给列表骨架，文字全在这个接口里 —— 见 :func:`_kuro_entry_detail`。
KUROBBS_ENTRY_DETAIL = (
    "https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail")

SETS_FILE = DATA_ROOT / "wuwa_echo_sets.json"
SKILLS_FILE = DATA_ROOT / "wuwa_echo_skills.json"
CHARACTERS_FILE = DATA_ROOT / "wuwa_characters.json"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
#: 详情要逐条抓，对库街区的礼貌间隔（秒）
DELAY = 0.35


def _ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


# --------------------------------------------------------------------- 远端拉取

@dataclass
class RemoteSnapshot:
    """一次检查拉下来的全部远端数据（没拉到的字段是空容器，不报错）。

    ★ 2026-10-01 起**只从库街区拿**（用户明确要求："除去一切其他来源数据，
    只从库街区拿"）。原来还挂着 bwiki 兜底，但实测它**提供不了任何独占数据**
    （37 套 / 205 声骸 / 60 角色，库街区全都覆盖且有富余），
    留着只会带来两个源的文字差异（那正是"效果更新 30 套"假报的根源）。

    ⚠ 这里**删掉了** ``sets`` / ``echoes_bwiki`` / ``characters_bwiki``
    三个字段 —— 它们曾是 bwiki 的入口。以后要再加数据源，
    请**新加字段**，不要复活这三个（旧的比对逻辑会跟着一起回来）。
    """

    #: ``{套装名: {4: [声骸名...]}}`` —— 库街区（成本键已转 int）
    echoes_kuro: dict[str, dict[int, list[str]]] = field(default_factory=dict)
    #: ``{声骸名: 官方图床 URL}`` —— 库街区
    icon_urls: dict[str, str] = field(default_factory=dict)
    #: ``{角色名: {rarity, element, weapon}}`` —— 库街区 1105
    characters: dict[str, dict] = field(default_factory=dict)
    #: ``{套装名: [{pieces, text}, ...]}`` —— 库街区 1219 详情
    set_effects: dict[str, list[dict]] = field(default_factory=dict)
    #: ``{声骸名: {skill, cooldown}}`` —— 库街区 1107 详情
    echo_skills: dict[str, dict[str, str]] = field(default_factory=dict)


def fetch_remote(log=lambda _msg: None) -> RemoteSnapshot:
    """拉全部数据 —— **只从库街区官方 wiki 拿**。

    ==================  ==========================================
    数据               来源（全部库街区）
    ==================  ==========================================
    声骸列表 + 套装归属   ``getPage`` catalogueId=1107
    套装名单 + 图标       ``getPage`` catalogueId=1219
    角色名单 + 属性       ``getPage`` catalogueId=1105
    角色/武器图标        ``getPage`` catalogueId=1105 / 1106
    套装效果原文         ``getEntryDetail``（1219 条目的详情）
    声骸技能说明         ``getEntryDetail``（1107 条目的详情）
    ==================  ==========================================

    ## 为什么把 bwiki 整个拿掉（2026-10-01）

    用户的要求很直接："**除去一切其他来源数据，只从库街区拿**"。
    我实测确认 bwiki **没有独占数据**：库街区 37 套 / 205 声骸 / 60 角色，
    bwiki 只有 34 / 255 条 / 58，**全是子集**。

    留着它的代价却很实在：两个源的**文字措辞不同**（bwiki 的套装效果多一句
    "延奏技能伤害提升60%"之类），于是比对时永远"有差异"——
    这就是用户看到的「效果更新 30 套」假报。

    ⚠ 顺带把 3 个请求也省了（原来每次检查都要打 bwiki 三趟）。
    """
    snapshot = RemoteSnapshot()
    kuro_sets, icon_urls = _fetch_kurobbs(log)
    snapshot.echoes_kuro = kuro_sets
    snapshot.icon_urls = icon_urls
    snapshot.characters = _fetch_kurobbs_characters(log)
    snapshot.set_effects = _fetch_kurobbs_set_effects(log)
    snapshot.echo_skills = _fetch_kurobbs_echo_skills(
        log, snapshot.echoes_kuro)
    return snapshot


def _get_json(url: str, headers: dict, data: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=45, context=_ssl()) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


#: 库街区 tagTree 的分组名 → 本地字段名。
#: 实测（2026-09-30）1105「共鸣者」有五组：稀有度 / 属性 / 武器 / 实装版本 / 风格定位。
_KURO_CHARACTER_TAGS = {
    "稀有度": "rarity",
    "属性": "element",
    "武器": "weapon",
}

#: 中文数字 → int。⚠ 库街区写的是「**五星**」不是「5星」——
#: 直接 ``replace("星","")`` 会剩下一个「五」，``int()`` 失败变成 0
#: （我第一版就是这么错的：64 个角色「有稀有度」的算出来是 0 个）。
_CHINESE_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                     "六": 6, "七": 7, "八": 8, "九": 9}


#: 库街区的角色名 → 本地用的名字。
#: ★ 漂泊者：库街区把它按「男/女 × 属性」拆成 8 条（``漂泊者-女-导电``），
#: 本地一直用 4 条属性版（``漂泊者·导电``）。不归一化的话，
#: 每更新一次就**多出 8 个假角色**（原有的 4 条又删不掉）。
_KURO_NAME_ALIASES = {
    "漂泊者-男-导电": "漂泊者·导电",
    "漂泊者-女-导电": "漂泊者·导电",
    "漂泊者-男-气动": "漂泊者·气动",
    "漂泊者-女-气动": "漂泊者·气动",
    "漂泊者-男-衍射": "漂泊者·衍射",
    "漂泊者-女-衍射": "漂泊者·衍射",
    "漂泊者-男-湮灭": "漂泊者·湮灭",
    "漂泊者-女-湮灭": "漂泊者·湮灭",
}


def _normalize_character_name(name: str) -> str:
    """库街区角色名 → 本地角色名（见 :data:`_KURO_NAME_ALIASES`）。"""
    return _KURO_NAME_ALIASES.get(name, name)


def _kuro_entry_detail(entry_id: str) -> dict:
    """拉库街区某个条目的**详情**（``getEntryDetail``）。

    ## ★ 为什么需要它（2026-09-30，我判断错过一次）

    我原先以为"套装效果原文 / 声骸技能说明**只有 bwiki 有**" ——
    因为 ``getPage`` 列表接口返回的 ``textList`` 是**空模板**::

        {"content": "", "placeholder": "请输入小标题"}

    用户当场指出："库街区也有套装效果"，并给了页面链接。
    去核之后发现：**文字在详情接口里**，``getPage`` 只是列表页的骨架。

    取法：列表记录的 ``content.linkId``（声骸）或 ``linkUrl``（套装）
    就是详情 id，见 :func:`_entry_id_from_record`。

    ⚠ **不需要 token** —— 实测直接可调（其它几个 wiki 接口会回
    ``code=220 访问令牌不能为空``，这个不会）。

    返回 ``data``（含 ``name`` / ``content.modules``）。
    详情正文是 **HTML 表格**，要 :func:`_html_table_cells` 拆。
    """
    body = urllib.parse.urlencode({"id": str(entry_id)}).encode()
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "wiki_type": "9",
    }
    data = _get_json(KUROBBS_ENTRY_DETAIL, headers, body)
    return data.get("data") or {}


def _html_table_cells(raw: str) -> list[str]:
    """把详情里的 HTML 表格/段落拆成一行行纯文本。

    实测结构是 ``<table><tr><td>名称</td><td>文本</td></tr>…`` ——
    单元格用 ``|`` 分隔、行用换行，这样"套件数"和"效果文字"能对上位置。
    """
    if not raw:
        return []
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"</t[dh]>", "|", text)
    text = re.sub(r"</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = htmllib.unescape(text).replace("\xa0", " ")
    lines: list[str] = []
    for line in text.split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip().strip("|").strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _kuro_component_texts(detail: dict, module_title: str,
                          component_title: str) -> list[str]:
    """取详情里某个「模块 / 组件」的文本行。

    ⚠ **按组件名找，模块名只当"优先匹配"** —— 不强制两个都对上。

    原因：模块名是库街区自己起的（实测是「基本信息」，写错一个字
    —— 比如「基础信息」—— 就一条都取不到，而且**不报错，只是返回空**）。
    组件名（「合鸣效果」/「声骸技能」）才是稳定的那个。

    所以策略是：先找"模块名也对上"的；找不到就退化成**只按组件名**找。
    这样官方改个模块标题也不会把整条链路悄无声息地打断。
    """
    content = detail.get("content") or {}
    modules = content.get("modules", []) or []

    # 第一轮：模块名 + 组件名都要对上（最精确）
    if module_title:
        for module in modules:
            if str(module.get("title") or "") != module_title:
                continue
            for component in module.get("components", []) or []:
                if str(component.get("title") or "") == component_title:
                    return _html_table_cells(component.get("content") or "")

    # 第二轮：只按组件名找（模块标题改过 / 我记错了都能兜住）
    for module in modules:
        for component in module.get("components", []) or []:
            if str(component.get("title") or "") == component_title:
                return _html_table_cells(component.get("content") or "")
    return []


def _entry_id_from_record(record: dict) -> str:
    """列表记录 → 详情 id。

    ⚠ 两个字段名不一样，别只认一个：

    * 声骸（1107）：``content.linkId``
    * 套装（1219）：``content.linkUrl``（``.../mc/item/<id>``）——
      它**没有** ``linkId``（实测：只认 linkId 的话套装一条都取不到）。
    """
    content = record.get("content") or {}
    link_id = str(content.get("linkId") or "").strip()
    if link_id.isdigit():
        return link_id
    link_url = str(content.get("linkUrl") or "").strip()
    if link_url:
        tail = link_url.rstrip("/").split("/")[-1].split("?")[0]
        if tail.isdigit():
            return tail
    return ""


def _parse_set_effects(lines: list[str]) -> list[dict]:
    """把「合鸣效果」那几行文本解析成 ``[{pieces, text}, ...]``。

    实测形状（每个套件占三行）::

        茜染怀想之花
        (2件套)
        治疗效果提升10%。

    ⚠ 按 ``(N件套)`` **定位**、取它后面一行当正文 ——
    比"固定每隔 3 行取一次"稳（有的格式没有名字行）。
    """
    effects: list[dict] = []
    for index, line in enumerate(lines):
        matched = re.match(r"^[（(]?\s*(\d+)\s*件套\s*[)）]?$", line.strip())
        if not matched:
            continue
        pieces = int(matched.group(1))
        text = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if text and not text.startswith("("):
            effects.append({"pieces": pieces, "text": text})
    return effects


def _parse_echo_skill(lines: list[str]) -> dict[str, str]:
    """把声骸详情的「声骸技能」文本解析成 ``{skill, cooldown}``。

    实测形状::

        5★
        技能描述
        使用声骸技能，召唤玉冥蛇，连续发射火球…随后造成64.80%的热熔伤害。
        冷却时间：8秒

    ⚠ **只要 5★ 那一段**：库街区把 2★~5★ 各写一遍（技能数值不同），
    本地一直只存 5 星数据，
    全塞进去会让技能说明变成四段重复文字。
    """
    skill_lines: list[str] = []
    cooldown = ""
    in_five_star = False
    for line in lines:
        star_match = re.match(r"^(\d)★$", line.strip())
        if star_match:
            in_five_star = star_match.group(1) == "5"
            continue
        if not in_five_star:
            continue
        if line.startswith("冷却时间"):
            cooldown = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if line in ("技能描述",):
            continue
        skill_lines.append(line)
    return {"skill": "\n".join(skill_lines).strip(), "cooldown": cooldown}


def _parse_stars(value: str) -> int:
    """把 ``"五星"`` / ``"5星"`` / ``"5"`` 都解析成 ``5``。"""
    text = str(value or "").strip().replace("星", "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    return _CHINESE_NUMERALS.get(text[0], 0)


def _fetch_kurobbs_characters(log) -> dict[str, dict]:
    """拉库街区角色名单（catalogue 1105）—— **角色数据的唯一来源**。

    为什么以它为准（这也是"只从库街区拿"的理由）：

    * **稀有度是结构化的** —— tagTree 里有「稀有度」标签组（值形如「五星」），
      以前靠 bwiki 那份没有这个字段、只能手工补；
    * 角色数更全（实测 60 个）；
    * 官方数据，和游戏内一致。

    ⚠ 数据在 ``content.relateTagIds`` 里，要拿 ``tagTree`` 反查才有名字 ——
    直接读 ``content`` 是读不到"五星/导电/迅刀"的。
    """
    log("拉取角色名单（库街区 1105）…")
    try:
        records, tag_tree = _kuro_page("1105", log)
    except Exception as exc:  # noqa: BLE001 - 一路数据源失败不该让整次检查崩掉
        log(f"  库街区角色名单拉取失败（{exc}）")
        return {}

    # tagTree → {tag_id: (分组, 值)}
    tags: dict[str, tuple[str, str]] = {}
    for group in tag_tree.get("children", []) or []:
        group_name = str(group.get("name", "") or "")
        for child in group.get("children", []) or []:
            node_id = str(child.get("id", "") or "")
            name = str(child.get("name", "") or "").strip()
            if node_id and name:
                tags[node_id] = (group_name, name)

    merged: dict[str, dict] = {}
    for record in records:
        raw_name = str(record.get("name", "")).strip()
        if not raw_name:
            continue
        # ⚠ 名字先归一化，否则漂泊者会每更新一次多出 8 条
        name = _normalize_character_name(raw_name)
        content = record.get("content") or {}
        info: dict = {"rarity": 0, "element": "", "weapon": ""}
        for tag_id in (content.get("relateTagIds") or []):
            group, value = tags.get(str(tag_id), ("", ""))
            field_name = _KURO_CHARACTER_TAGS.get(group)
            if not field_name:
                continue          # 实装版本 / 风格定位：本地用不上
            if field_name == "rarity":
                info["rarity"] = _parse_stars(value)
            else:
                info[field_name] = value
        # 归一化后可能撞车（漂泊者男/女）→ 保留信息更全的那条
        known = merged.get(name)
        if known is None or _info_score(info) > _info_score(known):
            merged[name] = info

    with_rarity = sum(1 for info in merged.values() if info["rarity"])
    log(f"  角色名单：{len(merged)} 个（其中 {with_rarity} 个有稀有度）")
    return merged


def _info_score(info: dict) -> int:
    """一条角色信息"有多全"—— 用来在归一化撞车时挑更好的那条。"""
    return sum(bool(info.get(f)) for f in ("rarity", "element", "weapon"))


def _fetch_kurobbs_set_effects(log) -> dict[str, list[dict]]:
    """套装效果原文（库街区 1219 详情）—— **唯一来源**。

    每个套装一次 ``getEntryDetail``（37 套 = 37 个请求），串行 + 间隔 ——
    比 bwiki 慢，但它是**官方**数据、且和游戏内一致（用户给的就是这个页面）。

    ⚠ 单套失败不影响其余的（可能只是那个条目还没建全）。
    """
    log("拉取套装效果原文（库街区 1219 详情）…")
    try:
        records, _ = _kuro_page("1219", log)
    except Exception as exc:  # noqa: BLE001 - 一路数据源失败不该让整次检查崩掉
        log(f"  库街区套装列表拉取失败（{exc}）")
        return {}

    effects_by_set: dict[str, list[dict]] = {}
    failed = 0
    for record in records:
        name = str(record.get("name", "")).strip()
        if not name:
            continue
        entry_id = _entry_id_from_record(record)
        if not entry_id:
            failed += 1
            continue
        try:
            detail = _kuro_entry_detail(entry_id)
            lines = _kuro_component_texts(detail, "基础信息", "合鸣效果")
            effects = _parse_set_effects(lines)
        except Exception:  # noqa: BLE001 - 单套失败不影响其余
            failed += 1
            continue
        if effects:
            effects_by_set[name] = effects
        time.sleep(DELAY)

    done = sum(1 for e in effects_by_set.values() if e)
    log(f"  套装效果：{done}/{len(records)} 套拿到"
        + (f"（{failed} 套失败）" if failed else ""))
    return effects_by_set


def _fetch_kurobbs_echo_skills(log, echoes_kuro: dict) -> dict[str, dict]:
    """声骸技能说明（库街区 1107 详情）—— **唯一来源**。

    只拉``echoes_kuro`` 里出现过的声骸（205 个），一次一个请求。
    ⚠ 这是一个**慢**操作（两百个请求），所以：
    * 已经在本地的（``wuwa_echo_skills.json``）**不重复拉**；
    * 中途可以 ``log`` 出进度，界面上能看到在动。
    """
    log("拉取声骸技能说明（库街区 1107 详情）…")
    try:
        records, _ = _kuro_page("1107", log)
    except Exception as exc:  # noqa: BLE001
        log(f"  库街区声骸列表拉取失败（{exc}）")
        return {}

    # 只拉**真的还缺**的。
    #
    # ⚠ 两个坑（都是实测踩出来的）：
    #
    # 1. **不能只看"名字在不在"** —— 本地那 187 条大多是
    #    ``{"skill": "", "cooldown": ""}`` 的空壳（只有名字没正文）。
    #    按名字跳过的话一个都补不上（第一次跑就是"0 个拿到"）。
    #    要看**有没有 skill 正文**。
    # 2. **但"没有正文"也不等于"该反复拉"** —— 有些声骸（活动 / 装饰类）
    #    库街区详情里**根本没有「声骸技能」模块**，它们永远不会有正文。
    #    只看正文的话这十几个**每次更新都白拉一遍**（用户 2026-10-01 报：
    #    "这里为什么老是要拉取，我本地本来就是最新的"）。
    #    → 用 ``_skill_missing`` 标记"查过了、确实没有"。
    data = {}
    if SKILLS_FILE.exists():
        try:
            loaded = json.loads(SKILLS_FILE.read_text(encoding="utf-8"))
            data = loaded.get("echoes") if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            data = {}
    data = data if isinstance(data, dict) else {}

    def _has_skill(info) -> bool:
        return isinstance(info, dict) and bool(str(info.get("skill") or "").strip())

    def _checked_no_skill(info) -> bool:
        """查过了、确认这个声骸**确实没有**技能说明（别再拉）。"""
        return isinstance(info, dict) and bool(info.get("_skill_missing"))

    existing = {str(n) for n, i in data.items() if _has_skill(i)}
    known_empty = {str(n) for n, i in data.items() if _checked_no_skill(i)}

    skills: dict[str, dict] = {}
    wanted = [
        r for r in records
        if str(r.get("name", "")).strip()
        and str(r.get("name", "")).strip() not in existing
        and str(r.get("name", "")).strip() not in known_empty
    ]
    skipped = len(known_empty)
    log(f"  需要补 {len(wanted)} 个（已有正文 {len(existing)} 个、"
        f"确认无技能 {skipped} 个，都不重复拉）")

    no_module = 0        # 详情里根本没有「声骸技能」模块
    for index, record in enumerate(wanted, 1):
        name = str(record.get("name", "")).strip()
        entry_id = _entry_id_from_record(record)
        if not entry_id:
            continue
        try:
            detail = _kuro_entry_detail(entry_id)
            lines = _kuro_component_texts(detail, "声骸技能", "声骸技能")
            info = _parse_echo_skill(lines)
        except Exception:  # noqa: BLE001 - 单个失败不影响其余
            continue
        if info.get("skill"):
            skills[name] = info
        else:
            # ⚠ 不是"失败" —— 有些声骸（活动/装饰类）**本来就没有技能**，
            #   库街区详情里连「声骸技能」模块都没有。把它和"抓失败"分开数，
            #   否则日志显示"0 个拿到"会让人以为整条路走不通
            #   （实测 18 个要补的里，**全部**都是这种）。
            no_module += 1
            # ★ 记下"查过了、确实没有" —— 否则**每次更新都会再拉一遍**
            #   （用户 2026-10-01："这里为什么老是要拉取，我本地本来就是最新的"）。
            skills[name] = {"skill": "", "cooldown": "", "_skill_missing": True}
        if index % 20 == 0:
            log(f"  … {index}/{len(wanted)}")
        time.sleep(DELAY)

    log(f"  声骸技能：{len(skills) - no_module} 个拿到"
        + (f"（{no_module} 个确认无技能说明，以后不再重复拉）"
           if no_module else ""))
    return skills


def _kuro_page(catalogue_id: str, log) -> tuple[list[dict], dict]:
    """拉库街区某一类（catalogue）的全部条目。

    返回 ``(records, tagTree)``。``catalogueId`` 映射（2026-09-30 实测）：

    ============  ==================  ====
    catalogueId   内容                条数
    ============  ==================  ====
    1105          共鸣者（角色）        64
    1106          武器                 123
    1107          声骸                 205
    1219          合鸣效果（套装）      37
    ============  ==================  ====

    ⚠ 网页 URL 是 ``?fid=1099&sid=1219`` —— **``sid`` 才是 catalogueId**。
    把 ``fid``（1099）传进来会返回 **0 条且 ``code=200``**（静默空，不报错），
    很容易被误判成"这类没有数据"。
    """
    body = urllib.parse.urlencode(
        {"catalogueId": str(catalogue_id), "page": "1", "limit": "1000"}
    ).encode()
    headers = {
        "User-Agent": _UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "wiki_type": "9",
    }
    data = _get_json(KUROBBS_PAGE, headers, body)
    payload = data.get("data") or {}
    records = (payload.get("results") or {}).get("records") or []
    return list(records), payload.get("tagTree") or {}


def _fetch_kurobbs(log) -> tuple[dict[str, dict[int, list[str]]], dict[str, str]]:
    log("拉取库街区官方数据（getPage）…")
    records, tag_tree = _kuro_page("1107", log)

    # tagTree 是一棵树：根的 children 里有「套装」（34 个子节点才是套装标签）、
    # 「COST」（COST 4/3/1）、「级别」「异相声骸」等分组。
    # **只**把「套装」分组的子节点当套装 —— 不然 COST/级别标签会被当成套装名。
    set_tags: dict[str, str] = {}
    cost_tags: dict[str, int] = {}
    for group in tag_tree.get("children", []) or []:
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

    # ★ 套装图标：**另一个 catalogue**（1219「合鸣效果」）。
    #   ⚠ 声骸那份（1107）里**没有套装图标** —— 它的记录全是声骸，
    #   所以只从 1107 取 icon_urls 的话，套装图标永远是缺的
    #   （用户 2026-09-30 就是发现"明明有图标为什么不加上去"）。
    set_icon_count = 0
    try:
        set_records, _ = _kuro_page("1219", log)
        for record in set_records:
            name = str(record.get("name", "")).strip()
            content = record.get("content") or {}
            url = str(content.get("contentUrl", "") or "").strip()
            # ⚠ 用 setdefault：声骸那份**优先**（名字重名时别被覆盖）
            if name and url.startswith("http") and name not in icon_urls:
                icon_urls[name] = url
                set_icon_count += 1
    except Exception as exc:  # noqa: BLE001 - 套装图标拿不到不该让整次更新失败
        log(f"  套装图标（catalogue 1219）拉取失败：{exc}")

    # ★ 角色 / 武器图标（2026-09-30 用户："这些素材街区也完全可以取到，
    #   同样可以放到资源库"）。抽卡卡片墙要显示头像，靠的就是这两份。
    #   1105 = 共鸣者（角色）、1106 = 武器。
    extra_icons = 0
    for cid, label in (("1105", "角色"), ("1106", "武器")):
        try:
            more, _ = _kuro_page(cid, log)
        except Exception as exc:  # noqa: BLE001 - 拿不到不该让整次更新失败
            log(f"  {label}图标（catalogue {cid}）拉取失败：{exc}")
            continue
        for record in more:
            name = str(record.get("name", "")).strip()
            content = record.get("content") or {}
            url = str(content.get("contentUrl", "") or "").strip()
            if name and url.startswith("http") and name not in icon_urls:
                icon_urls[name] = url
                extra_icons += 1

    log(f"  库街区：{len(records)} 条记录 / {len(icon_urls)} 个图标 URL "
        f"（套装 {set_icon_count} / 角色武器 {extra_icons}）"
        f" / {len(set_tags)} 个套装标签")
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
                "多半是网络不通，或者库街区的接口 / 页面结构变了。\n"
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
    if (not snapshot.set_effects and not snapshot.echoes_kuro
            and not snapshot.characters):
        report.remote_empty = True
        return report
    report.local_empty = not local_by_name

    # 套装效果：跟**数据的实际来源**比 —— 现在只有库街区一路，
    # 所以这里比对的就是写进本地的那一份（不会再出现"跨源比文字"的假报）。
    for name, effects in snapshot.set_effects.items():
        local = local_by_name.get(name)
        if local is None:
            report.new_sets.append(name)
        elif effects and local.get("effects") != effects:
            report.effect_changed.append(name)

    # 套装名单也来自库街区（tagTree 的「套装」分组）—— 效果里没覆盖到的
    # 名字这里再兜一次（比如某套还没建详情页）。
    for name in snapshot.echoes_kuro:
        if name not in local_by_name and name not in report.new_sets:
            report.new_sets.append(name)

    seen_new: set[str] = set()
    for set_name, by_cost in snapshot.echoes_kuro.items():
        for _cost, names in by_cost.items():
            for echo_name in names:
                if echo_name in local_echo_names or echo_name in seen_new:
                    continue
                seen_new.add(echo_name)
                report.new_echoes.append(echo_name)

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

    # 套装效果（库街区 1219 详情）—— **唯一来源**
    for name, effects in snapshot.set_effects.items():
        local = by_name.get(name)
        if local is None:
            by_name[name] = {"name": name, "effects": effects}
            sets.append(by_name[name])
            changed = True
        elif effects and local.get("effects") != effects:
            local["effects"] = effects
            changed = True

    # 套装名单里、效果还没覆盖到的（比如详情页还没建）也要建出来 ——
    # 否则它带的声骸会被 _union_echoes 因为"找不到这个套装"而**整批丢掉**。
    for name in snapshot.echoes_kuro:
        if name not in by_name:
            by_name[name] = {"name": name, "effects": []}
            sets.append(by_name[name])
            changed = True

    # 声骸掉落池（库街区 1107）—— **唯一来源**
    merged_names: set[str] = set()
    for set_name, by_cost in snapshot.echoes_kuro.items():
        # 库街区的 COST 档在 getPage 里拿不到（记录没有 cost 字段），
        # 它的条目按名字并进已有的档位；实在找不到的进 0 桶 → 跳过。
        _union_echoes(by_name, set_name, by_cost)
        merged_names.add(set_name)

    local_sets["_fetched"] = time.strftime("%Y-%m-%d")
    return changed


def _merge_characters_data(local_chars: dict, snapshot: RemoteSnapshot) -> bool:
    """把远端角色名单并进 ``local_chars``（就地修改）。返回是否有变化。

    纯数据操作，不碰磁盘 —— 单测可以直接喂 dict。

    ## 规则（与套装一致的"只增不减"思路）

    * **新角色追加**（这就是"能选到新角色"）；
    * **已有角色不删**：数据源偶尔漏页 / 改名，删掉会让用户已存的配置和任务
      指向一个不存在的角色（``find_character`` 查不到 → 头像消失、名字报错）。
      宁可留着过时的，也不要删；
    * **属性 / 武器**：远端有值且和本地不同就更新（官方修正过的更可信）；
      远端为空时**保留本地的** —— 别拿空串盖掉已有信息；
    * **稀有度**：库街区有结构化的「稀有度」标签，所以正常都有值；
      仍然**只在本地为 0 时**才写入，绝不拿 0 覆盖本地已知的星级。
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

    # 2) 技能说明 + 图标 URL
    skills = json.loads(SKILLS_FILE.read_text(encoding="utf-8")) if SKILLS_FILE.exists() else {}
    skills.setdefault("echoes", {})
    if snapshot.icon_urls:
        skills["icon_urls"] = dict(snapshot.icon_urls)
        skills["_fetched"] = time.strftime("%Y-%m-%d")
        done.append(f"图标 URL 已刷新（{len(snapshot.icon_urls)} 个）")

    # 2a) ★ 声骸技能：**库街区优先**（2026-09-30）
    #     同样是被 getPage 的空 textList 骗过 —— 技能说明在详情接口里。
    if snapshot.echo_skills:
        added = 0
        missing_marked = 0
        for name, info in snapshot.echo_skills.items():
            entry = skills["echoes"].setdefault(name, {})
            # 有值就更新（数值会随版本调整）
            if info.get("skill"):
                if entry.get("skill") != info["skill"]:
                    entry["skill"] = info["skill"]
                    entry["cooldown"] = info.get("cooldown", "")
                    added += 1
                entry.pop("_skill_missing", None)      # 有正文了，标记作废
            elif info.get("_skill_missing") and not str(
                    entry.get("skill") or "").strip():
                # ★ 记下"确认没有技能" —— 下次更新就不再拉它了。
                #   ⚠ 只在本条**也没有正文**时才标记：绝不能用"没查到"
                #   去覆盖已有的正文（那是数据倒退）。
                if not entry.get("_skill_missing"):
                    entry["_skill_missing"] = True
                    missing_marked += 1
        if added:
            done.append(f"声骸技能说明已更新（库街区：{added} 条）")
        if missing_marked:
            done.append(f"确认 {missing_marked} 个声骸没有技能说明"
                        "（记下来，以后不再重复拉取）")

    if skills.get("echoes") or snapshot.icon_urls:
        skills["_source"] = (
            "声骸技能/冷却、icon_urls 全部来自库街区官方 wiki —— "
            "技能走 getEntryDetail 详情的『声骸技能』模块（取 5★ 那一段），"
            "图标走 getPage（catalogueId 1105/1106/1107/1219）。"
        )
        SKILLS_FILE.write_text(
            json.dumps(skills, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    # 就地重载内存数据：资源库页在下次显示时会发现版本号变了并重建，不必重启程序
    game_data.reload_data()

    # 4) ★ **把缺的图标下下来**（2026-09-30 用户："资源库已经更新了，
    #    这图片为什么没自动补上？"）
    #
    #    以前这一步**只写 URL、从不下载** —— 下载一直是
    #    ``tools/fetch_wuwa_assets.py`` 那个手动脚本干的，
    #    于是"数据更新了但图还是空的"。两件事本就不该分开。
    #
    #    ⚠ 必须在 ``reload_data()`` **之后**跑：要按新的声骸/套装/武器名单
    #    去算"缺哪些图"，先下载的话拿到的还是旧名单。
    done.extend(_download_missing_icons(log))

    done.append("已写盘，并已就地刷新内存数据 —— 打开资源库页即可看到最新内容（不用重启）。")
    return done


def _download_missing_icons(log=lambda _m: None) -> list[str]:
    """下载本地缺的图标文件（角色 / 套装 / 声骸 / 武器都要）。

    返回给人看的结果行（放在"更新完成"的报告里）。

    ⚠ **只补缺**：已有的文件绝不覆盖 —— 用户可能自己换过图
    （README 里就是这么教的）。
    """
    from . import assets  # noqa: PLC0415 - 避免和 paths 的初始化顺序纠缠

    wanted: dict[str, str] = {}
    urls = game_data.ICON_URLS

    def want(name: str, relative: str) -> None:
        url = urls.get(name)
        if url:
            wanted.setdefault(relative, url)

    for character in game_data.CHARACTERS:
        want(character.name, character.avatar)
    for echo_set in game_data.ECHO_SETS:
        want(echo_set.name, echo_set.icon)
    for items in game_data.ECHOES_BY_COST.values():
        for echo in items:
            want(echo.name, echo.icon)
    for weapon in game_data.WEAPONS:
        want(weapon.name, weapon.icon)

    root = assets.assets_root()
    missing = [rel for rel in wanted if not (root / rel).exists()]
    if not missing:
        return ["图标已齐全（没有要补的）"]

    log(f"补下 {len(missing)} 张缺的图标（已存在的会跳过）…")
    done_count, failed = assets.ensure_assets(wanted, log=log)
    lines = [f"图标已补齐（新下 {done_count} 张，原本就有 "
             f"{len(wanted) - len(missing)} 张）"]
    if failed:
        # 不把它当失败：少几张图不影响用，但要说清楚
        lines.append(f"⚠ {len(failed)} 张没下下来（其余照常）："
                     + "；".join(failed[:3])
                     + ("…" if len(failed) > 3 else ""))
    return lines


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
