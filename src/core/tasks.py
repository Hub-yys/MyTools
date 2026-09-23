"""任务流程（把多个工具串成一串按顺序跑）的模型 + 本地 JSON 存储。

**纯逻辑**：不依赖 Qt，可以命令行单测（见 ``tests/test_tasks.py``）。

一条任务流程 = 名字 + 任务类型 + 有序的步骤列表。步骤分两种：

- **工具步骤**：一个 ``src/tools/`` 下注册的工具（比如声骸自动强化）；
- **配置步骤**：一个角色配置（``data/loadouts.json`` 里的 Loadout）。

配置步骤属于**它上面最近的工具步骤** —— 编排界面里把配置拖到某个工具下面
就是这个语义；运行时把配置 id 传给工具（工具用不用是它自己的事）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths
from .task_types import describe as _describe_type
from .task_types import normalize as _normalize_type

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
    key: str = ""                  # 工具的 registry key，或配置的 loadout id
    name: str = ""                 # 显示名（工具名 / 配置的角色名）

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
        return {"type": self.type, "key": self.key, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict) -> "TaskStep":
        step_type = str(data.get("type", STEP_TOOL))
        if step_type not in (STEP_TOOL, STEP_CONFIG, STEP_START, STEP_END):
            step_type = STEP_TOOL
        return cls(type=step_type, key=str(data.get("key", "")), name=str(data.get("name", "")))


@dataclass
class TaskFlow:
    """一条任务流程。"""

    name: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    id: str = ""
    updated_at: str = ""
    #: 任务类型（只是标签，不影响运行）：一级 = 工具分类 key，"" = 未分类；
    #: 二级 = 具体产品 / 场景 key。候选表在 core/task_types.py。
    #: 存 key 不存显示名，以后改名 / 挪分类都不影响老数据。
    type_key: str = ""
    sub_key: str = ""

    def __post_init__(self) -> None:
        # JSON 可能被手改坏、也可能来自还没有类型字段的老版本 —— 统一收拾成合法的一对 key
        self.type_key, self.sub_key = _normalize_type(self.type_key, self.sub_key)

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

        配置属于它上面最近的工具步骤；上面的工具一个都没有时配置会被丢弃
        （编排界面上保存前应该给出提示）。

        返回 ``[{"step": TaskStep(工具), "configs": [TaskStep(配置)...]}, ...]``
        """
        result: list[dict] = []
        for step in self.steps:
            if step.is_tool:
                result.append({"step": step, "configs": []})
            elif step.type == STEP_CONFIG and result:
                result[-1]["configs"].append(step)
            # 其余类型（开始 / 结束标记）不参与绑定
        return result

    # ------------------------------------------------------------ 展示
    def summary(self) -> str:
        """列表行上的步骤摘要：「工具A → 配置x → 工具B」。"""
        return " → ".join(step.name or step.key for step in self.steps) if self.steps else "空流程"

    def type_text(self) -> str:
        """「游戏 · 鸣潮」；未分类时返回空串（界面上就不显示这个标签）。"""
        return _describe_type(self.type_key, self.sub_key)

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type_key": self.type_key,
            "sub_key": self.sub_key,
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
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            type_key=str(data.get("type_key", "")),
            sub_key=str(data.get("sub_key", "")),
            steps=steps,
            updated_at=str(data.get("updated_at", "")),
        )


def bind_configs_to_tools(items: list[TaskStep]) -> list[dict]:
    """编辑器保存时用：把「右侧列表的原始条目」整理成绑定关系。

    与 :meth:`TaskFlow.tool_bindings` 同一套语义，单独拿出来是为了方便单测。
    顶层悬空（前面没有工具）的配置会被丢掉 —— 返回值里不会出现。
    """
    flow = TaskFlow(steps=list(items))
    return flow.tool_bindings()


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
