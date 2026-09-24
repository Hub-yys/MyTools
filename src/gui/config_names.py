"""配置页两类配置的**名字**—— 显示名规则 + 从配置里**实时**取名。

## 为什么要单独一个模块

配置在界面上显示成 **「绯雪-声骸筛选」/「绯雪-声骸强化」**（用户 2026-09-26 要求），
而**任务流程里存的是配置的 key**（筛选配置存 id、强化配置存角色名）。
显示的时候要去配置里读**当前**的名字 —— 配置改了名，任务里那一行也要跟着变
（用户 2026-09-26 明确："每次从配置读最新名字"，不要存快照）。

这套逻辑有 **4 处**要用：

1. 配置页的两种列表行
2. 任务编排的「可用组件」（以及它的搜索）
3. 编排区里已经拖进去的步骤
4. 任务列表行的步骤摘要

所以集中放在这里，别各写一份。

## ⚠ 后缀只加在**显示**上

存盘里存的仍然是**纯角色名**（`EchoProfile.name` / `Loadout.character`）：

* 列表行的头像是拿名字去 ``find_character()`` 查的，带后缀就查不到 → **头像消失**；
* 「角色」下拉里必须显示纯角色名，否则编辑时回填不回去；
* 类型名是**显示常量**（用户已经改过一次），烤进存盘数据会带过期后缀。
"""

from __future__ import annotations

#: 两类配置在界面上的**类型名**（同时也是「新增配置」时下拉里的选项）
TYPE_LOADOUT = "角色声骸筛选"
TYPE_ECHO_PROFILE = "角色声骸强化"
CONFIG_TYPES = (TYPE_LOADOUT, TYPE_ECHO_PROFILE)

#: 步骤里区分"这是哪一类配置"的标记 —— **本体在 core**（工具层也要用，
#: 不该从 gui 引），这里原样转出去给界面用。
from ..core.echo_profile import KIND as KIND_ECHO_PROFILE  # noqa: E402
from ..core.loadout import KIND as KIND_LOADOUT  # noqa: E402

#: 类型名 → 步骤里的标记（反向见 :func:`kind_type_name`）
_KIND_BY_TYPE = {TYPE_LOADOUT: KIND_LOADOUT, TYPE_ECHO_PROFILE: KIND_ECHO_PROFILE}


def type_suffix(type_name: str) -> str:
    """类型名 → 名字后缀（用户 2026-09-26 要求）。

    「角色声骸强化」→ ``-声骸强化``、「角色声骸筛选」→ ``-声骸筛选``。

    做法是**去掉开头的「角色」**，所以以后类型名再改（用户已经改过一次了），
    后缀会自动跟着变，不用再去改一处硬编码。
    """
    name = str(type_name or "").strip()
    if not name:
        return ""
    return "-" + (name[2:] if name.startswith("角色") else name)


def config_display_name(type_name: str, character: str) -> str:
    """列表/标题里显示的配置名 = **角色名 + 类型后缀**（如 ``绯雪-声骸强化``）。"""
    who = str(character or "").strip()
    if not who:
        return "(未填角色)"
    return who + type_suffix(type_name)


def kind_of_type(type_name: str) -> str:
    """类型名 → 步骤里用的 kind 标记。"""
    return _KIND_BY_TYPE.get(str(type_name or "").strip(), KIND_LOADOUT)


def kind_type_name(kind: str) -> str:
    """步骤里的 kind 标记 → 类型名。

    ⚠ 空 kind 当作**筛选配置** —— 老流程里只有这一类，存的时候还没这个字段。
    """
    return TYPE_ECHO_PROFILE if kind == KIND_ECHO_PROFILE else TYPE_LOADOUT


def find_config(kind: str, key: str):
    """按 kind + key 去配置里找那一条。找不到 / 配置文件坏了返回 None。

    * ``KIND_LOADOUT`` → ``LoadoutStore``，key 是 **id**；
    * ``KIND_ECHO_PROFILE`` → ``EchoProfileStore``，key 是**稳定 id**
      （``EchoProfile.id``）。找不到时**再按名字试一次** —— 兼容 2026-09-26
      之前存的流程（那时候强化配置还没有 id，步骤里存的是角色名）。
    """
    key = str(key or "").strip()
    if not key:
        return None
    try:
        if kind == KIND_ECHO_PROFILE:
            from ..core.echo_profile import EchoProfileStore

            store = EchoProfileStore()
            store.load()
            return store.by_id(key) or store.get(key)

        from ..core.loadout import LoadoutStore

        return LoadoutStore().get(key)
    except Exception:  # noqa: BLE001 - 配置文件坏了不该把界面带崩
        return None


def live_config_name(step) -> str:
    """配置步骤**当前**的显示名 —— 去配置里读最新的（用户 2026-09-26 要求）。

    读不到（配置被删了 / 文件坏了）才回退到步骤里存的那份快照，
    并把它标出来，免得看起来像"名字没更新"。
    """
    kind = getattr(step, "config_kind", "") or KIND_LOADOUT
    item = find_config(kind, getattr(step, "key", ""))
    if item is None:
        fallback = str(getattr(step, "name", "") or getattr(step, "key", ""))
        return f"{fallback}（配置已不在）" if fallback else "（配置已不在）"

    if kind == KIND_ECHO_PROFILE:
        return config_display_name(TYPE_ECHO_PROFILE, getattr(item, "name", ""))
    return config_display_name(TYPE_LOADOUT, getattr(item, "character", ""))


