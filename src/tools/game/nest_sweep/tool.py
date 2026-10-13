# -*- coding: utf-8 -*-
"""扫荡残像聚落 —— 工具页：**卡片展示 + 一键全选 + 按顺序刷**。

## 用户要的是什么

原话（2026-10-13）::

    新增"扫荡残像聚落"工具，会展示当前版本所有的残像聚落和梦魇残像，
    以卡片形式展示，可以一键勾选全部，勾选的运行后，根据顺序一个一个去刷

这一页就照着这句话长：**卡片**（一个目标一张）、**全选按钮**、
**运行按钮**（按勾选的顺序跑）。顺序逻辑全在
:mod:`src.core.nest_sweep`（纯逻辑、有单测），本页只管画和接线。

## 两种卡片

====================================  ==========================================
残像聚落 / 梦魇残像                   一张卡 = 一个**能刷的目标**（可勾选）
梦魇残像**声骸**清单                   一张卡 = 一份**资料**（不可勾选）
====================================  ==========================================

⚠ 为什么要分开：游戏指南里**能点的是"聚落"**，不是单个怪。
一个聚落里含多个梦魇残像，所以"勾单个怪"在游戏里**没有对应的操作**。
把 25 个声骸做成可勾的卡片会造出一个点了没用的界面 ——
所以它们列在下面当资料，让用户知道这一趟能刷到哪些声骸。

## ⚠ 卡片不写成"全选后 50 个框一起动会卡"

本项目为列表性能返工过（见 ``pickers.STAT_COLUMNS`` 的说明）。
这里目标数量是**个位到十几个**（不是几百个角色的量级），
所以直接铺卡片就够了，不需要虚拟滚动。真到几十上百条再说。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core import paths
from ....core.categories import ToolCategory
from ....core.nest_sweep import (
    KIND_NAMES,
    SweepTarget,
    build_plan,
    catalog_by_kind,
    load_catalog,
    load_selection,
    save_selection,
    selection_summary,
)
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.widgets import ConfigCard
from ..auto_combat.okww_boot import get_host

#: 页面在引擎里的任务名（要和 ``okww_boot.TASKS`` 的键一致）
TASK_KEY = "扫荡残像聚落"

#: 说明文字颜色（(浅色主题, 深色主题)）—— 与其他页保持同一套灰
MUTED = ("#8A8F98", "#7C7C7C")

#: 卡片网格的列数。目标名字不长（10 字上下），3 列在常见窗口宽度下正好。
CARD_COLUMNS = 3

#: 卡片最小宽度 —— 比这窄的话名字会折成两行，卡片高度就参差不齐了
CARD_MIN_WIDTH = 260


def _muted(label) -> None:
    """把说明文字刷成统一的灰。"""
    try:
        label.setTextColor(*MUTED)
    except Exception:  # noqa: BLE001 - 老版本 qfluentwidgets 没这个接口
        pass


class TargetCard(CardWidget):
    """一个可勾选的目标卡片：**勾选框 + 名称 + 区域/数量**。

    ## 为什么勾选框放**左上角**而不是整卡可点

    整卡可点会和"点卡片看详情"这类未来需求打架，而且误触率高。
    左上角是这类多选列表的惯例位置。
    """

    def __init__(self, target: SweepTarget, checked: bool, on_toggle, parent=None):
        super().__init__(parent)
        self.target = target
        self._on_toggle = on_toggle

        self.setMinimumWidth(CARD_MIN_WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 12)
        box.setSpacing(6)

        # ── 第一行：勾选框 + 名称
        head = QHBoxLayout()
        head.setSpacing(8)
        self.check = CheckBox("", self)
        self.check.setChecked(bool(checked))
        self.check.stateChanged.connect(self._toggled)
        head.addWidget(self.check)

        self.name_label = StrongBodyLabel(target.name, self)
        self.name_label.setWordWrap(True)
        head.addWidget(self.name_label, 1)
        box.addLayout(head)

        # ── 第二行：区域 · 每日数量（有什么写什么，都没有就整行不画）
        details = []
        if target.region:
            details.append(target.region)
        if target.count:
            details.append(f"每日 {target.count}")
        if target.version:
            details.append(f"{target.version} 版本")
        if not target.verified:
            #: ★ 名单没核对过的条目要**明说**，别让它看起来和别的一样可信
            details.append("待核对")
        if details:
            info = CaptionLabel(" · ".join(details), self)
            _muted(info)
            info.setWordWrap(True)
            box.addWidget(info)

        #: 别名（有才显示）—— 让用户知道"任务会拿哪些名字去找这一行"，
        #: 名称对不上时能自己往 aliases 里补
        if target.aliases:
            alias = CaptionLabel("别名：" + " / ".join(target.aliases), self)
            _muted(alias)
            alias.setWordWrap(True)
            box.addWidget(alias)

    def _toggled(self, _state: int) -> None:
        self._on_toggle(self.target.key, self.check.isChecked())

    def set_checked(self, checked: bool, *, silent: bool = False) -> None:
        """外部改勾选。``silent=True`` 时不回调（用于"全选/全不选"批量设置）。"""
        if silent:
            self.check.blockSignals(True)
        self.check.setChecked(bool(checked))
        if silent:
            self.check.blockSignals(False)

    def is_checked(self) -> bool:
        return self.check.isChecked()


class EchoNameCard(CardWidget):
    """梦魇残像**声骸**的资料卡（**不可勾选**）。

    见模块说明：指南里能点的是"聚落"，不是单个怪 ——
    把它做成可勾选会造出一个点了没用的界面。
    """

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(CARD_MIN_WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(0)
        label = BodyLabel(name, self)
        label.setWordWrap(True)
        box.addWidget(label)


class NestSweepWidget(ScrollArea):
    """扫荡残像聚落面板：目标卡片墙 + 全选/反选 + 运行/停止 + 进度。"""

    POLL_MS = 300

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._host = get_host()
        self._targets: tuple[SweepTarget, ...] = ()
        self._cards: dict[str, TargetCard] = {}
        #: 勾选集合（**内存里就是这份**；每次改动立刻落盘）
        self._selected: set[str] = set()

        self.setObjectName("nest_sweep_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget(self)
        page.setObjectName("nest_sweep_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_run_card(page))
        layout.addWidget(self._build_targets_card(page))
        layout.addWidget(self._build_echo_list_card(page))
        layout.addStretch(1)
        self.setWidget(page)

        self._reload()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)
        self._poll()

    # ------------------------------------------------------------------ 清单
    def _reload(self) -> None:
        """读清单 + 已存勾选，重建卡片墙。"""
        self._targets = load_catalog()
        try:
            saved = set(load_selection(self._targets))
        except Exception:  # noqa: BLE001 - 设置读不出来不该挡住页面
            saved = set()
        #: ★ 第一次打开（盘上什么都没存）时**默认全选**。
        #:   用户要的是"一键勾选全部"，那默认就替他勾上 —— 想少刷再取消。
        #:   ⚠ 只有"从来没存过"才默认全选；用户取消过就尊重他的选择，
        #:     否则每次开工具页都把他取消的又勾回来。
        self._selected = saved if self._has_saved_selection() else {
            t.key for t in self._targets}
        self._rebuild_cards()

    def _has_saved_selection(self) -> bool:
        """盘上有没有存过勾选？（用来区分"没存过"和"存了个空"）"""
        try:
            from ....core import tool_settings

            saved = tool_settings.load("nest_sweep")
            return "selected" in saved
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ 构建
    def _build_run_card(self, parent) -> ConfigCard:
        card = ConfigCard(
            "扫荡残像聚落",
            "勾选要刷的目标，点「运行」后**按下面的顺序一个一个刷**"
            "（顺序 = 卡片顺序，也就是清单里的 order）。",
            parent,
        )

        # ── 勾选控制行
        pick_row = QHBoxLayout()
        pick_row.setSpacing(10)
        self.select_all_button = PushButton("全选", card)
        self.select_all_button.clicked.connect(self._select_all)
        pick_row.addWidget(self.select_all_button)

        self.clear_button = PushButton("全不选", card)
        self.clear_button.clicked.connect(self._clear_all)
        pick_row.addWidget(self.clear_button)

        self.invert_button = PushButton("反选", card)
        self.invert_button.clicked.connect(self._invert)
        pick_row.addWidget(self.invert_button)

        pick_row.addSpacing(10)
        self.selection_label = CaptionLabel(selection_summary([], ()), card)
        _muted(self.selection_label)
        pick_row.addWidget(self.selection_label, 1)
        card.body.addLayout(pick_row)

        # ── 运行控制行
        run_row = QHBoxLayout()
        run_row.setSpacing(10)
        self.run_button = PrimaryPushButton("运行", card)
        self.run_button.clicked.connect(self._run)
        run_row.addWidget(self.run_button)

        self.stop_button = PushButton("停止", card)
        self.stop_button.clicked.connect(self._stop)
        run_row.addWidget(self.stop_button)

        self.state_label = CaptionLabel("引擎：未启动 · 点「运行」会先加载引擎再开跑", card)
        _muted(self.state_label)
        run_row.addWidget(self.state_label, 1)
        card.body.addLayout(run_row)

        # ── 进度行（跑起来才有内容）
        self.progress_label = CaptionLabel("", card)
        _muted(self.progress_label)
        self.progress_label.setWordWrap(True)
        card.body.addWidget(self.progress_label)

        return card

    def _build_targets_card(self, parent) -> ConfigCard:
        card = ConfigCard(
            "可以刷的目标",
            "卡片顺序就是刷取顺序。名称和游戏里对不上时，"
            "改 src/core/data/wuwa_sweep_targets.json 的 aliases 即可（两种“象/像”写法已内置）。",
            parent,
        )
        self.targets_host = QWidget(card)
        self.targets_grid = QGridLayout(self.targets_host)
        self.targets_grid.setContentsMargins(0, 4, 0, 0)
        self.targets_grid.setHorizontalSpacing(12)
        self.targets_grid.setVerticalSpacing(12)
        card.add(self.targets_host)
        return card

    def _build_echo_list_card(self, parent) -> ConfigCard:
        """梦魇残像**声骸**清单（资料，不可勾选）。"""
        card = ConfigCard(
            "当前版本的梦魇残像声骸",
            "梦魇残像里能刷到的声骸（资料用 · 不可单独勾选 —— "
            "指南里能点的是“聚落”，一个聚落含多个残像）。",
            parent,
        )
        self.echoes_host = QWidget(card)
        self.echoes_grid = QGridLayout(self.echoes_host)
        self.echoes_grid.setContentsMargins(0, 4, 0, 0)
        self.echoes_grid.setHorizontalSpacing(12)
        self.echoes_grid.setVerticalSpacing(10)
        card.add(self.echoes_host)
        return card

    def _rebuild_cards(self) -> None:
        """按清单重建卡片墙（清空旧卡片）。"""
        self._cards.clear()
        while self.targets_grid.count():
            item = self.targets_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        while self.echoes_grid.count():
            item = self.echoes_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        #: ★ 按**分类**分段，每段前面加一行小标题 —— 用户要"展示所有的
        #:   残像聚落和梦魇残像"，两类混在一起排会看不出分界
        row = 0
        for kind, group in catalog_by_kind(self._targets).items():
            title = StrongBodyLabel(KIND_NAMES.get(kind, kind), self.targets_host)
            self.targets_grid.addWidget(title, row, 0, 1, CARD_COLUMNS)
            row += 1
            for index, target in enumerate(group):
                card = TargetCard(target, target.key in self._selected,
                                  self._on_card_toggle, self.targets_host)
                self.targets_grid.addWidget(card, row + index // CARD_COLUMNS,
                                            index % CARD_COLUMNS)
                self._cards[target.key] = card
            row += (len(group) + CARD_COLUMNS - 1) // CARD_COLUMNS

        names = self._echo_names()
        for index, name in enumerate(names):
            self.echoes_grid.addWidget(EchoNameCard(name, self.echoes_host),
                                       index // CARD_COLUMNS, index % CARD_COLUMNS)

        self._refresh_selection_label()

    def _echo_names(self) -> tuple[str, ...]:
        """从数据文件里读梦魇残像声骸清单（读不到就是空的，不报错）。"""
        try:
            import json

            path = paths.game_data_dir() / "wuwa_sweep_targets.json"
            with path.open(encoding="utf-8") as fh:
                raw = json.load(fh)
            block = raw.get("_nightmare_echoes") or {}
            items = block.get("list") or []
            return tuple(str(x) for x in items if str(x).strip())
        except Exception:  # noqa: BLE001 - 资料读不出来不该让整页崩
            return ()

    # ------------------------------------------------------------------ 勾选
    def _on_card_toggle(self, key: str, checked: bool) -> None:
        """单张卡被勾/取消 —— 立刻落盘（用户切页 / 关程序都不丢）。"""
        if checked:
            self._selected.add(key)
        else:
            self._selected.discard(key)
        self._persist()
        self._refresh_selection_label()

    def _select_all(self) -> None:
        """★ 一键勾选全部（用户明确要的功能）。"""
        self._selected = {t.key for t in self._targets}
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _clear_all(self) -> None:
        self._selected.clear()
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _invert(self) -> None:
        self._selected = {t.key for t in self._targets
                          if t.key not in self._selected}
        self._apply_to_cards()
        self._persist()
        self._refresh_selection_label()

    def _apply_to_cards(self) -> None:
        """把 ``self._selected`` 刷到每个勾选框上。

        ⚠ 必须 ``silent=True``：否则每张卡都会回调一次
        :meth:`_on_card_toggle`，50 张卡就是 50 次存盘 + 50 次刷新
        —— 而且中途的回调会拿**半更新**的集合去写盘。
        """
        for key, card in self._cards.items():
            card.set_checked(key in self._selected, silent=True)

    def _persist(self) -> None:
        try:
            save_selection(self._selected, self._targets)
        except Exception as exc:  # noqa: BLE001 - 存不下来不该挡住操作
            self._toast("勾选存不下来", str(exc), error=True)

    def _refresh_selection_label(self) -> None:
        self.selection_label.setText(
            selection_summary(self._selected, self._targets))
        #: 没勾任何东西时「运行」点不动 —— 免得点了才发现没勾
        self.run_button.setEnabled(bool(self._selected) and not self._running())

    # ------------------------------------------------------------------ 运行
    def _running(self) -> bool:
        return bool(self._host.running_task or self._host.pending_start)

    def _run(self) -> None:
        """把勾选**当场**变成计划，注入任务，启动。"""
        plan = build_plan(self._selected, self._targets)
        if not len(plan):
            self._toast("还没勾选", "先在下面勾选要刷的目标，再点运行")
            return

        def configure(task) -> None:
            #: ★ 把用户**此刻看到的**那份计划交给任务 ——
            #:   任务自己也会读盘兜底（冷启动场景），但界面上这份优先，
            #:   否则"我刚取消了它还是刷了"就会变成很难解释的现象。
            task.sweep_plan = plan

        err = self._host.start_task(TASK_KEY, configure=configure)
        if err:
            self._toast("启动失败", err, error=True)
            return
        self.progress_label.setText(f"已交给引擎：{plan.describe()}")
        self._refresh_selection_label()

    def _stop(self) -> None:
        err = self._host.stop_task()
        if err:
            self._toast("停止失败", err, error=True)
        else:
            self.progress_label.setText("已请求停止")

    # ------------------------------------------------------------------ 轮询
    def _poll(self) -> None:
        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error

        if err and state == "error":
            self.state_label.setText(f"引擎：启动失败 —— {err}（点「运行」可重试）")
        elif state == "booting":
            self.state_label.setText(
                "引擎：正在后台启动 ok-ww…就绪后自动开始（首次加载 OCR 会慢一些）")
        elif state == "running":
            self.state_label.setText(f"引擎：运行中 —— {running}（点「停止」结束）")
        elif state == "ready":
            self.state_label.setText("引擎：就绪 · 点「运行」开始扫荡")
        else:
            self.state_label.setText("引擎：未启动 · 点「运行」会先加载引擎再开跑")

        self.stop_button.setEnabled(bool(running) or bool(pending))
        for button in (self.select_all_button, self.clear_button, self.invert_button):
            button.setEnabled(not running)
        self._refresh_selection_label()

        #: 跑的时候把引擎那边的进度抄过来（任务用 ``info_set`` 写的）
        self._refresh_progress(running)

        self._host.poll_done()

    def _refresh_progress(self, running: str | None) -> None:
        """把 ok-ww 任务里 ``info`` 的进度抄到界面上。"""
        if not running:
            return
        try:
            task = self._host.find_task(TASK_KEY)
            info = getattr(task, "info", None) if task is not None else None
            if not isinstance(info, dict):
                return
            parts = []
            total = info.get("扫荡目标总数")
            done = info.get("扫荡完成数")
            if total:
                parts.append(f"进度 {done or 0}/{total}")
            current = info.get("当前进度")
            if current:
                parts.append(str(current))
            result = info.get("扫荡结果")
            if result:
                parts.append(str(result))
            if parts:
                self.progress_label.setText(" · ".join(parts))
        except Exception:  # noqa: BLE001 - 抄进度失败不该让界面崩
            pass

    # ------------------------------------------------------------------ 杂项
    def _toast(self, title: str, message: str = "", *, error: bool = False) -> None:
        try:
            window = self.window()
            if error:
                InfoBar.error(title, message, duration=6000, parent=window)
            else:
                InfoBar.warning(title, message, duration=6000, parent=window)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.GAME,
    name="扫荡残像聚落",
    description="展示当前版本的残像聚落与梦魇残像，勾选后按顺序逐个扫荡",
    icon_name="GAME",
    coming_soon=False,
)
class NestSweepTool(BaseTool):
    key = "nest_sweep"
    name = "扫荡残像聚落"
    description = "勾选残像聚落 / 梦魇残像，按顺序一个一个自动扫荡"
    version = "0.1.0"
    tags = ("自动", "声骸", "日常")
    coming_soon = False
    #: 可以在任务流程里跑（ok-ww 那边已注册 MyToolsNestSweepTask）
    supports_task_run = True
    icon_path = str(paths.resource_dir("assets", "icons", "nest_sweep.png"))

    def create_widget(self, parent=None):
        return NestSweepWidget(self.meta(), parent)

    # ---------------------------------------------------------------- 任务系统
    def create_task_runner(self, options: dict, log, should_stop):
        """给「任务流程」用：把 ok-ww 宿主上的扫荡任务包装成同步 runner。

        ## ★ 勾选从哪来（没有工具页的时候）

        任务流程跑起来**可能根本没打开过工具页**（用户刚开机就跑流程）。
        所以勾选**不从编排里读**，而是让任务自己读
        ``tool_settings.json`` 里工具页存的那份
        （见 ``MyToolsNestSweepTask._resolve_plan`` 的兜底分支）。

        这样"从任务页跑"和"从工具页点运行"用的就是**同一套勾选** ——
        本项目在声骸强化那边立下的规矩：两条入口的规则必须一致。
        """
        plan = build_plan(load_selection(self._targets_for_log()))
        if not len(plan):
            #: ⚠ 说清楚"为什么没跑"，而不是静默跑一个空任务
            log("⚠ 扫荡残像聚落：一个目标都没勾选 —— 先去工具页勾选，再重跑这条流程")
        else:
            log(f"扫荡残像聚落：{plan.describe()}（顺序按清单）")

        from .runner import NestSweepRunner

        return NestSweepRunner(log=log, should_stop=should_stop)

    @staticmethod
    def _targets_for_log():
        """读清单给日志用；读不出来返回空（日志少一行，不是错误）。"""
        try:
            return load_catalog()
        except Exception:  # noqa: BLE001
            return ()
