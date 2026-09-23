"""任务流程的「任务类型」——两级下拉的候选表。

一级 = **工具分类**（``ToolCategory``：游戏 / 数据 / 办公）。这里不另起一套枚举，
而是直接复用：以后加一个工具分类，任务类型下拉里就自动多一项，不用两头改。

二级 = **具体产品 / 场景**（游戏 → 鸣潮）。一张表列在下面，支持一个新游戏就加一行。
分类没在表里配二级时，兜底成「通用」这一项，不至于出现空下拉。

一级还有一个 **未分类**（key 是空串）：老流程的 JSON 里没有类型字段，编辑时落到这里；
用户就是不想分类时也能选它，这时二级下拉置灰。

**纯逻辑**：core 层不依赖 Qt（见 ``tests/test_task_types.py``）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .categories import ToolCategory
from .game_client import WUWA, ClientSpec

#: 一级「未分类」的 key —— 用空串，省得再编一个假分类出来
UNCLASSIFIED_KEY = ""
UNCLASSIFIED_NAME = "未分类"


@dataclass(frozen=True)
class SubTypeSpec:
    """二级选项：一个具体产品 / 场景。"""

    key: str
    display_name: str
    #: 这个二级项对应的**游戏客户端判据**（只有具体作品才有，通用 / 非游戏是 None）。
    #: 任务流程的「开始」步拿它去查"客户端在不在运行"。
    client: ClientSpec | None = None


#: 二级候选表。**键 = ToolCategory.key**；
#: 想让某个分类多一个子选项，就在对应那行加一条 SubTypeSpec。
SUB_TYPES: dict[str, tuple[SubTypeSpec, ...]] = {
    # 游戏类：每个具体作品挂上它自己的客户端判据（「开始」步要用）
    ToolCategory.GAME.key: (
        SubTypeSpec("generic", "通用"),
        SubTypeSpec("wuwa", "鸣潮", client=WUWA),
    ),
    ToolCategory.DATA.key: (
        SubTypeSpec("generic", "通用"),
        SubTypeSpec("wuwa", "鸣潮"),
    ),
    ToolCategory.OFFICE.key: (
        SubTypeSpec("generic", "通用"),
    ),
}

#: 分类没配二级清单时的兜底项
DEFAULT_SUB_TYPE = SubTypeSpec("generic", "通用")


def type_options() -> list[tuple[str, str]]:
    """一级候选 ``[(key, 显示名), ...]``；「未分类」排最前（也就是默认值）。"""
    options = [(UNCLASSIFIED_KEY, UNCLASSIFIED_NAME)]
    options += [(item.key, item.display_name) for item in ToolCategory.sorted_all()]
    return options


def sub_specs(type_key: str) -> tuple[SubTypeSpec, ...]:
    """某个一级类型下的二级候选（对象形式，带客户端判据）。

    一级是「未分类」或压根不认识的 key → 空元组（界面上把二级下拉置灰）。
    """
    if not type_key or ToolCategory.from_key(type_key) is None:
        return ()
    return SUB_TYPES.get(type_key) or (DEFAULT_SUB_TYPE,)


def sub_options(type_key: str) -> list[tuple[str, str]]:
    """某个一级类型下的二级候选 ``[(key, 显示名), ...]``。"""
    return [(spec.key, spec.display_name) for spec in sub_specs(type_key)]


def sub_spec(type_key: str, sub_key: str) -> SubTypeSpec | None:
    """按 key 取二级项（连带它的客户端判据）。"""
    for spec in sub_specs(type_key):
        if spec.key == sub_key:
            return spec
    return None


def client_of(type_key: str, sub_key: str) -> ClientSpec | None:
    """这对「任务类型」要检查哪个游戏客户端。

    未分类 / 二级选了「通用」/ 非游戏类 → ``None``，「开始」步据此跳过检查。
    """
    spec = sub_spec(type_key, sub_key)
    return spec.client if spec else None


def normalize(type_key: str, sub_key: str) -> tuple[str, str]:
    """把可能过期 / 手改坏的一对 key 收拾成合法的。

    一级不认识 → 未分类；二级不在该一级的清单里 → 该清单的第一项（通用）。
    """
    pairs = sub_options(type_key)
    if not pairs:
        return UNCLASSIFIED_KEY, ""
    keys = [key for key, _ in pairs]
    return type_key, (sub_key if sub_key in keys else keys[0])


def type_name(type_key: str) -> str:
    for key, name in type_options():
        if key == type_key:
            return name
    return UNCLASSIFIED_NAME


def sub_name(type_key: str, sub_key: str) -> str:
    for key, name in sub_options(type_key):
        if key == sub_key:
            return name
    return ""


def describe(type_key: str, sub_key: str) -> str:
    """一行显示：「游戏 · 鸣潮」。

    未分类时返回**空串** —— 界面上就不显示这个标签了（未分类不该占地方）。
    """
    if not type_key or type_name(type_key) == UNCLASSIFIED_NAME:
        return ""
    name = type_name(type_key)
    sub = sub_name(type_key, sub_key)
    return f"{name} · {sub}" if sub else name