def live_config_avatar(step) -> str:
    """配置步骤**当前**的头像相对路径（拿不到就空串 —— 不画占位图）。"""
    kind = getattr(step, "config_kind", "") or KIND_LOADOUT
    item = find_config(kind, getattr(step, "key", ""))
    if item is None:
        return ""
    if kind == KIND_ECHO_PROFILE:
        from ..core import game_data

        info = game_data.find_character(getattr(item, "name", ""))
        return info.avatar if info is not None else ""
    return getattr(item, "display_avatar", "") or ""


def live_flow_summary(flow) -> str:
    """任务行上的步骤摘要 —— 配置那几步用**当前**名字。

    ``TaskFlow.summary()`` 是纯逻辑版本（只能用步骤里存的快照）；
    界面上要用这个，否则配置改了名，任务列表里还是旧名字
    （用户 2026-09-26 明确："每次从配置读最新名字"）。
    """
    parts: list[str] = []
    for step in getattr(flow, "steps", ()) or ():
        if getattr(step, "is_tool", False):
            parts.append(step.name or step.key)
        elif getattr(step, "type", "") == "config":
            parts.append(live_config_name(step))
        else:
            parts.append(step.name or step.key)
    return " → ".join(parts) if parts else "空流程"


# ---------------------------------------------------------------- 任务流程名
#: 任务流程名自动补的后缀（用户 2026-09-28 批注："任务这里也是选角色，
#: 保存时自动加后缀声骸自动强化"）。
#:
#: ⚠ 这是**任务流程**的后缀，和上面 :func:`type_suffix`（配置名的后缀）不是一回事：
#: 配置名是「绯雪-声骸强化」，流程名是「绯雪-声骸自动强化」。两者都由用户
#: 直接指定，改的时候别互相带跑。
FLOW_NAME_SUFFIX = "-声骸自动强化"

#: 老流程名可能**不带连字符** —— 存量数据里就是「绯雪声骸自动强化」这种
#: （用户手打的名字，见 ``data/tasks.json``）。读取时要认出来，否则打开「修改」
#: 会把角色下拉留空、还弹一句"这不是一个角色"的警告。
_FLOW_LEGACY_SUFFIXES = (
    "声骸自动强化",
    "声骸强化",
)


def flow_name_for(character: str) -> str:
    """角色名 → 任务流程名（角色 + 固定后缀）。

    已经是完整流程名（带后缀）时**原样返回**，不重复追加 ——
    编辑老流程时名字是从存盘读回来的完整名，再补一次会变成
    「绯雪-声骸自动强化-声骸自动强化」。
    """
    who = str(character or "").strip()
    if not who:
        return ""
    if _strip_flow_suffix(who) != who:      # 已经带后缀（新式或老式）
        return who
    return who + FLOW_NAME_SUFFIX


def flow_character_of(name: str) -> str:
    """流程名 → 角色名（去掉自动补的后缀）。

    编辑时用它把**角色下拉**回填成当初选的角色。

    两种后缀都认（``-声骸自动强化`` 新式 / ``声骸自动强化`` 老式），
    因为存量流程名大多是**手打的、没有连字符**的版本。

    名字不是这个格式（比如老流程名「日常清声骸」）时**原样返回** ——
    那种名字填不进角色下拉，调用方会另外给出提示，不该在这里猜一个角色出来。
    """
    text = str(name or "").strip()
    return _strip_flow_suffix(text)


def live_flow_avatar(flow) -> str:
    """任务流程行上的**角色头像**相对路径（用户 2026-09-28 要求）。

    流程名 = 角色 + 后缀（见 :func:`flow_name_for`），所以拿名字把后缀剥掉、
    再去 ``game_data.find_character()`` 查那个角色的头像 ——
    和配置页两类配置的行走的是**同一条**查法。

    取不到时返回空串（**不画占位图**）：查不到的原因可能只是资料还没加载、
    或者那个角色在数据集里没头像（实测 ``卡缇希娅`` 就是），
    这时留空比画一个假图更诚实。

    ⚠ 名字不是「角色 + 后缀」格式的老流程（「日常清声骸」）同样查不到 → 留空。
    """
    from ..core import game_data  # noqa: PLC0415 - 只在建行时用

    who = flow_character_of(getattr(flow, "name", ""))
    if not who:
        return ""
    try:
        info = game_data.find_character(who)
    except Exception:  # noqa: BLE001 - 资料没加载好也不该让行建不出来
        return ""
    return info.avatar if info is not None and info.avatar else ""


def _strip_flow_suffix(text: str) -> str:
    """去掉流程名末尾的自动后缀（新式优先，再试老式）。没命中就原样返回。"""
    text = str(text or "").strip()
    if not text:
        return ""
    if text.endswith(FLOW_NAME_SUFFIX):
        return text[: -len(FLOW_NAME_SUFFIX)]
    for legacy in _FLOW_LEGACY_SUFFIXES:
        if text.endswith(legacy) and len(text) > len(legacy):
            return text[: -len(legacy)]
    return text


def is_flow_name_of_character(name: str) -> bool:
    """这个名字看起来像"角色 + 自动后缀"吗（用来决定要不要弹老名字的提示）。

    ⚠ 只判断**形状**，不查数据集 —— 调用方还要自己确认那是不是个真角色
    （见 ``TaskEditorDialog`` 里那条 stale 提示）。
    """
    text = str(name or "").strip()
    if not text:
        return False
    return _strip_flow_suffix(text) != text
