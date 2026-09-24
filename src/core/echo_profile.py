"""「角色声骸强化」配置 —— 配置页里的第二类配置。

## 它和「声骸自动强化」工具的设置**互不影响**

| | 存哪 | 谁在用 |
|---|---|---|
| **声骸自动强化工具的设置** | `tool_settings.json` 的 `echo_enhance` 节 | 工具页 + 任务运行时 |
| **「角色声骸强化」配置**（本模块） | `echo_profiles.json` | **暂时没人用，先只存着** |

两边**没有联动**：配置页里改这些配置，不会动到工具页那套；
工具页里改设置，也不会动到这些配置。别把「设为当前」之类的概念加回来 ——
那是"配置即工具规则"的设计，**用户明确否掉了**（2026-09-26）。

将来要做「按角色/按配置选规则」时，再从这里读、显式注入任务即可。

## 名字就是**角色名**（2026-09-26 晚改）

一条配置 = 一个角色。名字**只能从角色列表里选**（``game_data.CHARACTERS``），
不许自由输入，并且**同一个角色只能有一条**。

这么定的原因：行上的头像本来就是拿名字去 ``game_data.find_character()`` 查出来的，
名字一旦是自由文本（比如"绯雪声骸强化配置"），就查不到角色 → **头像凭空消失**。
把名字锁成角色名，头像永远查得到，也就没有"重名"这个伪概念了。

## 没有「默认」那条了

以前第一次运行会种出一条叫「默认」的配置、新增时也从它复制。现在：

* **不再种子**，而且启动时会把遗留的「默认」**清掉**（用户 2026-09-26 明确：
  "去掉种子并删掉已有的「默认」"）；
* 新建时的起点是**出厂默认** —— 也就是打开「声骸自动强化」页**每次看到的那套**。

> ⚠ 别去读 ``tool_settings`` 里存的 ``echo_enhance``。**那个页面每次进入都显示出厂默认**
> （用户早先定的"每次进入都是出厂默认"），它**不显示**存盘值 ——
> 所以"跟工具页一样"＝出厂默认。曾经读存盘，结果弹框一打开就是
> 「双爆不启用 / 可选勾了 2 条 / 有效词条 3」，和用户看到的工具页完全不同。

## 为什么文件放在 tool_settings 的**同目录**

``tests/smoke_gui.py`` / ``check_*_gui.py`` 都靠 monkeypatch
``tool_settings.settings_file`` 做隔离（"跑完断言真实配置没被改动"）。
路径跟着它走 = **自动被那套隔离覆盖**，不用再改一遍那些脚本 ——
不然测试会往真实用户数据里写文件。

**纯逻辑**：core 层，不依赖 Qt，可单独单测。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: 「配置类型」的稳定标识（见 :mod:`src.core.loadout` 里的同名说明）。
KIND = "echo_profile"

#: 文件名（放在 tool_settings.json 旁边）
FILE_NAME = "echo_profiles.json"

#: **遗留**名字：老版本第一次运行自动种出来的那条。
#: 现在不再种，而且会在 :meth:`EchoProfileStore.purge_legacy_default` 里被清掉。
#: 保留这个常量只是为了"认得出来要清谁"。
LEGACY_DEFAULT_NAME = "默认"

#: 名字长度上限。角色名最长 6 个字（如「漂泊者·衍射」），留一倍余量做防御 ——
#: 真出现超长名字（手改过 JSON、或以后数据源变了）也不至于把行撑破。
MAX_NAME_LENGTH = 12


def profiles_file() -> Path:
    """配置文件位置 —— **跟着 tool_settings 走**（见模块文档的隔离说明）。"""
    from . import tool_settings  # noqa: PLC0415 - 避免模块级循环导入

    return tool_settings.settings_file().parent / FILE_NAME


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick(value, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """只留允许的值，其余丢掉（设置改版后的老数据别把界面搞崩）。"""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if str(v) in allowed)


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


@dataclass
class EchoProfile:
    """一套「声骸自动强化」的判定条件。

    ``settings`` 直接存 :class:`~src.tools.game.echo_enhance.settings.EchoSettings`
    ``to_dict()`` 的结果（原样一个 dict）—— core 层不该 import tools 层，
    所以这里不解析它的字段，只在 :meth:`describe` 里读几个已知键。
    """

    name: str
    settings: dict = field(default_factory=dict)
    #: 创建时间（只是给人看的，不参与逻辑）
    created: str = ""
    #: ★ 稳定 id（2026-09-26 加）。
    #: 名字就是角色名、**会变**（用户换角色 = 改名），而任务流程里的步骤要指向
    #: "这一条配置"、并在改名后**跟着变** —— 所以需要一个不随改名变的标识。
    #: 老数据（文件里没有 id）在 :meth:`EchoProfileStore.load` 里补发并落盘，
    #: 之后就一直稳定。
    id: str = ""

    def __post_init__(self) -> None:
        # ⚠ 名字**不再**兜底成「默认」——名字就是角色名，空名字在这里是"坏数据"，
        #   由 store 那边丢掉（见 load()）。以前兜成「默认」会凭空造出一条
        #   不是角色的配置，正是这轮要清掉的东西。
        self.name = str(self.name or "").strip()[:MAX_NAME_LENGTH]
        self.id = str(self.id or "").strip() or uuid.uuid4().hex[:12]
        if not isinstance(self.settings, dict):
            self.settings = {}
        if not self.created:
            self.created = _now()

    # ------------------------------------------------------------------ 展示
    def is_legacy_default(self) -> bool:
        """是不是老版本自动种出来的那条「默认」（启动时要清掉）。"""
        return self.name == LEGACY_DEFAULT_NAME

    def describe(self) -> str:
        """一行摘要 —— 让用户在列表里不点开就知道这套是什么。

        ⚠ 故意**只读已知的几个键**、缺了就用默认值：设置结构以后加了字段，
        这里不会跟着崩（老数据照样能显示）。
        """
        s = self.settings
        core = s.get("core_stats")
        core_text = "、".join(str(x) for x in core) if isinstance(core, list) and core else "（未设）"

        crit = _number(s.get("crit_min"), 7.5)
        crit_dmg = _number(s.get("crit_dmg_min"), 15.0)
        valid = _number(s.get("min_valid_count"), 2)

        parts = [f"核心：{core_text}", f"双爆 ≥{crit:g}/{crit_dmg:g}"]
        if not _flag(s.get("enable_crit_check"), True):
            parts[-1] += "（未启用）"
        parts.append(f"有效词条 ≥{valid:g}")
        if _flag(s.get("enable_max_roll_lock"), True):
            parts.append("满值保护开")
        optional = s.get("optional_stats")
        if isinstance(optional, list) and optional:
            parts.append("可选：" + "、".join(str(x) for x in optional))
        return " · ".join(parts)

    # ------------------------------------------------------------------ 存取
    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "created": self.created,
                "settings": dict(self.settings)}

    @classmethod
    def from_dict(cls, data) -> "EchoProfile":
        """坏数据一律兜住 —— 一条配置读坏了不该让整个列表打不开。

        ⚠ 名字空的**不兜底**（以前会兜成「默认」）—— 名字就是角色名，
        没有名字的条目是坏数据，由 :meth:`EchoProfileStore.load` 丢掉。
        """
        if not isinstance(data, dict):
            return cls(name="")
        return cls(
            name=data.get("name") or "",
            settings=data.get("settings") if isinstance(data.get("settings"), dict) else {},
            created=str(data.get("created") or ""),
            id=str(data.get("id") or ""),
        )


class EchoProfileStore:
    """「角色声骸强化」配置的仓库。全量读 / 全量写（量小，没必要增量）。

    ⚠ **没有"当前使用"这个概念** —— 这些配置和声骸自动强化工具是两回事
    （用户 2026-09-26 明确）。所以这里只有增删改查，没有 active / 设为当前。
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path is not None else None
        self._items: list[EchoProfile] = []

    # ------------------------------------------------------------------ 路径
    @property
    def path(self) -> Path:
        return self._path if self._path is not None else profiles_file()

    # ------------------------------------------------------------------ 读写
    def load(self) -> None:
        path = self.path
        self._items = []
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("角色声骸强化配置读不出来（%s）：%s —— 当作没有", path, exc)
            return
        if not isinstance(raw, dict):
            return

        items = raw.get("profiles")
        if isinstance(items, list):
            # 名字空的条目直接丢 —— 名字就是角色名，没有名字的条目在界面上
            # 既查不到头像、也点不出什么东西（坏数据，不兜底）
            self._items = [p for p in (EchoProfile.from_dict(x) for x in items) if p.name]
            # ★ 老数据（文件里没有 id）在这里被补发了**随机** id —— 必须立刻落盘，
            #   否则每次启动都换一个新的，任务流程里指向它的步骤就永远找不到它。
            #   （一次性迁移：补完存盘，下次 load 时 raw 里就都有 id 了。）
            if self._items and not all(
                    isinstance(x, dict) and x.get("id") for x in items):
                logger.info("给 %d 条「角色声骸强化」配置补发稳定 id 并落盘", len(self._items))
                self.save()

    def save(self) -> None:
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"profiles": [p.to_dict() for p in self._items]}
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            # 写不下来不该让功能不可用（和 tool_settings 一个态度）
            logger.warning("角色声骸强化配置写不进去（%s）：%s", path, exc)

    # ------------------------------------------------------------------ 查询
    def all(self) -> list[EchoProfile]:
        return list(self._items)

    def names(self) -> list[str]:
        return [p.name for p in self._items]

    def __len__(self) -> int:
        return len(self._items)

    def get(self, name: str) -> EchoProfile | None:
        want = str(name or "").strip()
        for p in self._items:
            if p.name == want:
                return p
        return None

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def by_id(self, item_id: str) -> EchoProfile | None:
        """按**稳定 id** 找一条 —— 任务流程里的步骤用 id 指向配置。

        ⚠ 为什么步骤不直接存名字：名字就是角色名、**会变**；
        存名字的话用户一换角色（= 改名），流程里那一步就找不到配置了。
        筛选配置一直是这个道理（它本来就用 id）。
        """
        want = str(item_id or "").strip()
        if not want:
            return None
        for profile in self._items:
            if profile.id == want:
                return profile
        return None

    def occupied_characters(self) -> set[str]:
        """已经被占用的角色名 —— 界面用它把"一角色一条"做成下拉里选不到。"""
        return {p.name for p in self._items}

    # ------------------------------------------------------------------ 改
    def add(self, profile: EchoProfile) -> bool:
        """加一条。**名字（＝角色）重复直接拒绝** —— 一个角色只能有一条配置。"""
        if not profile.name or self.has(profile.name):
            return False
        profile.name = profile.name[:MAX_NAME_LENGTH]
        self._items.append(profile)
        self.save()
        return True

    def update(self, profile: EchoProfile) -> bool:
        for i, p in enumerate(self._items):
            if p.name == profile.name:
                self._items[i] = profile
                self.save()
                return True
        return False

    def rename(self, old: str, new: str) -> bool:
        """改名（＝换角色）。新名字为空 / 已被别的配置占用 → 拒绝。"""
        new = str(new or "").strip()[:MAX_NAME_LENGTH]
        target = self.get(old)
        if target is None or not new or (new != old and self.has(new)):
            return False
        target.name = new
        self.save()
        return True

    def remove(self, name: str) -> bool:
        """删一条。**可以删到一条不剩**（用户 2026-09-26 要求）。

        没有配置时不报错、也不自动补 —— 列表显示空状态，
        新增时起点是**出厂默认**（见 ``EchoProfileDialog``）。
        """
        target = self.get(name)
        if target is None:
            return False
        self._items = [p for p in self._items if p.name != target.name]
        self.save()
        return True

    # ------------------------------------------------------------------ 迁移
    def purge_legacy_default(self) -> bool:
        """把老版本的「默认」那条清掉。**返回是否真删了**。

        老版本第一次运行会自动种一条叫「默认」的配置（它不是角色、没有头像），
        而且新增时从它复制。用户 2026-09-26 明确要求："去掉种子并删掉已有的「默认」"。

        ⚠ 只认**恰好叫「默认」**的那一条。用户要是把某条配置正好起名叫「默认」，
        那也会被删 —— 但现在已经不允许自由起名了（名字只能选角色），
        而「默认」不是角色名，所以只会命中真正的遗留条目。
        """
        before = len(self._items)
        self._items = [p for p in self._items if not p.is_legacy_default()]
        if len(self._items) == before:
            return False
        self.save()
        logger.info("已清理遗留的「%s」配置（%d 条）",
                    LEGACY_DEFAULT_NAME, before - len(self._items))
        return True

    def duplicate(self, source: str, new_name: str) -> bool:
        """复制一条（新增时最常用的一条路）。"""
        src = self.get(source)
        if src is None:
            return False
        return self.add(EchoProfile(name=new_name, settings=dict(src.settings)))
