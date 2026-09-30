"""任务流程（把多个工具串成一串按顺序跑）的模型 + 本地 JSON 存储。

**纯逻辑**：不依赖 Qt，可以命令行单测（见 ``tests/test_tasks.py``）。

一条任务流程 = 名字 + 有序的步骤列表。步骤分两种：

- **工具步骤**：一个 ``src/tools/`` 下注册的工具（比如声骸自动强化）；
- **配置步骤**：一个角色配置（``data/loadouts.json`` / ``data/echo_profiles.json``）。

配置步骤属于**它上面最近的工具步骤** —— 编排界面里把配置拖到某个工具下面
就是这个语义；运行时把配置 id / 名字传给工具（工具用不用是它自己的事）。

## 「任务类型」不再手填（2026-09-26 用户要求）

原来流程上有一对「任务类型」下拉（一级 = 工具分类，二级 = 具体产品），
用户可以自己选。用户要求**去掉那两个下拉** —— 类型本来就是"这条流程属于哪一类"，
看它放了什么工具就知道，不该再让人手填一遍。

→ 改成 :meth:`TaskFlow.derived_type` **从步骤推导**。
存盘里**不再写** ``type_key`` / ``sub_key``（老数据里那两个字段读的时候直接忽略）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths

#: 步骤类型
STEP_TOOL = "tool"
STEP_CONFIG = "config"
#: 流程的起点 / 终点标记（不执行任何东西，只给编排一个"从头到尾"的视觉结构）
STEP_START = "start"
STEP_END = "end"

#: 默认存放位置：用户数据目录下的 tasks.json（见 core/paths.py）
DEFAULT_STORE_PATH = paths.user_data_dir() / "tasks.json"


@dataclass
class TaskStep:
    """流程里的一步。"""

    type: str                      # STEP_TOOL / STEP_CONFIG
    key: str = ""                  # 工具的 registry key，或配置的 id / 名字
    name: str = ""                 # 显示名（工具名 / 配置的角色名）
    #: 配置步骤的**类型**（``"loadout"`` / ``"echo_profile"``）——
    #: 两类配置的 key 长得不一样（一个 id、一个角色名），光看 key 分不出是哪一类。
    #: 工具步骤这个字段为空。
    config_kind: str = ""

    @property
    def is_tool(self) -> bool:
        return self.type == STEP_TOOL

    @property
    def is_marker(self) -> bool:
        """开始 / 结束这类纯标记步骤（不执行、不参与配置绑定）。"""
        return self.type in (STEP_START, STEP_END)

    def describe(self) -> str:
        prefix = "工具" if self.is_tool else "配置"
        return f"[{prefix}] {self.name or self.key}"

    def to_dict(self) -> dict:
        return {"type": self.type, "key": self.key, "name": self.name,
                "config_kind": self.config_kind}

    @classmethod
    def from_dict(cls, data: dict) -> "TaskStep":
        step_type = str(data.get("type", STEP_TOOL))
        if step_type not in (STEP_TOOL, STEP_CONFIG, STEP_START, STEP_END):
            step_type = STEP_TOOL
        return cls(type=step_type, key=str(data.get("key", "")),
                   name=str(data.get("name", "")),
                   config_kind=str(data.get("config_kind", "")))


@dataclass
class TaskFlow:
    """一条任务流程。"""

    name: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    id: str = ""
    updated_at: str = ""

    # ------------------------------------------------------------ 校验
    def validate(self) -> list[str]:
        """返回错误说明列表（空列表 = 通过）。"""
        errors: list[str] = []
        if not self.name.strip():
            errors.append("任务名称为必填项")
        if not self.steps:
            errors.append("流程里至少要有一步")
        elif not any(step.is_tool for step in self.steps):
            errors.append("流程里至少要有一个工具步骤")
        return errors

    # ------------------------------------------------------------ 配置绑定
    def tool_bindings(self) -> list[dict]:
        """把步骤列表整理成「工具 + 它挂的配置」。

        ## 绑定规则（2026-09-27 修）

        1. **优先绑给上面最近的工具**（"工具后面跟的配置归它"）—— 旧行为，不变；
        2. 上面**没有**工具的配置（悬空配置），**改绑给下面最近的工具**。

        第 2 条是这次修的 bug。用户把配置放在工具**前面**：

            开始 → 配置「绯雪-声骸筛选」 → 配置「绯雪-声骸强化」 → 工具「声骸自动强化」

        读起来就是"先筛选、再强化"，非常自然；但旧写法
        （``elif step.type == STEP_CONFIG and result: result[-1][...]``）
        因为那时 ``result`` 还是空的，就把它们**直接丢掉**了 ——
        结果是"配置明明挂着，运行时却没生效"，用户报「进去就直接声骸强化、根本没筛选」。

        ⚠ 这条路径**不报错**（只在编排界面保存时给一句很容易看漏的提示），
        属于**静默失效**，最难查。这种"看着完全合理的流程却不生效"
        比报错糟糕得多。

        返回 ``[{"step": TaskStep(工具), "configs": [TaskStep(配置)...]}, ...]``
        """
        #: 流程下标 → 它是第几个工具步骤
        tool_index: dict[int, int] = {}
        count = 0
        for i, step in enumerate(self.steps):
            if step.is_tool:
                tool_index[i] = count
                count += 1

        result: list[dict] = [{"step": s, "configs": []}
                              for s in self.steps if s.is_tool]
        for i, step in enumerate(self.steps):
            if step.type != STEP_CONFIG:
                continue
            above = [j for j in tool_index if j < i]
            below = [j for j in tool_index if j > i]
            # ① 上面最近的工具；② 没有就找下面最近的
            target = max(above) if above else (min(below) if below else None)
            if target is not None:
                result[tool_index[target]]["configs"].append(step)
            # 上下都没有工具 → 丢弃；validate() 会拦"流程里至少要有一个工具步骤"
        return result

    # ------------------------------------------------------------ 展示
    def summary(self) -> str:
        """列表行上的步骤摘要：「工具A → 配置x → 工具B」。"""
        return " → ".join(step.name or step.key for step in self.steps) if self.steps else "空流程"

    def type_text(self) -> str:
        """「游戏 · 鸣潮」；推导不出类型时返回空串（界面上就不显示这个标签）。"""
        from .task_types import describe as _describe_type

        return _describe_type(*self.derived_type())

    # ------------------------------------------------------------ 类型推导
    def tool_steps(self) -> list[TaskStep]:
        return [step for step in self.steps if step.is_tool]

    def derived_type(self) -> tuple[str, str]:
        """流程的「任务类型」—— **从步骤推导**，不再手填（2026-09-26 用户要求）。

        用户去掉了编排界面上的两级下拉：类型本来就是"这条流程属于哪一类"，
        看它放了什么工具就知道，不该再让人手填一遍。

        推导规则（简单可预期）：

        * 没有任何工具步骤 → ``("", "")``（未分类）；
        * 有**游戏类**工具 → ``("game", "wuwa")`` —— 本工具目前只支持鸣潮，
          所以具体游戏直接定成 ``wuwa``，于是「开始」步能真的去查客户端；
        * 否则取**第一个工具步骤**的分类，二级用「通用」。

        ⚠ 分类取自 ``ToolRegistry`` 里工具**自己声明**的 ``category``
        （声明式，不去实例化探测 —— 实例化有副作用）。
        """
        from .categories import ToolCategory

        metas = []
        for step in self.tool_steps():
            meta = _tool_meta(step.key)
            if meta is not None:
                metas.append(meta)
        if not metas:
            return "", ""

        if any(m.category == ToolCategory.GAME for m in metas):
            # 具体游戏：现在只有鸣潮一个客户端判据，直接用它
            return ToolCategory.GAME.key, "wuwa"
        return metas[0].category.key, "generic"

    def client_spec(self):
        """「开始」步要检查哪个游戏客户端（不检查时返回 None）。"""
        from .task_types import client_of

        return client_of(*self.derived_type())

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        # ⚠ 不再写 type_key / sub_key —— 类型已经是推导出来的，存了反而会过期
        return {
            "id": self.id,
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskFlow":
        steps = [
            TaskStep.from_dict(item)
            for item in (data.get("steps") or [])
            if isinstance(item, dict)
        ]
        # 老数据里的 type_key / sub_key 直接忽略（改推导了，留着会误导）
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            steps=steps,
            updated_at=str(data.get("updated_at", "")),
        )


def _tool_meta(key: str):
    """按 key 取工具元数据；注册表还没发现工具 / key 已失效时返回 None。"""
    try:
        from .registry import ToolRegistry

        return ToolRegistry.get_meta(key)
    except Exception:  # noqa: BLE001 - 推导类型不该把整条流程读崩
        return None


def bind_configs_to_tools(items: list[TaskStep]) -> list[dict]:
    """编辑器保存时用：把「右侧列表的原始条目」整理成绑定关系。

    与 :meth:`TaskFlow.tool_bindings` 同一套语义，单独拿出来是为了方便单测。
    顶层悬空（前面没有工具）的配置会被丢掉 —— 返回值里不会出现。
    """
    flow = TaskFlow(steps=list(items))
    return flow.tool_bindings()


def flows_using_config(flows, kind: str, *keys) -> list[str]:
    """哪些任务流程**引用了**这条配置？返回流程名列表（给界面提示用）。

    用户 2026-09-28 要求："已完成任务流程里使用的配置，不能直接删除配置，
    需要先删除任务，才能删除配置"。

    ## 为什么必须拦

    配置步骤靠 ``key`` 指向配置（筛选配置用 ``Loadout.id``、强化配置用
    ``EchoProfile.id``）。配置一删，流程里那一步就变成**悬空引用**：
    界面上那一步会显示成「xxx（配置已不在）」，而**运行时工具拿不到配置**，
    等于那一步静默失效 —— 用户看到的是"流程明明还在，却不筛选了"。
    这正是 ``live_config_name`` 里那段"（配置已不在）"的来源。

    所以要在这里拦住，让用户**先删流程、再删配置**，把因果关系摆到明面上。

    ## 匹配规则

    ``keys`` 传这条配置的**所有**可用于指向它的键，因为历史上存过不同形式：

    * **id**：稳定 id（现行）；
    * **名字**：2026-09-26 之前强化配置还没有 id，步骤里存的是角色名
      （见 ``config_names.find_config`` 的兼容说明）——
      所以名字也要一起比，否则老流程引用会被漏掉、照样能删出事。

    ``kind`` 为空串时**任意类型都算**（防御性：极老的步骤没有 config_kind 字段，
    这种步骤按 ``KIND_LOADOUT`` 处理，见 ``kind_type_name``）；调用方一般会传准。

    名字为空 / 没被任何流程引用 → 返回空列表（可以删）。
    """
    wanted = {str(k).strip() for k in keys if str(k or "").strip()}
    if not wanted:
        return []
    names: list[str] = []
    for flow in flows or ():
        for step in getattr(flow, "steps", ()) or ():
            if getattr(step, "type", "") != STEP_CONFIG:
                continue
            if kind and (getattr(step, "config_kind", "") or "") not in ("", kind):
                continue
            if str(getattr(step, "key", "") or "").strip() in wanted:
                names.append(getattr(flow, "name", "") or "（未命名）")
                break                      # 同一条流程只报一次
    return names


class TaskStore:
    """任务流程的本地存储（一个 JSON 文件装全部）。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH
        self._items: list[TaskFlow] = []
        self.load()

    # ------------------------------------------------------------ 读写
    def load(self) -> None:
        self._items = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        records = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            return
        for record in records:
            if isinstance(record, dict):
                self._items.append(TaskFlow.from_dict(record))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "tasks": [item.to_dict() for item in self._items]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------ 查询
    def all(self) -> list[TaskFlow]:
        """按更新时间倒序（最近改的排前面）。"""
        return sorted(self._items, key=lambda x: x.updated_at, reverse=True)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, flow_id: str) -> TaskFlow | None:
        for item in self._items:
            if item.id == flow_id:
                return item
        return None

    # ------------------------------------------------------------ 增删改
    def add(self, flow: TaskFlow) -> TaskFlow:
        if not flow.id:
            flow.id = uuid.uuid4().hex[:12]
        flow.updated_at = _now()
        self._items.append(flow)
        self.save()
        return flow

    def update(self, flow: TaskFlow) -> bool:
        for index, item in enumerate(self._items):
            if item.id == flow.id:
                flow.updated_at = _now()
                self._items[index] = flow
                self.save()
                return True
        return False

    def remove(self, flow_id: str) -> bool:
        for index, item in enumerate(self._items):
            if item.id == flow_id:
                del self._items[index]
                self.save()
                return True
        return False


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
