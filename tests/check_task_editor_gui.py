# -*- coding: utf-8 -*-
"""任务编排弹框的检查（不需要游戏）。

    QT_QPA_PLATFORM=windows ./.venv/Scripts/python.exe tests/check_task_editor_gui.py

盯四件事（都是用户 2026-09-26 提的，或者实现时踩到的）：

1. **没有「任务类型」那一对下拉了** —— 类型改成从步骤推导；
2. **可用组件列出全部工具 + 两类配置**（"可以搜索所有的配置、工具"）；
3. **搜索要真能搜到** —— 按配置页显示的名字（「筛选」「强化」）和工具名（「调频」）
   都能搜到；**而且搜一个不存在的词必须 0 项**（防止匹配退化成一律命中）。
4. **配置项的名字跟着配置走** —— 显示名和配置页一致（带类型后缀），
   配置改名之后，已经拖进流程里的那一步文字也要跟着变。

⚠ 隔离：``tool_settings`` 指到临时目录（强化配置跟着它走）；
``loadouts.json`` **没法隔离**（`LoadoutStore` 用模块级常量路径）——
所以这个脚本**只读**它，跑完断言真实文件没变。
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REAL_SETTINGS = ROOT / "data" / "tool_settings.json"
REAL_LOADOUTS = ROOT / "data" / "loadouts.json"

CHECKS: list[tuple[str, bool, str]] = []
#: 报告已经打过了吗（见下面的 atexit 安全网）
_REPORTED = False


def print_report() -> int:
    """打印所有检查项 + 统计。返回进程退出码。

    ⚠ 用 ``atexit`` 兜底调用：这个脚本是**最后统一打印**的，
    中途一旦抛异常就**什么都打印不出来**（实测：一个未捕获的
    ``AttributeError`` 让 39 项检查全成了哑巴）。失败必须看得见。
    """
    global _REPORTED
    _REPORTED = True
    if not CHECKS:
        print("（没有收到任何检查项 —— 脚本在开始检查前就挂了）")
        return 1
    width = max(len(name) for name, _, _ in CHECKS)
    for name, ok, detail in CHECKS:
        print("%-*s %s%s" % (width, name, "PASS" if ok else "FAIL",
                             ("  " + detail) if detail else ""))
    failed = [c for c in CHECKS if not c[1]]
    print("\n%d 项检查，%d 项失败" % (len(CHECKS), len(failed)))
    return 1 if failed else 0


def _atexit_report() -> None:
    if not _REPORTED:
        import traceback

        print("\n⚠ 脚本中途异常退出，下面是**已经收到的**检查项：")
        traceback.print_exc()
        print_report()


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def _digest(path: pathlib.Path) -> str | None:
    return hashlib.md5(path.read_bytes()).hexdigest() if path.is_file() else None


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from src.core import tool_settings
    from src.core.echo_profile import EchoProfile, EchoProfileStore
    from src.core.registry import ToolRegistry
    from src.tools import discover_tools

    discover_tools()

    # ★ 隔离（早于构造任何页面）
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="task-editor-check-"))
    tool_settings.settings_file = lambda: tmp_dir / "tool_settings.json"
    settings_before = _digest(REAL_SETTINGS)
    loadouts_before = _digest(REAL_LOADOUTS)

    from src.gui.config_names import (
        KIND_ECHO_PROFILE,
        KIND_LOADOUT,
        TYPE_ECHO_PROFILE,
        TYPE_LOADOUT,
        config_display_name,
        live_config_name,
    )
    from src.gui.main_window import MainWindow
    from src.gui.task_editor_dialog import TaskEditorDialog
    from src.core.tasks import (
        STEP_CONFIG,
        STEP_END,
        STEP_START,
        STEP_TOOL,
        TaskFlow,
        TaskStep,
    )

    # 造两条强化配置（隔离目录里），供编排界面列出来
    store = EchoProfileStore()
    store.load()
    for name in ("绯雪", "漂泊者·衍射"):
        if store.get(name) is None:
            store.add(EchoProfile(name=name, settings={"core_stats": ["暴击", "暴击伤害"]}))

    win = MainWindow()
    win.resize(1080, 700)
    win.show()
    for _ in range(6):
        app.processEvents()

    dlg = TaskEditorDialog(win)
    dlg.show()
    for _ in range(10):
        app.processEvents()

    def palette() -> list[str]:
        return [dlg.palette_list.item(i).text() for i in range(dlg.palette_list.count())]

    def search(kw: str) -> list[str]:
        dlg.search_edit.setText(kw)
        app.processEvents()
        return palette()

    # ---- ① 任务类型那对下拉已经没了 ----
    for attr in ("type_combo", "sub_combo"):
        check(f"弹框里没有 {attr}（任务类型已改成从步骤推导）", not hasattr(dlg, attr))
    from qfluentwidgets import StrongBodyLabel
    check("弹框上找不到「任务类型」这几个字",
          not any("任务类型" in w.text() for w in dlg.findChildren(StrongBodyLabel)),
          str([w.text() for w in dlg.findChildren(StrongBodyLabel)]))

    # ---- ② 列出全部工具 + 两类配置 ----
    all_tools = [m.name for m in ToolRegistry.all_metas()]
    shown = palette()
    missing_tools = [n for n in all_tools if f"[工具] {n}" not in shown]
    check("★ 可用组件列出**全部**工具（原来只有 1 个）", not missing_tools,
          f"少了 {missing_tools}；实际 {len(shown)} 项")
    check("★ 可用组件列出**两类**配置（含「角色声骸强化」）",
          any("声骸强化" in t for t in shown) and any("声骸筛选" in t for t in shown),
          str(shown))
    check("检查前置：至少有一条筛选配置（否则上面那条是空转）",
          any(t.startswith("[配置] ") and "声骸筛选" in t for t in shown), str(shown))
    check("检查前置：至少有一条强化配置（否则上面那条是空转）",
          any(t.startswith("[配置] ") and "声骸强化" in t for t in shown), str(shown))

    # ---- ③ 搜索：要搜得到，而且不能"一律命中" ----
    check("搜「调频」能搜到那个工具", search("调频") == ["[工具] 声骸批量调频"],
          str(search("调频")))
    check("搜「战斗」能搜到 4C 自动战斗", search("战斗") == ["[工具] 4C 自动战斗"],
          str(search("战斗")))
    got = search("筛选")
    check("★ 搜「筛选」只出筛选配置（按配置页的名字就能搜到）",
          bool(got) and all(t.endswith("声骸筛选") and t.startswith("[配置]") for t in got),
          str(got))
    got = search("强化")
    check("★ 搜「强化」出强化工具 + 强化配置",
          "[工具] 声骸自动强化" in got and any(t.endswith("声骸强化") for t in got),
          str(got))
    got = search("绯雪")
    check("★ 搜角色名能同时带出两类的配置",
          len(got) == 2 and all("绯雪" in t for t in got), str(got))
    # ★ 这条是防"匹配退化成一律命中"的 —— 实测踩过：
    #   配置循环的变量覆盖了闭包里的搜索关键词，导致搜什么都把配置全列出来。
    check("★ 搜一个不存在的词 → 0 项（防止匹配一律命中）",
          search("zzz这个词不存在zzz") == [], str(search("zzz这个词不存在zzz")))
    dlg.search_edit.setText("")
    app.processEvents()

    # ---- ④ 配置项名字跟配置页一致 ----
    check("配置项用的是配置页那套带后缀的显示名",
          config_display_name(TYPE_LOADOUT, "绯雪") == "绯雪-声骸筛选"
          and config_display_name(TYPE_ECHO_PROFILE, "绯雪") == "绯雪-声骸强化")

    # ---- ⑤ 已存流程里的那一步要跟着配置改名变 ----
    # ★ 步骤存的是**稳定 id**，不是角色名 —— 名字就是角色名、会变，
    #   存名字的话用户换个角色，流程里那一步就找不到配置了（实测踩过）。
    profile = store.get("绯雪")
    check("检查前置：拿到了「绯雪」那条配置和它的稳定 id",
          profile is not None and bool(profile.id), str(profile))
    step = TaskStep(type=STEP_CONFIG, key=profile.id, name="绯雪",
                    config_kind=KIND_ECHO_PROFILE)
    check("★ 配置步骤的显示名来自配置（当前 = 绯雪-声骸强化）",
          live_config_name(step) == "绯雪-声骸强化", live_config_name(step))
    store.rename("绯雪", "清宵")     # 换个角色名（= 改名）
    check("★ 配置改名后，流程里那一步的文字跟着变",
          live_config_name(step) == "清宵-声骸强化", live_config_name(step))
    # 用不存在的 key：不能炸，而且要标出来
    gone = TaskStep(type=STEP_CONFIG, key="早就删了的配置", name="老名字",
                    config_kind=KIND_LOADOUT)
    text = live_config_name(gone)
    check("配置被删掉时标出「已不在」而不是静默显示旧名",
          "已不在" in text, text)

    # ---- ⑥ id 必须**落盘**（否则每次启动换一个，流程就永远找不到） ----
    raw_after = (tmp_dir / "echo_profiles.json").read_text(encoding="utf-8")
    check("★ 稳定 id 已经落盘（不是每次启动现编一个）",
          '"id"' in raw_after, raw_after[:120])
    reloaded = EchoProfileStore()
    reloaded.load()
    check("★ 重新读一遍，id 不变（真稳定）",
          reloaded.get("清宵") is not None
          and reloaded.get("清宵").id == step.key, str(reloaded.get("清宵")))

    win.close_without_prompt()

    # ---- ⑦ 编排区：可在**中间自由插入**（用户 2026-09-26 要求） ----
    # Qt 在 IconMode 下**不按落点插** —— 拖到第 1、2 项之间会追加到末尾（实测过），
    # 所以 `FlowListWidget.dropEvent` 自己算插入位置。这几条就是钉住它。
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QDropEvent

    fl = dlg.flow_list

    def flow_order() -> list[str]:
        return [fl.item(i).text() for i in range(fl.count())]

    def drop_at(text: str, pos=None) -> None:
        item = next(dlg.palette_list.item(i)
                    for i in range(dlg.palette_list.count())
                    if dlg.palette_list.item(i).text() == text)
        pos = pos if pos is not None else fl.viewport().rect().center()
        fl.dropEvent(QDropEvent(pos, Qt.DropAction.CopyAction,
                                dlg.palette_list.mimeData([item]),
                                Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier))
        app.processEvents()

    def between(i: int) -> QPoint:
        """第 i 项和第 i+1 项之间的落点。"""
        left = fl.visualItemRect(fl.item(i))
        right = fl.visualItemRect(fl.item(i + 1))
        return QPoint((left.right() + right.left()) // 2, left.center().y())

    before_palette = dlg.palette_list.count()
    for text in ("[开始] 开始", "[工具] 声骸自动强化", "[配置] 绯雪-声骸强化"):
        drop_at(text)
    check("检查前置：编排区已经塞进 3 项（否则下面是空转）",
          len(flow_order()) == 3, str(flow_order()))

    drop_at("[工具] 4C 自动战斗", between(0))          # 插到 0、1 之间
    got = flow_order()
    check("★ 拖到中间 → **插在中间**（不是追加到末尾）",
          len(got) == 4 and "4C" in got[1], str(got))
    check("★ 插入没有顶掉原来那一项（数量 = 4）", len(got) == 4, str(got))

    drop_at("[工具] 资源库更新", between(2))           # 再插到 2、3 之间
    got = flow_order()
    check("★ 再插一次也在中间（连插位置都要对）",
          len(got) == 5 and "资源库" in got[3], str(got))
    check("★ 从组件区拖进来是**复制**（组件区不该少项）",
          dlg.palette_list.count() == before_palette,
          f"拖前 {before_palette} → 现在 {dlg.palette_list.count()}")

    check("落点在某一项左半边 → 插到它前面",
          fl.insert_index_at(QPoint(fl.visualItemRect(fl.item(2)).left() + 2, 10)) == 2)
    check("落点在某一项右半边 → 插到它后面",
          fl.insert_index_at(QPoint(fl.visualItemRect(fl.item(2)).right() - 2, 10)) == 3)
    check("落点在最后一项右边 → 排到末尾",
          fl.insert_index_at(QPoint(fl.visualItemRect(fl.item(4)).right() + 50, 10)) == 5)

    # 内部排序：拖到哪儿就排到哪儿
    fl.item(0).setSelected(True)
    fl.move_selected_to(fl.count())
    check("★ 编排区内部排序：拖到末尾就排到最后",
          flow_order()[-1].startswith("[开始]"), str(flow_order()))

    # ---- ⑨ 「详情」要显示任务的**流程图**（用户 2026-09-26） ----
    # 走**真实路径**：调 TaskRowCard._show_detail（它内部会 exec()，
    # 所以把 exec 换成"把弹框抓出来、不发消息循环"）。
    from qfluentwidgets import MessageBoxBase

    from src.gui.task_editor_dialog import TILE_SIZE, FlowPreview, preview_width_for
    from src.gui.tasks_interface import TaskRowCard

    # ⚠ 脚本前面已经把配置改名成「清宵」了 —— 这里取**当前**那条，
    #   别再写死"绯雪"（第一版就是写死的，红了一条没必要的失败）
    _live_prof = store.all()[0]

    detail_flow = TaskFlow(name="详情样例", steps=[
        TaskStep(type=STEP_START, key="start", name="开始"),
        TaskStep(type=STEP_CONFIG, key=_live_prof.id, name=_live_prof.name,
                 config_kind=KIND_ECHO_PROFILE),
        TaskStep(type=STEP_TOOL, key="echo_enhance", name="声骸自动强化"),
        TaskStep(type=STEP_END, key="end", name="结束"),
    ])
    # 期望值**自己拼**（脚本前面已经给配置改过名了，别写死"绯雪"）
    _expect_tile = f"[配置] {_live_prof.name}-声骸强化"

    class _FakePage:
        def has_running_flow(self) -> bool:
            return False

    card = TaskRowCard(detail_flow, _FakePage(), win)
    captured: dict = {}
    _orig_exec = MessageBoxBase.exec

    def _capture_exec(self, *_a, **_kw):
        captured["dialog"] = self
        return 0

    MessageBoxBase.exec = _capture_exec
    try:
        card._show_detail()
    finally:
        MessageBoxBase.exec = _orig_exec

    dlg_detail = captured.get("dialog")
    check("★ 「详情」弹得出来（走的是 TaskRowCard._show_detail 真实路径）",
          dlg_detail is not None)
    if dlg_detail is not None:
        dlg_detail.show()
        for _ in range(10):
            app.processEvents()
        preview = dlg_detail.findChild(FlowPreview)
        check("★ 「详情」里是**流程图**（不再是一行行文字）", preview is not None)
        if preview is not None:
            tiles = [preview.list.item(i).text()
                     for i in range(preview.list.count())]
            check("★ 流程图把每一步都画出来了（瓦片数 = 步数）",
                  len(tiles) == len(detail_flow.steps), str(tiles))
            check("★ 配置那一步用的是配置页的名字（带后缀）",
                  _expect_tile in tiles, f"期望 {_expect_tile!r}；实际 {tiles}")
            # 只读：不能拖、不能选 —— 详情里不该能把步骤拖走
            from PySide6.QtWidgets import QListWidget as _QLW
            check("★ 详情里的流程图是只读的（不能拖）",
                  not preview.list.acceptDrops()
                  and preview.list.dragDropMode() == _QLW.DragDropMode.NoDragDrop,
                  f"acceptDrops={preview.list.acceptDrops()} "
                  f"mode={preview.list.dragDropMode()}")

        # ⚠ 后面的检查都依赖 preview —— 它要是 None（= 没有流程图），
        #   这几条必须**跳过而不是崩**：脚本崩了就什么都打印不出来（实测踩过）
        #
        # ★ 宽度要放得下所有瓦片，否则最后一个会被切（实测 5 个就被切过）
        n_steps = len(detail_flow.steps)
        usable = preview_width_for(n_steps) - 24 * 2          # 去掉左右边距
        check("★ 弹框宽度放得下所有瓦片（最后一个不被切）",
              usable >= n_steps * TILE_SIZE.width(),
              f"{n_steps} 个瓦片需要 {n_steps * TILE_SIZE.width()}px，可用 {usable}px")

        # 配置改名后，详情里的名字也要跟着变（实时读）
        if preview is not None:
            from src.core.game_data import CHARACTERS as _CHARS

            free_name = next(c.name for c in _CHARS
                             if c.name not in ("清宵", "漂泊者·衍射"))
            store.rename("清宵", free_name)
            preview.set_flow(detail_flow)
            app.processEvents()
            tiles2 = [preview.list.item(i).text() for i in range(preview.list.count())]
            check("★ 配置改名后，详情流程图里的名字跟着变",
                  any(f"{free_name}-声骸强化" in t for t in tiles2), str(tiles2))
        dlg_detail.close()

    # 空流程：不该画个大空框，给一行提示
    empty_preview = FlowPreview(TaskFlow(name="空", steps=[]))
    # ⚠ 用 isHidden() 而不是 isVisible()：控件没 show 时 isVisible() 恒为 False
    #   （会被这条断言误判成"提示没显示"）
    check("空流程显示提示、不画空框",
          not empty_preview.empty_hint.isHidden() and empty_preview.list.isHidden(),
          f"hint.isHidden={empty_preview.empty_hint.isHidden()} "
          f"list.isHidden={empty_preview.list.isHidden()}")

    # ---- ⑩ ★ 任务流程启动**之前**要查权限（2026-09-27） ----
    # 权限不足时点击会被 UIPI **静默丢掉**，接着"点完验证"失败 →
    # 报出来是「准备步骤…没看到…」（看着像坐标不对），真正的原因被盖掉。
    # 工具页那条路早就查了（okww_boot.start_task），任务流程这条一直漏着。
    from src.gui.tasks_interface import FlowRunThread
    from src.tools.game.auto_combat import okww_boot as _boot

    _game_flow = TaskFlow(name="游戏流程", steps=[
        TaskStep(type=STEP_TOOL, key="echo_enhance", name="声骸自动强化")])
    _data_flow = TaskFlow(name="数据流程", steps=[
        TaskStep(type=STEP_TOOL, key="wuwa_library_update", name="资源库更新")])
    check("前置：两条流程推导出的类型不一样（否则下面是同义反复）",
          _game_flow.derived_type()[0] == "game"
          and _data_flow.derived_type()[0] == "data",
          f"{_game_flow.derived_type()} / {_data_flow.derived_type()}")

    _orig_perm = _boot.input_permission_error
    _boot.input_permission_error = lambda: "假的权限不足"
    try:
        _blocked = FlowRunThread(_game_flow, None)._permission_block()
        _allowed = FlowRunThread(_data_flow, None)._permission_block()
    finally:
        _boot.input_permission_error = _orig_perm
    check("★ 游戏流程：权限不足时会被拦下（返回原因给用户看）",
          _blocked == "假的权限不足", repr(_blocked))
    check("★ 数据流程：不受影响（不该因为「游戏开着但没提权」被拦）",
          _allowed is None, repr(_allowed))

    # ⚠ 上面两条只验了「`_permission_block` **算得对不对**」；
    #   「它有没有**被调用**」是另一回事 —— 把 `run()` 里那行删掉，上面照样绿。
    #   所以再补一条**接线**检查（源码级），并确认它排在准备动作**之前**。
    _src = (ROOT / "src/gui/tasks_interface.py").read_text(
        encoding="utf-8", errors="replace")
    _perm_at = _src.find("blocked = self._permission_block()")
    _prep_at = _src.find("self._run_start_step(bindings)")
    check("★ 权限预检确实**被调用**，且排在准备动作之前",
          _perm_at != -1 and _prep_at != -1 and _perm_at < _prep_at,
          f"调用点@{_perm_at} / 准备动作@{_prep_at}")

    # ---- ⑪ ★ 流程日志要**同时**进日志文件（2026-09-27） ----
    # 以前 _emit 只 message.emit，界面上那句"某步骤失败"永远进不了日志文件，
    # 出问题只能靠截图口述。功能上验"确实调了 logger"，再接一条源码级检查
    # 覆盖准备动作那条路（它以前走的是 self.message.emit，绕过了 _emit）。
    import logging as _logging

    from src.gui import tasks_interface as _ti

    _records: list[str] = []

    class _Trap(_logging.Handler):
        def emit(self, record):  # noqa: D102
            _records.append(record.getMessage())

    _trap = _Trap()
    _ti.logger.addHandler(_trap)
    # ⚠ logger 的级别默认比 INFO 高时，日志根本到不了 handler ——
    #   不临时放宽，这条护栏会永远 FAIL（而它想验的其实是"有没有写"）。
    _old_level = _ti.logger.level
    _ti.logger.setLevel(_logging.INFO)
    _seen_msgs: list[str] = []
    try:
        _thread = FlowRunThread(_data_flow, None)
        _thread.message.connect(_seen_msgs.append)
        _thread._emit("探针文本")
    finally:
        _ti.logger.removeHandler(_trap)
        _ti.logger.setLevel(_old_level)
    check("★ 流程日志同时进日志文件（_emit 里 logger.info）",
          any("探针文本" in r for r in _records),
          f"logger 收到 {_records!r}")
    check("★ 流程日志同时进界面（message 信号还在发）",
          _seen_msgs == ["探针文本"], repr(_seen_msgs))

    # 源码级：准备动作的 log 回调必须走 self._emit，不能走 self.message.emit
    _prep_log_at = _src.find("log=self._emit")
    _prep_log_bad = _src.find("log=self.message.emit")
    check("★ 准备动作（18 步）的日志也走 _emit（不绕过文件）",
          _prep_log_at != -1 and _prep_log_bad == -1,
          f"log=self._emit@{_prep_log_at} / 被禁的写法@{_prep_log_bad}")

    # ---- ⑬ ★ 「任务类型」不许再出现在**任务列表行**上（2026-09-27） ----
    # 用户：这个标签怎么还有啊，任务类型我已经删了 ——
    # 上次只顾着删**录入**（那对下拉），推导出来的类型还照旧显示在名字后面，
    # 用户看到的就是删了怎么还在。所以这里盯**显示**。
    #
    # ⚠ 查的是**类型标签那个确切字符串**（），
    #   不是含『游戏』二字 —— 后者会误伤摘要和任务名。
    from PySide6.QtWidgets import QLabel

    from src.gui.tasks_interface import TaskRowCard

    _cards = win.tasks_interface.findChildren(TaskRowCard)
    check("任务列表里确实有卡片（否则下面是在空集合上空转）",
          len(_cards) > 0, f"{len(_cards)} 张")
    _tagged = []
    for _card in _cards:
        _want = _card.flow.type_text()
        if not _want:
            continue
        for _lb in _card.findChildren(QLabel):
            if _lb.text() == _want:
                _tagged.append(f"{_card.flow.name} → {_lb.text()!r}")
    check("任务行上没有「游戏 · 鸣潮」这类类型标签", not _tagged,
          "；".join(_tagged[:3]) if _tagged else f"查了 {len(_cards)} 张卡片")

    # ⚠ 源码级检查要**跳过注释行**：第一版直接 grep 整个文件，结果命中了
    #   我自己写的注释（"「任务类型：…」那行也去掉了"），报了个假 FAIL。
    _code_lines = [
        ln for ln in (ROOT / "src/gui/tasks_interface.py").read_text(
            encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]
    check("详情弹框里也不再写「任务类型」（源码级，跳过注释）",
          not any("任务类型：" in ln for ln in _code_lines),
          next((ln.strip()[:60] for ln in _code_lines if "任务类型：" in ln), ""))

    # ---- ⑫ 名称行 = **选角色** + 自动后缀（用户 2026-09-28）----
    # 用户批注："任务这里也是选角色，保存时自动加后缀声骸自动强化"。
    from src.core import game_data
    from src.gui.config_names import FLOW_NAME_SUFFIX, flow_name_for

    game_data.ensure_loaded()      # 保证 CHARACTERS 有内容（下面要按它比对）

    check("弹框里已经没有自由输入的名字框（name_edit）",
          not hasattr(dlg, "name_edit"))
    check("名称行换成了角色下拉（character_box）",
          hasattr(dlg, "character_box"))
    # 候选要覆盖数据集里的全部角色，而且能打拼音筛
    _chars = [c.name for c in game_data.CHARACTERS]
    _matched = dlg.character_box.matched_texts()
    check("★ 角色下拉列出**全部**角色",
          len(_matched) == len(_chars),
          f"候选 {len(_matched)} / 数据集 {len(_chars)}")
    dlg.character_box.setText("feixue")
    app.processEvents()
    _py = dlg.character_box.matched_texts()
    check("★ 角色下拉支持拼音筛（feixue → 绯雪）",
          "绯雪" in _py, f"feixue → {_py[:5]}")
    dlg.character_box.setText("")

    # 保存时自动补后缀；补过的不再补第二次（编辑回填时不能补出两个）
    check("★ 角色名 → 流程名自动加后缀",
          flow_name_for("绯雪") == "绯雪" + FLOW_NAME_SUFFIX,
          flow_name_for("绯雪"))
    check("★ 后缀是**幂等**的（编辑老流程不会补成两个后缀）",
          flow_name_for(flow_name_for("绯雪")) == flow_name_for("绯雪"),
          flow_name_for(flow_name_for("绯雪")))
    dlg.character_box.setText("绯雪")
    dlg._collect()
    check("★ 保存时 flow.name 已带后缀",
          dlg.flow.name == "绯雪" + FLOW_NAME_SUFFIX, dlg.flow.name)

    # ---- ⑬ 校验：角色必须命中数据集 + 按**最终名**查重 ----
    # ⚠ 步骤要从 flow_list 里建（_collect_steps 读的是那个控件），
    #   直接写 flow.steps 是没用的 —— 校验会报"流程里至少要有一步"。
    from src.core.tasks import STEP_END, STEP_START, STEP_TOOL, TaskStore, TaskStep
    from src.gui.task_editor_dialog import _ROLE_DATA, _make_item

    def _add_steps(target) -> None:
        for _t, _k, _n in ((STEP_START, "start", "开始"),
                           (STEP_TOOL, "echo_enhance", "声骸自动强化"),
                           (STEP_END, "end", "结束")):
            _make_item(target.flow_list, _n,
                       {"type": _t, "key": _k, "name": _n, "config_kind": ""})

    import tempfile as _tempfile
    from pathlib import Path as _Path

    with _tempfile.TemporaryDirectory() as _tmp:
        _store = TaskStore(_Path(_tmp) / "tasks.json")

        _d1 = TaskEditorDialog(win, store=_store)
        _d1.character_box.setText("绯雪")
        _add_steps(_d1)
        check("★ 选角色 + 有步骤 → 校验通过", _d1.validate() is True)
        _d1._collect()
        _store.add(_d1.flow)

        _d2 = TaskEditorDialog(win, store=_store)
        _d2.character_box.setText("绯雪")
        _add_steps(_d2)
        check("★ 同一角色再来一条 → 被拦（流程名重复）", _d2.validate() is False)

        _d2.character_box.setText("爱弥斯")
        check("★ 换个角色 → 放行（同一角色可有多条流程不受限）",
              _d2.validate() is True)

        _d3 = TaskEditorDialog(win, store=_store)
        _d3.character_box.setText("绯雪声骸强化配置")
        _add_steps(_d3)
        check("★ 手打一个不是角色的名字 → 被拦", _d3.validate() is False)

        _d4 = TaskEditorDialog(win, store=_store)
        _add_steps(_d4)
        check("★ 没选角色 → 被拦", _d4.validate() is False)

        # 编辑自己：回填角色、不该被自己判成重名
        _d5 = TaskEditorDialog(win, flow=_store.all()[0], store=_store)
        app.processEvents()
        check("★ 编辑存量流程 → 角色下拉正确回填",
              _d5.character_box.text() == "绯雪", _d5.character_box.text())
        check("★ 编辑自己 → 不算重名", _d5.validate() is True)

    # ---- ⑭ 任务行上的**角色头像**（用户 2026-09-28）----
    # 用户："这里也加上显示角色头像吧"。
    from qfluentwidgets import IconWidget as _IconWidget

    from src.gui.tasks_interface import AVATAR_SIZE as _AV
    from src.gui.tasks_interface import TaskRowCard as _Card

    _rows = win.tasks_interface.findChildren(_Card)
    check("检查前置：任务列表里有行（否则下面是空转）", len(_rows) > 0,
          f"{len(_rows)} 行")
    _sized = [r for r in _rows
              if r.avatar_view.width() == _AV and r.avatar_view.height() == _AV]
    check(f"★ 每行行首都有 {_AV}x{_AV} 的头像位（查不到的也占等大空位，保持对齐）",
          len(_sized) == len(_rows),
          f"{len(_sized)}/{len(_rows)} 行尺寸正确")
    # 有角色的行必须**真画出图来**（拿一个确实带头像的角色造一条流程来验）
    _who = next((c.name for c in game_data.CHARACTERS if c.avatar), None)
    if _who:
        from src.core.tasks import TaskFlow as _Flow

        _probe = _Card(_Flow(name=f"{_who}声骸自动强化"), win.tasks_interface,
                       win.tasks_interface)
        app.processEvents()
        check("★ 能查到角色的行**真的画出头像**",
              len(_probe.avatar_view.findChildren(_IconWidget)) > 0,
              f"{_who} → IconWidget "
              f"{len(_probe.avatar_view.findChildren(_IconWidget))}")
        # 查不到时留空、但尺寸照样占住（不画占位图）
        _blank = _Card(_Flow(name="日常清声骸"), win.tasks_interface,
                       win.tasks_interface)
        app.processEvents()
        check("★ 查不到角色的行留空位（不画占位图，也不塌成 0 宽）",
              len(_blank.avatar_view.findChildren(_IconWidget)) == 0
              and _blank.avatar_view.width() == _AV,
              f"{_blank.avatar_view.width()}x{_blank.avatar_view.height()}")

    # ---- ⑮ 没写脏真实文件 ----
    check("真实 tool_settings.json 未被改动", _digest(REAL_SETTINGS) == settings_before)
    check("真实 loadouts.json 未被改动（只读）", _digest(REAL_LOADOUTS) == loadouts_before)

    width = max(len(name) for name, _, _ in CHECKS)
    for name, ok, detail in CHECKS:
        print("%-*s %s%s" % (width, name, "PASS" if ok else "FAIL",
                             ("  " + detail) if detail else ""))
    failed = [c for c in CHECKS if not c[1]]
    print("\n%d 项检查，%d 项失败" % (len(CHECKS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    import atexit

    atexit.register(_atexit_report)      # 崩了也要把结果打出来
    raise SystemExit(main())
