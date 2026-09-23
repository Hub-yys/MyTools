"""工具分类。

core 层不放 Qt 依赖，所以图标只存 *名字*，由 gui 层解析成 FluentIcon。
新增一个分类 = 加一个枚举成员，主页会自动多出一个分组。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class CategorySpec:
    """一个分类的描述信息。"""

    key: str
    display_name: str
    icon_name: str
    order: int
    note: str = ""


class ToolCategory(Enum):
    """工具分类枚举。value 是 CategorySpec。"""

    GAME = CategorySpec(
        key="game",
        display_name="游戏",
        icon_name="GAME",
        order=10,
        note="游戏辅助、脚本、存档处理等",
    )
    DATA = CategorySpec(
        key="data",
        display_name="数据",
        icon_name="DATABASE",
        order=15,
        note="数据更新、资料整理等",
    )
    OFFICE = CategorySpec(
        key="office",
        display_name="办公",
        icon_name="DOCUMENT",
        order=20,
        note="文档批处理、表格整理、文件改名等",
    )

    @property
    def spec(self) -> CategorySpec:
        return self.value

    @property
    def key(self) -> str:
        return self.value.key

    @property
    def display_name(self) -> str:
        return self.value.display_name

    @classmethod
    def from_key(cls, key: str) -> "ToolCategory | None":
        for item in cls:
            if item.key == key:
                return item
        return None

    @classmethod
    def sorted_all(cls) -> list["ToolCategory"]:
        return sorted(cls, key=lambda c: c.spec.order)


ALL_CATEGORIES = ToolCategory.sorted_all()
