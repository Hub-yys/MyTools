"""声骸自动强化 —— 配置界面 + 运行。

界面结构对应需求：
    ① 核心属性（必输有，缺则弃置；最多 5 条；暴击/爆伤强制勾选且不可取消）
    ② 暴击 / 爆伤各自的下限（左右 -/+ 按钮，也可直接输入）
    ③ 可选属性（列表去掉双爆，勾选数量不限）
    ④ 有效词条数（加减按钮，范围随核心/可选属性联动）
    ⑤ 运行 / 停止
    ⑥ 结果报告（判定数 / 符合条件 / 弃置原因 / 满属性，跑的过程实时刷新）

运行模型：**强化流程整个交给 ok-ww 引擎**（与「4C 自动战斗」共用同一个宿主，
见 ``auto_combat/okww_boot.py``）。本页只负责两件事：
① 收集用户配的筛选条件；② 点「运行」时把它注入任务并启动。

为什么不再自己写一套点击/OCR：2026-09-23 实测那套（``controller`` / ``runner`` /
``reader``）在别的机器上**完全没用**，而同期 4C 走的 ok-ww 引擎是通的 ——
于是流程直接搬 ok-ww 的 ``EnhanceEchoTask``，见 ``okww_task.py``；
只有判定条件换成这里界面上的那套。

按钮状态靠定时器轮询宿主（不自己维护线程），界面不会被阻塞。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core import notifications as N
from ....core import notify, paths, tool_history
from ....core.categories import ToolCategory
from ....core.echo_profile import KIND as ECHO_PROFILE_KIND
from ....core.loadout import KIND as LOADOUT_KIND
from ....core.registry import logger, registry
from ....core.tasks import SET_BONUS_PLANS  #: 成套声骸结构（和新建任务对话框共用）
from ....core.tool_base import BaseTool
from ..auto_combat.okww_boot import get_host
from .settings_editor import EchoSettingsEditor
from .settings import (
    DEFAULT_VALID_COUNT,
    TASK_KEY,
    EchoSettings,
)
from .stats import (
    format_result_report,
    JudgeConfig,
)


# --------------------------------------------------------------------- 说明
# 这里原来有个 RunnerThread：在 QThread 里跑 MyTools 自己写的强化状态机。
# 2026-09-23 换成 ok-ww 引擎后就不需要了 —— 后台线程由 ok-script 的 TaskExecutor
# 负责，本页只用 QTimer 轮询宿主状态。

#: 历史记录文件名前缀（``<用户数据>/echo_enhance_history.json``）
#:
#: ⚠ 别和 4C 那个 ``auto_combat_history.json`` 混用 —— 字段完全不同
#: （那个存战斗/声骸/锁定，这个存判定/保留/弃置/满属性）。
HISTORY_NAMESPACE = "echo_enhance"

#: 历史卡片显示最近几轮
#:
#: ★ 2026-10-30 用户：
#:
#: > 历史记录要每一轮每一轮的展示，不过最多展示最近的10轮，统计还是照常统计
#:
#: 原来是 5 行纯数字表格。现在改成**每轮一张卡片**（带该轮强化好的声骸图），
#: 所以行数提到 10（10 张卡片已经很长了，再多会淹没后面的内容）。
#:
#: ⚠ 底部那行「累计统计」照旧统计**全部**记录（不受这 10 条限制）。
HISTORY_ROWS = 10

#: 说明文字颜色（(浅色主题, 深色主题)）
#: 本文件原来各处直接写 ``"#8A8F98", "#7C7C7C"``，历史卡片要用多次，
#: 提成常量免得又漏一处（跟 4C 页 / 抽卡页同一个灰）。
MUTED = ("#8A8F98", "#7C7C7C")

# --------------------------------------------------------------------- 小控件
# 数值加减框（NumberStepper / NumberField）和配置卡片（ConfigCard）都挪到了
# src/gui/widgets.py —— 新工具「4C 自动战斗」要用同一套，别在后头各写一份。


#: 「满属性」标记的金色（浅色皮肤底 / 深色皮肤底各一档）
_BADGE_GOLD = "#c8a02c"
_BADGE_GOLD_LIGHT = "#f5d76e"


def _badge_bg() -> str:
    """「满属性」标记的底色 —— **跟着当前皮肤算**（不写死）。

    ⚠ 写死浅黄会被 ``tests/test_character_build.TestNoHardcodedLightBackground``
    抓住（它按亮度扫全仓的 ``background:``）：深色皮肤下那就是一块发白的黄斑。
    用户为这类问题报过两次，所以老老实实按皮肤混。
    """
    from ....core import skins

    try:
        skin = skins.active_skin()
        return skins.blend_color(
            skin["bg"][0][1],
            _BADGE_GOLD if skin["mode"] == "dark" else _BADGE_GOLD_LIGHT,
            0.28 if skin["mode"] == "dark" else 0.45)
    except Exception:  # noqa: BLE001 - 取皮肤色失败不该让卡片建不出来
        return "#f2e6c0"


def _badge_fg() -> str:
    """标记文字色：深色底上用亮金，浅色底上用深棕（都要压得住底色）。"""
    from ....core import skins

    try:
        return "#e8d9a0" if skins.active_skin()["mode"] == "dark" else "#6b5310"
    except Exception:  # noqa: BLE001
        return "#6b5310"


class QualifyingEchoCard(CardWidget):
    """一个「符合条件的声骸」卡片：**声骸截图 + 词条**。

    用户 2026-10-10 要求::

        "结果报告符合条件的要完整展示声骸图，以卡片形式展示"

    ## 图从哪来

    ok-ww 在 ``lock_and_esc`` 里**已经**给每个上锁的声骸截了图
    （``screenshot_echo('success/<序号>')``），落在
    ``<用户数据>/okww/screenshots/success/`` 下。这里直接读那些图，
    **不重建截图链路**（那要碰 ok-ww 的坐标和时序，风险大得多）。

    ⚠ 找不到图就**只显示词条**，不留一个空洞的灰框
    （本仓的老规矩：拿不到图就不画占位 —— 见 ``detail_view._icon_label``）。
    """

    #: 声骸图默认显示宽度（原始截图约 538×497，等比缩到这么大够看清楚词条）
    IMAGE_WIDTH = 190

    def __init__(self, item: dict, *, index: int, is_perfect: bool = False,
                 parent=None, image_width: int | None = None):
        """
        :param image_width: 图宽覆盖。历史卡片里一行要并排放好几轮，
            用 :data:`IMAGE_WIDTH` 会太宽 —— 那边传 120。
        """
        super().__init__(parent)
        from qfluentwidgets import BodyLabel

        self._image_width = int(image_width or self.IMAGE_WIDTH)

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)

        # ── 标题行：第 N 个 + 「满属性」标记（如果这个声骸出了满值词条）
        head = QHBoxLayout()
        head.setSpacing(6)
        title = StrongBodyLabel(f"第 {index} 个", self)
        head.addWidget(title)
        if is_perfect:
            #: ⚠ 满属性 ≠ 符合条件：出了满暴击/满爆伤会被上锁（有意保护），
            #: 但有效词条数可能不够。那个标记要说清它是"因为满值才留下的"。
            badge = CaptionLabel("满属性", self)
            #: ★ 底色**跟皮肤算**，不写死。
            #:
            #: ⚠ 我第一版写死 ``background: #ffe9a8`` —— 被本仓自己的
            #: ``TestNoHardcodedLightBackground``（按亮度扫全仓的 background）
            #: 当场抓住：**深色皮肤下会是一块发白的黄斑**。
            #: 那个测试就是为这个bug类建的（用户报过两次"深色皮肤下发白"），
            #: 所以这里走它的正解：用 ``skins`` 按当前皮肤混出实色。
            badge.setStyleSheet(
                f"color: {_badge_fg()}; background: {_badge_bg()};"
                f" border-radius: 6px; padding: 1px 6px;")
            head.addWidget(badge)
        head.addStretch(1)
        box.addLayout(head)

        # ── 声骸图（拿不到就跳过这一块）
        pixmap = self._load_pixmap(item.get("image") or "")
        if pixmap is not None and not pixmap.isNull():
            holder = QLabel(self)
            holder.setPixmap(pixmap)
            holder.setAlignment(Qt.AlignmentFlag.AlignLeft)
            box.addWidget(holder)

        # ── 词条（图看不到时这就是唯一信息，所以一定要有）
        stats = item.get("stats") or []
        text = "、".join(str(s) for s in stats) if stats else "（没读到词条）"
        body = BodyLabel(text, self)
        body.setWordWrap(True)
        box.addWidget(body)

    def _load_pixmap(self, name: str):
        """按**文件名**去截图目录取图（不是绝对路径 —— 见 okww_task 的说明）。"""
        from PySide6.QtGui import QPixmap

        if not name:
            return None
        try:
            folder = paths.user_data_dir() / "okww" / "screenshots" / "success"
            path = folder / name
            if not path.is_file():
                return None
            pix = QPixmap(str(path))
            if pix.isNull():
                return None
            return pix.scaledToWidth(self._image_width,
                                     Qt.TransformationMode.SmoothTransformation)
        except Exception:  # noqa: BLE001 - 图读不出来不该让报告卡崩掉
            return None


# ------------------------------------------------------------------ 统计快照


def _snapshot_task_stats(task) -> dict:
    """从任务实例抄一份本次运行的统计。

    为什么每 300ms 抄一次：任务跑完会被 ok-script disable，到时候
    ``checked_echoes`` / ``discard_tally`` 这些实例属性就读不到了。
    """
    info = getattr(task, "info", None)
    if not isinstance(info, dict):
        info = {}
    return {
        "checked": int(getattr(task, "checked_echoes", 0) or 0),
        "kept": int(info.get("成功声骸数量") or 0),
        "dropped": int(info.get("失败声骸数量") or 0),
        # 满属性只在「启用满暴击/满爆伤自动锁定」时才统计 ——
        # 键不存在就是没启用，报告里也不显示这项
        "perfect": info.get("满属性声骸数量"),
        "tally": dict(getattr(task, "discard_tally", None) or {}),
        # 任务异常中断的原因（okww_task.run 捕获异常时写进去的）。
        # 有它时报告优先显示它 —— 真实原因都在这里，不显示的话用户会去
        # 看默认那句「请确认停在 背包 → 声骸 界面」，完全对不上。
        "failed_reason": (str(info.get("失败原因") or "").strip() or None),
        #: ★ 真正符合条件的声骸清单（用户要求：报告里以卡片完整展示声骸图）
        "qualifying": list(info.get("符合条件的声骸") or []),
    }


def _format_report(stats: dict) -> str:
    """``_snapshot_task_stats()`` 的字典 → 报告文字（**安全包装**）。

    ## ⚠ 为什么需要它（2026-10-28 我引入的 bug）

    ``_snapshot_task_stats()`` 返回的键比 ``format_result_report()``
    接受的多一个 ``qualifying``（符合条件的声骸清单，给卡片区用的）。

    原来直接写::

        format_result_report(**self._last_stats)

    → ``TypeError: got an unexpected keyword argument 'qualifying'``
    → ``_poll`` 里**每 300ms 抛一次**，界面报告区完全不更新
    （日志里刷了几十屏同样的 traceback）。

    ## 做法

    只挑 ``format_result_report`` 认识的键传进去。
    这样以后 ``_snapshot_task_stats`` 再加字段也不会再炸。
    """
    accepted = ("checked", "kept", "dropped", "perfect", "tally",
                "failed_reason")
    picked = {k: stats[k] for k in accepted if k in stats}
    try:
        return format_result_report(**picked)
    except Exception as exc:  # noqa: BLE001 - 排版失败不能把轮询带崩
        logger.warning("生成强化报告失败：%s", exc, exc_info=True)
        return f"（报告生成失败：{type(exc).__name__}）"


# --------------------------------------------------------------------- 主界面

def _find_echo_profile(key: str):
    """按 key 取一条「角色声骸强化配置」。取不到返回 ``None``。

    key 是 ``EchoProfile.id``（**稳定 id**，改名不变）；``by_id`` 找不到
    再按**角色名**试一次 —— 兼容 2026-09-26 之前存的、按名字指的老流程。
    读配置出任何问题都不该把任务带崩，所以这里兜住。
    """
    key = str(key or "").strip()
    if not key:
        return None
    try:
        from ....core.echo_profile import EchoProfileStore

        store = EchoProfileStore()
        store.load()
        return store.by_id(key) or store.get(key)
    except Exception:  # noqa: BLE001 - 配置文件坏了就当作没有
        logger.warning("读「角色声骸强化配置」失败（key=%s）", key, exc_info=True)
        return None


def _bound_loadout(options: dict):
    """按 key 取编排里挂的「角色声骸筛选配置」（``Loadout``）。取不到返回 ``None``。

    key 是 ``Loadout.id``。找不到（配置被删了）就返回 None —— 调用方会退化成
    "让用户自己筛"，不会因此把任务打断。
    """
    keys = list(options.get("config_keys") or [])
    kinds = list(options.get("config_kinds") or [])
    for index, key in enumerate(keys):
        kind = kinds[index] if index < len(kinds) else ""
        if kind != LOADOUT_KIND:
            continue
        try:
            from ....core.loadout import LoadoutStore

            return LoadoutStore().get(str(key))
        except Exception:  # noqa: BLE001 - 配置坏了不该把任务带崩
            logger.warning("读「角色声骸筛选配置」失败（key=%s）", key, exc_info=True)
            return None
    return None


def _loadout_picks(loadout) -> dict:
    """``{档位: [声骸名, ...]}`` —— 给日志用（每档勾了几个什么）。"""
    result: dict = {}
    for cost in (4, 3, 1):
        try:
            picks = loadout.picks_of(cost)
        except Exception:  # noqa: BLE001
            picks = []
        if picks:
            result[cost] = [
                getattr(getattr(pick, "echo", None), "name", str(getattr(pick, "echo", "")))
                for pick in picks
            ]
    return result


def _allowed_echo_names(loadout) -> set[str]:
    """配置里**勾选过的所有声骸名**（归一化后），用作强化白名单。

    ## 用户 2026-10-29

    > 配置哪里我不是勾选了声骸吗，可以准确识别出声骸名和声骸类型
    > （4C、3C、1C），我想要实现比如强化好了一个 融躯战士 1C
    > （就是符合条件的，只是满属性的除外），那么就跳过他

    配置里 ``picks`` 是 ``{Cost: [EchoPick(echo='解形煞',...), ...]}``，
    每一档勾了哪些声骸、叫什么名字，这里全都拉平成一个名字集合。

    ## 为什么归一化

    和任务侧 ``_handled_echoes`` 用**同一套** ``same_echo.normalize_echo_name``
    （去空白/标点）。否则「小翼龙·衍射」在配置里带「·」、OCR 读出来
    可能不带，比对就会失配 → 该强化的被跳过（比漏强化更糟）。

    ## 为什么不分 Cost 档

    理论上可以用「当前声骸是几 C + 叫什么」做二维判断，但：
      * 读 Cost 要多一次 OCR（右侧面板「COST 3」那行）
      * 同名声骸的 Cost **本来就固定**（融躯战士永远是 1C），
        名字已经隐含了档位
    → 只按名字判就够了，少一次 OCR、少一处可能出错的地方。
    """
    names: set[str] = set()
    try:
        from . import same_echo  # noqa: PLC0415

        normalize = same_echo.normalize_echo_name
    except Exception:  # noqa: BLE001 - 导入失败就退回朴素 strip
        normalize = lambda s: str(s or "").strip()  # noqa: E731

    for cost in (4, 3, 1):
        try:
            picks = loadout.picks_of(cost)
        except Exception:  # noqa: BLE001
            continue
        for pick in picks or ():
            echo = getattr(pick, "echo", None)
            #: ``echo`` 可能是字符串，也可能是带 ``.name`` 的对象
            name = getattr(echo, "name", None)
            if name is None:
                name = echo
            key = normalize(str(name or ""))
            if key:
                names.add(key)
    return names


def _picks_by_cost(loadout) -> dict:
    """配置的声骸按 Cost 分组 → ``{4: ['名1'], 3: [...], 1: [...]}``。

    ## 用途（2026-10-29 成套声骸）

    任务侧要判断"当前这个声骸是几 C"，但不想多一次 OCR 读「COST 3」那行。
    配置的 ``picks`` 本来就是按 Cost 存的，用它建一张「名字 → Cost」
    反查表就够了（见 ``okww_task._build_cost_index``）。
    """
    result: dict = {}
    for cost in (4, 3, 1):
        try:
            picks = loadout.picks_of(cost)
        except Exception:  # noqa: BLE001
            continue
        names: list[str] = []
        for pick in picks or ():
            echo = getattr(pick, "echo", None)
            name = getattr(echo, "name", None)
            if name is None:
                name = echo
            text = str(name or "").strip()
            if text:
                names.append(text)
        if names:
            result[cost] = names
    return result


def _set_plan_of_flow(flow_name: str) -> str:
    """从流程名里读套装结构（``43311`` / ``44111``）。

    ``绯雪-声骸自动强化（小毕业 43311）`` → ``'43311'``
    ``绯雪-声骸自动强化（小毕业）``       → ``''``（不成套）
    """
    if not flow_name:
        return ""
    try:
        from ....gui.config_names import flow_set_plan_of  # noqa: PLC0415

        return flow_set_plan_of(flow_name)
    except Exception:  # noqa: BLE001 - 读不到就当不成套
        return ""


class EchoEnhanceWidget(ScrollArea):

    #: ★ 2026-10-30 ``COLS``（时间/时长/判定/保留/弃置 的固定列宽）**已删除**。
    #:
    #: 历史记录从"纯数字表格"改成了"每轮一张卡片"（用户要求带声骸图），
    #: 统计数字写在卡片头里、靠 Layout 自然排布，不再需要列宽。
    #: 原来那个「判定数字叠成一团」的坑（列宽 62px 装不下 3~4 位数）
    #: 也随之消失 —— 现在没有固定列了。

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("EchoEnhanceWidget")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        #: ok-ww 宿主（进程内单例，与 4C 自动战斗共用一个 OK 实例）
        self._host = get_host()
        self._timer: QTimer | None = None
        #: 只在状态**变化**时写日志，别每 300ms 刷一次
        self._last_state = ""
        self._was_running = False
        #: 任务跑起来后持续抄统计 —— 结束时任务被 disable，就取不到了
        self._last_stats: dict = {}
        #: 本次轮询期间见过本页的任务（running/pending）——
        #: 引擎自启完成（booting→ready）不算「任务结束」，就靠它区分
        self._task_seen = False
        #: ★ 已经报过的「自动停止原因」（防止每 300ms 重复弹气泡 —— 见 _notify_auto_stop）
        self._auto_stop_reported = ""
        #: 上一次轮询时任务是不是暂停着（「继续」按钮的可见状态跟着它走）
        self._was_paused = False
        #: ★ 历史记录（2026-10-28 用户：结果报告也加上历史记录）
        self._history = tool_history.ToolHistoryStore(HISTORY_NAMESPACE)
        #: 本次运行的开始时刻（落历史时算时长用）
        self._run_started_at = 0.0
        #: 本页当前的一套设置。**每次打开页面都是出厂默认**（用户 2026-09-24
        #: 明确要求："不要遗留上次的东西，每次进入都是默认配置"）—— 所以这里
        #: 不用 ``EchoSettings.load()``。改动仍然存盘，任务流程读的就是存下来那份。
        #:
        #: ⚠ 本页**不碰**「角色声骸强化」那些配置（配置页里的第二类）——
        #: 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的配置是无关的"。
        #: 那条种子（第一次升级时补一条「默认」）由配置页负责，本页不掺和。
        self._settings = EchoSettings()

        view = QWidget(self)
        view.setObjectName("echoView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_title_row(view))
        intro = CaptionLabel(
            "在背包 → 声骸界面用过滤器筛好、按等级升序排序，再点运行。"
            "强化流程由 ok-ww 引擎执行（与「4C 自动战斗」同一个引擎，后台按键不抢前台）："
            "符合条件的上锁保留，不符合条件的自动弃置。\n"
            f"运行日志按日期落盘：{paths.user_data_dir() / 'okww' / 'logs'}"
            "（出问题把当天那个文件发过来即可）",
            view,
        )
        intro.setTextColor("#8A8F98", "#7C7C7C")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # ★ 设置区是**独立组件** —— 配置页里编辑「角色声骸强化」配置用的是同一份，
        #   两边界面永远一致（改一处两边都变）。见 settings_editor.py。
        self.editor = EchoSettingsEditor(view)
        self.editor.changed.connect(self._save_settings)
        layout.addWidget(self.editor)

        layout.addWidget(self._build_report_card(view))
        #: ★ 2026-10-28 用户：「结果报告 … 也加上历史记录」
        layout.addWidget(self._build_history_card(view))

        layout.addStretch(1)

        # 回填上次的选择 —— 界面上看到的值 = 任务流程会用的值，必须是同一份
        self.editor.set_settings(self._settings)

        self.setWidget(view)
        self.setWidgetResizable(True)

        # 状态靠轮询宿主（和 4C 工具页一致），页面不自己维护线程
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(300)
        self._poll()

    # ---------------------------------------------------------------- 配置卡片
    #: ⚠ 这里**故意没有**「用哪套配置」的选择器。
    #:   「角色声骸强化」那些配置（配置页里的第二类）和本页的设置是**两回事**
    #:   —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的配置是无关的"。
    #:   曾经加过一条下拉 + "改动写回当前那套"，属于把两者绑在一起的错误设计，已拆掉。
    #:   将来要做"按配置跑"的话，应该是**显式选择并注入任务**，而不是让两者共享存储。






    def _build_report_card(self, parent: QWidget) -> QWidget:
        """本次运行的结果报告（判定数 / 符合条件 / 弃置原因 / 满属性）。

        跑的过程中就实时刷新（数据来自每 300ms 的统计快照），结束后定格。

        ★ 2026-10-10 起下面多一块「符合条件的声骸」卡片区（用户要求：
        "结果报告符合条件的要完整展示声骸图，以卡片形式展示"）。
        """
        card = CardWidget(parent)
        col = QVBoxLayout(card)
        col.setContentsMargins(20, 15, 20, 15)
        col.setSpacing(4)
        col.addWidget(StrongBodyLabel("结果报告", card))
        self.report_label = CaptionLabel(
            "还没跑过 —— 点「运行」后这里实时显示本次的统计", card)
        self.report_label.setTextColor("#8A8F98", "#7C7C7C")
        self.report_label.setWordWrap(True)
        # 老坑：QLabel 开 wordWrap 后 sizeHint 只算一行 → 第二行（弃置原因）被截掉。
        # 按两行钉最小高度；正文固定两行以内（首行统计 + 弃置原因），不会溢出。
        self.report_label.setMinimumHeight(46)
        col.addWidget(self.report_label)

        #: ★ 符合条件的声骸卡片区（没有符合条件的就整块隐藏）
        self.echo_area = QWidget(card)
        self.echo_box = QVBoxLayout(self.echo_area)
        self.echo_box.setContentsMargins(0, 6, 0, 0)
        self.echo_box.setSpacing(8)
        self.echo_area.setVisible(False)
        col.addWidget(self.echo_area)
        #: 上次画的是哪一批（只在内容真的变了才重建 —— 否则每 300ms 重建一次，
        #: 图片会一直闪，而且 300ms 重新解码几十张 PNG 很费）
        self._echo_key: tuple = ()
        return card

    # ------------------------------------------------------------------ 历史
    def _build_history_card(self, parent: QWidget) -> QWidget:
        """「历史记录」—— 每次「运行 → 停止」记一条。

        ## 用户 2026-10-28

        > 结果报告 … 也加上历史记录

        ## 显示什么

        每行：时间 / 时长 / 判定 / 保留 / 弃置 / 满属性（有才显示）。
        只列最近 :data:`HISTORY_ROWS` 条，多了在底部给累计汇总。

        ## 为什么不做成卡片

        4C 那边用卡片是因为要**点选切换账号**；这里没有切换需求，
        数字又多（6 列），行式排版更省地方也更好扫。
        """
        card = CardWidget(parent)
        head = QHBoxLayout()
        head.setContentsMargins(20, 15, 20, 0)
        head.addWidget(StrongBodyLabel("历史记录", card))
        head.addStretch(1)
        clear = PushButton("清空历史", card)
        clear.setFixedWidth(96)
        clear.setToolTip("删掉本地记录的强化历史（不影响已强化的声骸）")
        clear.clicked.connect(self._clear_history)
        head.addWidget(clear)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 15)
        outer.setSpacing(4)
        outer.addLayout(head)

        #: ★ 2026-10-30 去掉了原来的「时间/时长/判定/保留/弃置」列标题 ——
        #: 现在每轮是一张卡片，统计直接写在卡片头里，
        #: 列标题既对不齐也没意义了。

        self.history_box = QVBoxLayout()
        self.history_box.setContentsMargins(20, 6, 20, 0)
        self.history_box.setSpacing(8)
        outer.addLayout(self.history_box)

        self.history_hint = CaptionLabel(
            "还没跑过 —— 点「运行」跑一次，结束后会记在这里", card)
        self.history_hint.setTextColor(*MUTED)
        outer.addWidget(self.history_hint)

        self.history_total = CaptionLabel("", card)
        self.history_total.setTextColor(*MUTED)
        self.history_total.setWordWrap(True)
        outer.addWidget(self.history_total)

        self._history_key: tuple = ()
        self._refresh_history()
        return card

    def _refresh_history(self) -> None:
        """重画历史卡片（内容没变就跳过 —— 这卡会被 _poll 频繁带动）。"""
        records = self._history.records(HISTORY_ROWS)
        #: ★ 指纹要带上**声骸清单** —— 现在卡片里有图，
        #: 只比统计数字的话，同一轮补上/换掉声骸图不会触发重画。
        key = tuple(
            (r.started_at, r.duration, r.get("checked"),
             r.get("kept"), r.get("dropped"), r.get("perfect"),
             tuple(
                 (it.get("index"), it.get("image"),
                  tuple(it.get("stats") or []))
                 for it in (r.get("qualifying") or [])
                 if isinstance(it, dict)))
            for r in records)
        if key == self._history_key:
            return
        self._history_key = key

        while self.history_box.count():
            item = self.history_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not records:
            self.history_hint.setVisible(True)
            self.history_total.setVisible(False)
            self.history_total.setText("")
            return

        self.history_hint.setVisible(False)
        for record in records:
            self.history_box.addWidget(self._build_history_entry(record))

        items = self._history.records()
        seconds = sum(r.duration for r in items)
        h, rem = divmod(int(seconds), 3600)
        minutes = rem // 60
        #: 底部累计**照常统计全部记录**（不受上面只显示 10 轮的限制）——
        #: 用户 2026-10-30：「统计还是照常统计」。
        more = (f"（上面只列最近 {HISTORY_ROWS} 轮）"
                if len(items) > HISTORY_ROWS else "")
        self.history_total.setText(
            f"共 {len(items)} 轮 · 累计判定 {sum(r.get('checked') for r in items)} "
            f"个 · 保留 {sum(r.get('kept') for r in items)} 个 · "
            f"弃置 {sum(r.get('dropped') for r in items)} 个 · "
            f"累计 {h} 小时 {minutes} 分{more}")
        self.history_total.setVisible(True)

    def _build_history_entry(self, record) -> QWidget:
        """★ 一轮历史 → 一张卡片（统计 + 该轮强化好的声骸图）。

        ## 用户 2026-10-30

        > 历史记录要每一轮每一轮的展示，不过最多展示最近的10轮

        原来是 5 行纯数字（时间/判定/保留/弃置），看不出每轮**强化出了什么**。
        现在每轮一张卡：上面一行是这轮的统计，下面横向排该轮的声骸图。

        ## 为什么用横向排图

        一屏高度有限，一张卡里横向排比纵向堆省地方得多；
        每轮通常也就 1~3 个符合条件的声骸，横排刚好。
        """
        card = CardWidget(self)
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(6)

        # ── 统计行
        head = QHBoxLayout()
        head.setSpacing(14)
        when = StrongBodyLabel(record.when_text, card)
        head.addWidget(when)
        for text in (record.duration_text,
                     f"判定 {record.get('checked')}",
                     f"保留 {record.get('kept')}",
                     f"弃置 {record.get('dropped')}"):
            label = CaptionLabel(text, card)
            label.setTextColor(*MUTED)
            head.addWidget(label)
        perfect = record.get("perfect")
        if perfect:
            label = CaptionLabel(f"满属性 {perfect}", card)
            label.setTextColor(*MUTED)
            head.addWidget(label)
        head.addStretch(1)
        box.addLayout(head)

        # ── 该轮强化好的声骸（横向排图 + 词条）
        qualifying = record.get("qualifying") or []
        if not qualifying:
            box.addWidget(CaptionLabel("这一轮没有符合条件的声骸", card))
            return card

        row = QHBoxLayout()
        row.setSpacing(10)
        for item in qualifying:
            if not isinstance(item, dict):
                continue
            row.addWidget(QualifyingEchoCard(
                item,
                index=int(item.get("index") or 0),
                is_perfect=bool(item.get("perfect")),
                parent=card,
                #: 历史卡片里图小一点，一行能并排放下好几个
                image_width=120))
        row.addStretch(1)
        box.addLayout(row)
        return card

    def _record_history(self) -> None:
        """把这次运行的统计落一条历史（任务结束分支里调）。"""
        stats = self._last_stats or {}
        #: 什么都没判定 —— 多半是点了「运行」就立刻停，不记垃圾行
        if not stats.get("checked") and not stats.get("kept") \
                and not stats.get("dropped"):
            return
        started = self._run_started_at or 0.0
        if not started:
            return
        record = tool_history.ToolRunRecord(
            started_at=started,
            ended_at=time.time(),
            duration=max(0.0, time.time() - started),
            extra={
                "checked": int(stats.get("checked") or 0),
                "kept": int(stats.get("kept") or 0),
                "dropped": int(stats.get("dropped") or 0),
                "perfect": int(stats.get("perfect") or 0),
                "tally": dict(stats.get("tally") or {}),
                #: ★ 2026-10-30 用户：
                #:
                #: > 历史记录要每一轮每一轮的展示
                #:
                #: 把这一轮「符合条件的声骸」清单（名字 / 词条 / 截图文件名）
                #: 一起存下来，历史卡片就能带着图展示每一轮强化出了什么。
                #:
                #: ⚠ 只存**文件名**不存绝对路径 —— 截图目录在不同机器/
                #: 不同用户下不一样，存路径换台机器就打不开了
                #: （和 ``QualifyingEchoCard._load_pixmap`` 的做法一致）。
                "qualifying": [
                    {
                        "index": it.get("index"),
                        "image": it.get("image"),
                        "stats": list(it.get("stats") or []),
                        "perfect": bool(it.get("perfect")),
                    }
                    for it in (stats.get("qualifying") or [])
                    if isinstance(it, dict)
                ],
            })
        self._history.add(record)
        self._history_key = ()       #: 强制重画
        self._refresh_history()

    def _clear_history(self) -> None:
        box = MessageBox("清空强化历史",
                         "删掉本地记录的强化历史？\n"
                         "只影响这张表，不影响游戏里已经强化的声骸。",
                         self.window())
        box.yesButton.setText("清空")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        self._history.clear()
        self._history_key = ()
        self._refresh_history()

    # ------------------------------------------------------- 待还原锁定提醒

    def _update_echo_cards(self, qualifying) -> None:
        """把「符合条件的声骸」画成卡片（图 + 词条）。

        ⚠ 用 ``_echo_key`` 做**内容指纹**：这一卡每 300ms 被刷一次，
        无条件重建的话图片会闪、还白白解码 PNG。内容没变就直接跳过。

        ## ★ 2026-10-30 改横排

        原来是一张一张**竖着堆**（``echo_box.addWidget(card)``），
        一轮强化出 3 个就占掉半屏，下面的历史记录被挤到很下面。
        现在横向并排（和下面历史卡片里的排法一致），
        一屏能同时看见「报告 + 声骸图 + 历史」。
        """
        items = list(qualifying or [])
        key = tuple((it.get("index"), it.get("image"), bool(it.get("perfect")),
                     tuple(it.get("stats") or [])) for it in items
                    if isinstance(it, dict))
        if key == self._echo_key:
            return
        self._echo_key = key

        #: 清空（连同旧控件）
        while self.echo_box.count():
            child = self.echo_box.takeAt(0)
            w = child.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if not items:
            self.echo_area.setVisible(False)
            return

        head = StrongBodyLabel(f"符合条件的声骸（{len(items)} 个）", self.echo_area)
        self.echo_box.addWidget(head)
        #: ★ 横排容器（一行放得下就一行，放不下由 Qt 自己挤）
        row = QHBoxLayout()
        row.setSpacing(10)
        for item in items:
            if not isinstance(item, dict):
                continue
            card = QualifyingEchoCard(
                item, index=int(item.get("index") or 0),
                #: ★ 满属性标记取**这个声骸自己**的标记（不在卡片区用全局计数近似）
                is_perfect=bool(item.get("perfect")),
                parent=self.echo_area,
                #: 横排时图小一点，一行能并排 3~4 个
                image_width=150)
            row.addWidget(card)
        row.addStretch(1)
        self.echo_box.addLayout(row)
        self.echo_area.setVisible(True)

    def _update_report_card(self, text: str) -> None:
        label = getattr(self, "report_label", None)
        if label is not None:
            label.setText(text)

    def _build_title_row(self, parent: QWidget) -> QWidget:
        """标题 + 紧随其后的操作按钮。"""
        holder = QWidget(parent)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        row.addWidget(StrongBodyLabel("声骸自动强化", holder))

        self.run_button = PrimaryPushButton(FluentIcon.PLAY, "运行", holder)
        self.run_button.clicked.connect(self._on_run)

        #: ★「继续」—— 自动停止把任务**暂停**了，没有这个按钮用户就回不去
        #:
        #: ⚠ 这不是可选的锦上添花：``pause()`` 之后 ok-ww 的 executor 会停在
        #: "不抓帧"的状态（``TaskExecutor.next_frame`` 里那句
        #: ``if not (self.paused or task.paused …)``），任务确实不动了 ——
        #: 而工具箱这边原来**只有「运行」和「停止」**，两个都不是"接着跑"。
        #: 少了它，"可续跑"就只是个说法（用户只能停止再重跑，前面强化的白费）。
        self.resume_button = PushButton(FluentIcon.PLAY, "继续", holder)
        self.resume_button.setEnabled(False)
        self.resume_button.clicked.connect(self._on_resume)

        self.stop_button = PushButton(FluentIcon.CANCEL, "停止", holder)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)

        #: ★★ 2026-10-30 用户：
        #:
        #: > 这个跳过可以加到声骸自动强化工具这里
        #:
        #: 从「任务」页搬到**工具页** —— 那边那个是测试用的，验证通过后删了；
        #: 这个是给日常用的：强化途中遇到某个不想要的声骸，按一下就换下一个。
        #:
        #: ## 语义（和自动跳过一致）
        #:
        #: 用户 2026-10-30 确认：
        #:
        #: > 跳过相当与他已经强化好了，需要跳过同类型同名声骸
        #:
        #: 所以按一下 = **把这个声骸当成"已强化好"记下来** →
        #: ① 跳过它本身；② 之后所有同名同类型的（含「异相」版）都跳过；
        #: ③ 成套模式下**计入该 Cost 档的种类数**（跳够 2 个 1C 就去强化 3C）。
        #:
        #: ## 怎么送进引擎线程
        #:
        #: 任务跑在 ok-ww 的线程里，界面线程不能直接改它的属性。
        #: 所以走宿主中转（一次性标志），任务在检查点取走。
        #: 见 ``OkwwHost.request_skip_current`` 与
        #: ``okww_task._consume_skip_request``。
        self.skip_button = PushButton(FluentIcon.SYNC, "跳过", holder)
        self.skip_button.setEnabled(False)
        self.skip_button.setToolTip(
            "跳过当前正在强化的声骸（当作已强化好：之后同名的都跳过，"
            "成套模式下还算作该档凑够一种）")
        self.skip_button.clicked.connect(self._on_skip)

        # 乱了一键拉回出厂默认：核心仅双爆 / 有效词条 = 2 / 可选清空
        self.reset_button = PushButton(FluentIcon.SYNC, "恢复默认", holder)
        self.reset_button.clicked.connect(self._on_reset_defaults)

        # 按钮紧跟在标题右边，不推到最右
        row.addWidget(self.run_button)
        row.addWidget(self.resume_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.skip_button)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        return holder

    # ---------------------------------------------------------------- 勾选约束








    # ---------------------------------------------------------------- 配置读写
    def _save_settings(self, *_) -> None:
        """配置一变就存盘 —— **任务流程运行时读的就是这一份**。

        设置控件本体在 :class:`~.settings_editor.EchoSettingsEditor` 里
        （那边改完发 ``changed`` 信号，这里接住落盘）。
        """
        self._settings = self.editor.settings()
        try:
            self._settings.save()
        except Exception as exc:  # noqa: BLE001 - 存不下来不该影响使用
            logger.warning("声骸强化设置存不下来：%s", exc)

    # ------------------------------------------------- 兼容：设置控件的直接访问
    # 检查脚本（check_echo_page_gui / check_settings_gui）会直接摸这些控件来断言，
    # 而它们现在住在 editor 里。转发一层，脚本不用改，改起来也只有这一处。
    @property
    def _core_boxes(self):
        return self.editor.core_boxes

    @property
    def _optional_boxes(self):
        return self.editor.optional_boxes

    @property
    def core_count_label(self):
        return self.editor.core_count_label

    @property
    def criterion_label(self):
        return self.editor.criterion_label

    @property
    def crit_field(self):
        return self.editor.crit_field

    @property
    def crit_dmg_field(self):
        return self.editor.crit_dmg_field

    @property
    def crit_switch(self):
        return self.editor.crit_switch

    @property
    def maxroll_switch(self):
        return self.editor.maxroll_switch

    @property
    def valid_stepper(self):
        return self.editor.valid_stepper

    def _checked_core(self) -> list:
        return self.editor.checked_core()

    def _checked_optional(self) -> list:
        return self.editor.checked_optional()

    def _update_core_count(self) -> None:
        self.editor._update_core_count()          # noqa: SLF001 - 见上面的说明

    def _update_optional_count(self, *_) -> None:
        self.editor._update_optional_count(*_)    # noqa: SLF001 - 见上面的说明

    def _sync_valid_count(self, *_, follow_core: bool = False) -> None:
        self.editor._sync_valid_count(follow_core=follow_core)  # noqa: SLF001

    def _apply_settings(self, settings: EchoSettings) -> None:
        self.editor.set_settings(settings)
        self._settings = self.editor.settings()

    def build_judge_config(self) -> JudgeConfig:
        """界面当前的值 → 判定配置（双爆由 JudgeConfig 强制进核心属性）。"""
        return self.editor.settings().to_judge_config()

    # ---------------------------------------------------------------- 日志
    def _append(self, text: str) -> None:
        """界面上不再显示日志区，运行日志走标准 logging
        （PyCharm 的运行/调试窗口里能看到；出错时另有 InfoBar 弹窗）。"""
        logger.info("[声骸强化] %s", text)

    # ---------------------------------------------------------------- 动作
    def _on_run(self) -> None:
        self._save_settings()          # 顺手存盘：任务流程跑的时候读的就是这一份
        settings = self.editor.settings()
        config = settings.to_judge_config()

        #: ★ 新一轮：清掉上一轮的自动停止标记，否则这次停了不会再报
        self._auto_stop_reported = ""
        self._echo_key = ()
        self._update_echo_cards([])
        #: ★ 记开始时刻 —— 结束时落历史要算时长（2026-10-28）
        self._run_started_at = time.time()

        self._append("— 开始运行（ok-ww 引擎）—")
        self._append("判定配置：" + settings.describe())
        self._append("前置：请停在 背包 → 声骸 界面，用过滤器筛好、按等级升序排序")
        self._append("⚠ 不符合条件的自动弃置（按 Z），符合条件的上锁（按 C）")
        if settings.enable_auto_stop:
            self._append("★ 出现符合条件的声骸会**自动暂停**并通知你")
        if self._host.state in ("idle", "error"):
            self._append("引擎未就绪：后台加载 ok-ww 中，就绪后自动开始（首次会慢一些）")

        # 把页面上的判定条件注入任务实例（ok-ww 的任务本身不知道这些）
        def configure(task):
            task.judge_config = config

        err = self._host.start_task(TASK_KEY, configure=configure)
        if err:
            self._append("启动失败：" + err)
            InfoBar.error("启动失败", err, duration=8000, parent=self.window())
            return
        self._poll()

    def _on_reset_defaults(self) -> None:
        """一键回到出厂默认：核心仅双爆、有效词条 = 2、可选属性清空。

        为什么有这个按钮：勾选是**自动存盘**的，测试/试用时随手勾的几条会一直
        留着，第二天打开看着就像"默认错了"（2026-09-24 用户反馈）。
        """
        from qfluentwidgets import MessageBox  # 局部导入：只有点了才需要
        box = MessageBox(
            "恢复默认设置？",
            "核心属性将回到「暴击 + 暴击伤害」，有效词条数回到 "
            f"{DEFAULT_VALID_COUNT}，可选属性清空；\n"
            "双爆下限、满值保护等开关也一并回到默认值。",
            self.window(),
        )
        if not box.exec():
            return
        # set_settings 内部有自己的回填保护，不会把"正要写进去的值"当成用户改动
        self._apply_settings(EchoSettings())
        self._save_settings()
        self._append("已恢复默认设置：" + self._settings.describe())
        InfoBar.success("已恢复默认", "核心属性：暴击、暴击伤害；有效词条 ≥"
                        f"{DEFAULT_VALID_COUNT}", duration=3000, parent=self.window())

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            self._append("停止失败：" + err)
            InfoBar.warning("停止失败", err, duration=8000, parent=self.window())
        else:
            self._append(">>> 已请求停止")

    def _on_skip(self) -> None:
        """★ 工具页「跳过」按钮 —— 跳过当前正在强化的声骸。

        ## 用户 2026-10-30

        > 这个跳过可以加到声骸自动强化工具这里

        语义（同一轮确认）：

        > 跳过相当与他已经强化好了，需要跳过同类型同名声骸

        所以按一下 = 把这个声骸**当成已强化好**：
        ① 跳过它本身；② 之后同名同类型的（含「异相」版）都跳过；
        ③ 成套模式下计入该 Cost 档的种类数。

        ## 实现

        界面线程碰不到引擎线程里那个任务实例，所以走宿主中转：
        ``host.request_skip_current()`` 置一次性标志，
        任务在下一个检查点取走
        （见 ``okww_task._consume_skip_request``）。

        ⚠ 有 1~2 秒延迟（等任务到检查点），不是瞬间中断。
        """
        if not hasattr(self._host, "request_skip_current"):
            InfoBar.warning("跳过不可用", "宿主还没加载完引擎",
                            duration=4000, parent=self.window())
            return
        try:
            ok = self._host.request_skip_current()
        except Exception as exc:  # noqa: BLE001 - 按钮不该把界面搞崩
            InfoBar.warning("跳过失败", f"{type(exc).__name__}: {exc}",
                            duration=6000, parent=self.window())
            return
        if ok:
            self._append(">>> 已请求跳过当前声骸（等任务到检查点）")
        else:
            InfoBar.warning(
                "没有可跳过的任务",
                "当前没有正在跑的「声骸自动强化」任务",
                duration=4000, parent=self.window())

    # ---------------------------------------------------------------- 轮询
    def _notify_auto_stop(self) -> None:
        """★ 自动停止时通知用户（托盘气泡 + 应用内提示）。

        用户 2026-10-10 要求："出现符合条件声骸自动停止 … **并通知**"。

        ## ⚠ 为什么两种都发

        用户跑这个工具时**多半在看游戏**（工具页在后台）——
        只弹 InfoBar 他看不见（那是窗口内的提示）。所以:

        * **托盘气泡** —— 窗口最小化/被游戏盖住也能看到；
        * **InfoBar** —— 他切回工具箱时，窗口里也有个明确的落点。

        ⚠ 只报**一次**：轮询每 300ms 跑一次，而 ``已自动停止`` 这个 info 键
        会一直是 True —— 不记状态的话会每 300ms 弹一次气泡（刷屏）。
        """
        task = self._host.find_task(TASK_KEY)
        info = getattr(task, "info", None) if task is not None else None
        if not isinstance(info, dict):
            return
        if not info.get("已自动停止"):
            return                          #: 没停 → 什么都不做

        reason = str(info.get("自动停止原因") or "").strip()
        if not reason or reason == self._auto_stop_reported:
            return                          #: 已经报过这一条了
        self._auto_stop_reported = reason

        title = "出现符合条件的声骸"
        self._append(f"★ {reason} —— 任务已暂停，请在游戏里确认")
        #: ① 托盘气泡（窗口不在前台也能看到）
        try:
            from ....gui import tray as tray_mod

            tray_mod.notify(title, reason + "\n任务已暂停，回到游戏确认后继续")
        except Exception:  # noqa: BLE001 - 气泡发不出去不该影响任务
            logger.debug("托盘气泡通知失败", exc_info=True)
        #: ② 应用内提示（切回窗口时的落点）
        try:
            InfoBar.success(title, reason, duration=15000, isClosable=True,
                            position=InfoBarPosition.TOP_RIGHT,
                            parent=self.window())
        except Exception:  # noqa: BLE001
            logger.debug("InfoBar 通知失败", exc_info=True)

    def _poll(self) -> None:
        """照「4C 自动战斗」那套：状态从宿主读，页面不自己维护线程。"""
        # 「引擎就绪后才开任务」那条路以前只有日志，页面上看不到 ——
        # 用户会以为"点了运行没反应"。这里把它捞出来弹一次。
        start_error = self._host.take_start_error()
        if start_error:
            self._append("启动失败：" + start_error)
            InfoBar.error("启动失败", start_error, duration=12000, parent=self.window())

        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error
        key = TASK_KEY if (running == TASK_KEY or pending == TASK_KEY) else None

        # 跑起来之后持续抄统计（结束/被 disable 之后就取不到了）
        if key:
            task = self._host.find_task(key)
            if task is not None:
                self._last_stats = _snapshot_task_stats(task)
            self._task_seen = True
            self._update_report_card(_format_report(self._last_stats))
            self._update_echo_cards(self._last_stats.get("qualifying"))
            self._notify_auto_stop()

        if state != self._last_state:
            if err and state == "error":
                self._append("引擎启动失败：" + err)
                InfoBar.error("引擎启动失败", err, duration=8000, parent=self.window())
            elif state == "booting" and (pending == TASK_KEY or not pending):
                self._append("引擎：后台加载 ok-ww 运行时…（首次加载 OCR 模型会慢一些）")
            elif state == "running" and key:
                self._append("引擎：运行中 —— 声骸自动强化")
            elif state == "ready" and self._last_state in ("running", "booting"):
                if self._task_seen:
                    # 只有真的跑过本页任务才算「结束」。引擎自启完成（booting→ready、
                    # 从没跑过任务）也走这条状态迁移 —— 之前在这里误弹了
                    # 「[声骸强化] 任务结束」，用户莫名其妙（2026-09-24）。
                    report = _format_report(self._last_stats)
                    first_line = report.splitlines()[0]
                    self._append("任务结束：" + report.replace("\n", "；"))
                    InfoBar.success("声骸强化结果", first_line, duration=10000,
                                    parent=self.window())
                    self._update_report_card(report)
                    #: ★★★ 2026-10-28 用户：「结果报告 … 也加上历史记录」
                    #:
                    #: 落一条到本地历史（``<用户数据>/echo_enhance_history.json``），
                    #: 刷新页面底部那张历史卡片。
                    #:
                    #: ⚠ 放在「任务**真正结束**」这个分支里，不能放运行中 ——
                    #: 运行中每 300ms 都会进上面 ``if key:`` 那段，
                    #: 在那里落历史会把文件刷爆（一次跑几十分钟 = 上万条）。
                    self._record_history()
                    self._task_seen = False
                    self._last_stats = {}
                elif self._last_state == "booting":
                    self._append("引擎就绪（本次没有跑任务）")
            self._last_state = state

        self._was_running = bool(running)
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(bool(running) or bool(pending))
        #: ★ 「跳过」只在**任务真在跑**时可用（没在跑就无物可跳）
        self.skip_button.setEnabled(bool(running))
        #: ★ 「继续」只在**任务被暂停**时可用（见 _task_paused）
        paused = self._task_paused()
        self.resume_button.setEnabled(paused)
        self._was_paused = paused

        # 一次性任务跑完把状态拉回 ready
        self._host.poll_done()

    def _task_paused(self) -> bool:
        """本页的任务现在是不是**暂停**状态。

        自动停止用的是 ``task.pause()``，它把 ``task._paused`` 置真
        （``ok.task.task.BaseTask.pause``）—— 读那个属性就知道要不要点亮「继续」。
        拿不到任务（没在跑 / 已结束）就是 False。
        """
        try:
            task = self._host.find_task(TASK_KEY)
            return bool(task is not None and getattr(task, "paused", False))
        except Exception:  # noqa: BLE001 - 读不到就算没暂停
            return False

    def _on_resume(self) -> None:
        """★ 继续：把自动暂停的任务放回去接着跑。

        走 ok-ww 自己的 ``task.unpause()``（它会把 ``_paused`` 置假、
        ``executor.start()`` 唤醒执行线程）—— 和它 GUI 里那个"继续"按钮
        是同一条路。**不自己造恢复逻辑**。
        """
        task = self._host.find_task(TASK_KEY)
        if task is None:
            InfoBar.warning("没有可继续的任务", "任务已经结束了",
                            duration=5000, parent=self.window())
            return
        try:
            task.unpause()
        except Exception as e:  # noqa: BLE001 - 恢复失败要说清楚，别静默
            self._append(f"继续失败：{type(e).__name__}: {e}")
            InfoBar.error("继续失败", str(e), duration=8000, parent=self.window())
            return
        self._append("已继续（从自动暂停处接着强化）")
        InfoBar.success("已继续", "接着强化剩下的声骸", duration=5000,
                        parent=self.window())
        self._poll()



# --------------------------------------------------------------------- 任务流程适配

class OkwwTaskRunner:
    """把 ok-ww 宿主上的任务包装成「任务流程」能用的 runner。

    任务流程是**同步**调 ``runner.run()`` 的（它自己跑在 QThread 里），
    所以这里就阻塞轮询宿主，直到任务跑完或被要求停止。
    """

    #: 轮询间隔（秒）
    POLL = 0.3

    #: 「交给引擎后多久还没开始跑」的上限（秒）。
    #:
    #: ★ 2026-09-27 用户报「应用卡死」就是栽在这里。引擎把任务排进队列之后
    #: （ok 日志里的 ``queued onetime_task``），紧接着本该出现
    #: ``get queued onetime_task`` —— 那是 executor 线程真把它取走了。
    #: 那天 ``get queued`` 一直没出现：任务排了队，但引擎的 executor 线程没起来，
    #: 于是下面这个 while **永远转下去**，界面上永远「运行中」、停止也没用 ——
    #: 用户看到的就是"卡死"。
    #:
    #: 与其无限等，不如到点认账并说清楚。
    START_TIMEOUT = 60.0

    #: 心跳日志间隔（秒）：长任务期间让日志里能看到"还活着、在等什么"。
    HEARTBEAT = 10.0

    def __init__(self, judge_config: JudgeConfig, *, log=None, should_stop=None,
                 allowed_echoes=None, picks_by_cost=None, set_plan=None,
                 designated_only: bool = False):
        #: 判定条件（工具页存下来的那份）。**公开字段**：任务流程的回归测试会读它，
        #: 确认"从任务页跑"和"从工具页点运行"用的是同一套规则。
        self.judge_config = judge_config
        self._log = log or (lambda msg: None)
        self._should_stop = should_stop or (lambda: False)
        #: ★ 2026-10-29 声骸白名单（来自编排里挂的「角色声骸筛选配置」）。
        #:
        #: 空集合 = 不过滤（没挂配置时就是空的，保持原行为）。
        #: 非空 = 只强化名单里的声骸，名单外的直接跳过。
        #: 见 ``okww_task._skip_reason`` 与 ``_allowed_echo_names``。
        self.allowed_echoes: set[str] = set(allowed_echoes or ())
        #: ★ 声骸按 Cost 分组（``{4: [...], 3: [...], 1: [...]}``）——
        #: 任务侧用它建「名字 → Cost」反查表（不用 OCR 读「COST 3」那行）。
        self.picks_by_cost: dict = dict(picks_by_cost or {})
        #: ★ 成套声骸结构 ``{Cost: 需要几种不同名字}``；空 = 不成套。
        self.set_plan: dict = dict(set_plan or {})
        #: ★★★ 2026-11-04 指定声骸强化模式（用户原话：
        #: 「增加【指定声骸强化】功能，即实现用户鼠标选中了哪个声骸就强化哪个声骸，
        #: 强化完或强化好了就停止」）。
        #:
        #: True 时：
        #:   * 不点第一格、不扫 18 格、不按白名单/成套跳过 ——
        #:     就强化玩家用鼠标点中的那个
        #:   * 处理完一个（锁定或弃置）立刻结束，不找下一个
        #:   * 「自动停止」即使开着也不 ``pause()``（会把 executor 停死）
        #:
        #: 传给 ``okww_task`` 靠两个东西：字段 ``_designated_mode``
        #: 和常量 ``DESIGNATED_ECHO_FLAG``（见 ``_configure``）。
        self.designated_only: bool = bool(designated_only)

    def run(self) -> "RunnerSummary":
        import time

        host = get_host()
        err = host.start_task(TASK_KEY, configure=self._configure)
        if err:
            raise RuntimeError(err)
        self._log("声骸自动强化：已交给 ok-ww 引擎（按「停止」可中断）")

        last_info: dict = {}
        last_stats: dict = {}
        #: 引擎真的开始跑了吗（``task.running`` 变 True 过）。
        #: 用它区分"还在等引擎"和"已经在强化中"—— 后者再久也不该超时。
        started = False
        queued_at = time.monotonic()
        last_beat = queued_at
        try:
            while True:
                task = host.find_task(TASK_KEY)
                if task is not None:
                    info = getattr(task, "info", None)
                    if isinstance(info, dict) and info:
                        last_info = dict(info)
                    last_stats = _snapshot_task_stats(task)
                    if getattr(task, "running", False):
                        started = True
                host.poll_done()
                if self._should_stop():
                    host.stop_task()
                    self._log("声骸自动强化：已请求停止")
                    break
                if host.running_task != TASK_KEY and host.pending_start != TASK_KEY:
                    break

                now = time.monotonic()
                if not started and now - queued_at > self.START_TIMEOUT:
                    host.stop_task()
                    raise RuntimeError(
                        "已把任务交给 ok-ww 引擎，但 %.0f 秒过去它还没开始跑"
                        "（任务排在队列里，引擎的执行线程没把它取走）—— "
                        "本次没有真正强化任何声骸，已中止等待。"
                        "引擎侧日志见 data/okww/logs/ok-ww.log"
                        % self.START_TIMEOUT)
                if now - last_beat >= self.HEARTBEAT:
                    last_beat = now
                    self._log("… 等待引擎：已 %.0f 秒（%s）"
                              % (now - queued_at,
                                 "任务已在跑" if started else "任务还没被引擎取走"))
                time.sleep(self.POLL)
        except Exception:
            host.stop_task()
            raise

        kept = last_info.get("成功声骸数量") or 0
        dropped = last_info.get("失败声骸数量") or 0
        #: ★ 2026-10-28：如果这次是「出现符合条件的声骸」自动结束的，
        #: 在汇总里说清楚 —— 否则用户在流程报告里只看到"完成"，
        #: 不知道这一步是**打到了目标才停**，会以为是被中断了。
        #: 用户明确说过「不用确认，记录」，所以这里只记录不阻塞。
        reason = str(last_info.get("自动停止原因") or "").strip()
        if reason:
            self._log(f"本步骤自动结束：{reason}")
        #: ★ 2026-10-30 用户：「任务里也是一样」（要展示强化好的声骸图片）
        #:
        #: 把这一轮符合条件的声骸清单带出去，任务页「本轮报告」据此画卡片。
        #: ``last_info`` 是轮询过程中抄下来的 info 快照（任务被 disable 之后
        #: 就读不到了，所以必须用这份快照）。
        #:
        #: ⚠ 只挑需要的字段 —— info 里那份可能带别的东西，
        #: 全塞进来会让流程报告的 JSON 膨胀。
        from .okww_task import QUALIFYING_INFO_KEY  # noqa: PLC0415

        qualifying = [
            {
                "index": it.get("index"),
                "image": str(it.get("image") or ""),
                "stats": [str(s) for s in (it.get("stats") or [])],
                "perfect": bool(it.get("perfect")),
            }
            for it in (last_info.get(QUALIFYING_INFO_KEY) or [])
            if isinstance(it, dict)
        ]
        return RunnerSummary(
            kept=kept, dropped=dropped,
            checked=last_stats.get("checked", 0),
            perfect=last_stats.get("perfect"),
            tally=last_stats.get("tally") or {},
            note=reason,
            qualifying=qualifying,
        )

    def _configure(self, task) -> None:
        task.judge_config = self.judge_config
        #: ★★★ 2026-10-29 把声骸白名单注入任务。
        #:
        #: 用户：「配置哪里我不是勾选了声骸吗……比如强化好了一个
        #: 融躯战士 1C，那么就跳过他」
        #:
        #: 任务侧 ``_skip_reason`` 会看这个集合：名字不在里面的
        #: （= 配置没勾的声骸，如「融躯战士」）直接解锁跳过，不判定。
        #:
        #: ⚠ 空集合 = **不过滤**（没挂筛选配置时就是空的）。
        #: 所以这里不用判断"有没有"，直接赋过去就行。
        try:
            from . import same_echo  # noqa: PLC0415

            names = {same_echo.normalize_echo_name(n)
                     for n in self.allowed_echoes if n}
            setattr(task, "_allowed_echoes", names)
            #: ★★ 2026-10-30 诊断：证明 `_configure` **真的执行了**。
            #:
            #: 实机排查时发现：GUI 日志显示"白名单 6 个"，
            #: 但任务里 `[fm#] 白名单=0个 成套=False` —— 说明注入没生效。
            #: 打这行就能确认是"没执行"还是"执行了但值不对"。
            #:
            #: ⚠ 同时写进**任务自己的 info**（`task.info_set`），
            #: 那样会出现在 ok-ww 的日志里 —— 和 `[fm#]` 在同一个文件，
            #: 对比起来最直接。
            try:
                task.info_set("注入状态",
                              f"白名单 {len(names)} 个 / 成套 "
                              f"{dict(self.set_plan or {})} / "
                              f"task#{id(task)}")
            except Exception:  # noqa: BLE001
                pass
            #: ★★★ 2026-10-30 **立刻回读**，验证 setattr 是否真的生效。
            #:
            #: 这是唯一能区分"注入了但被覆盖" 和 "注入失败" 的手段：
            #: 同一行代码里写完马上读，如果读出来是空，说明
            #: `MyToolsEnhanceEchoTask` 上有 `__slots__` 或
            #: 属性被 `@property` 拦截了。
            _readback = getattr(task, "_allowed_echoes", None)
            logger.info(
                "【注入】白名单 %d 个 → task#%s；回读=%s；set_plan=%r",
                len(names), id(task),
                len(_readback) if _readback is not None else "None",
                dict(self.set_plan or {}))
        except Exception:  # noqa: BLE001 - 注入失败不该挡住启动
            logger.warning("注入声骸白名单失败", exc_info=True)
        #: ★★★ 2026-10-29 成套声骸（43311 / 44111）：
        #: 注入「套装结构」+「名字 → Cost 反查表」。
        #:
        #: 任务侧据此判断：某档凑够要求的种类数后，
        #: 该档剩余的同类型声骸全部跳过（见 ``_skip_reason``）。
        #:
        #: ⚠ ``_build_cost_index`` 会打一行日志（"声骸 Cost 索引：4C×1、3C×2…"），
        #: 出问题时能一眼看出反查表建对了没有。
        try:
            setattr(task, "_set_plan", dict(self.set_plan or {}))
            setattr(task, "_set_done", set())
            if hasattr(task, "_build_cost_index"):
                task._build_cost_index(self.picks_by_cost or {})
        except Exception:  # noqa: BLE001 - 注入失败不该挡住启动
            logger.warning("注入成套声骸参数失败", exc_info=True)
        #: ★ 2026-10-28 用户：「任务里我要让他切换到强化另一种声骸」
        #:
        #: 打上「这是任务流程起的」标记 —— 任务侧看到它就把
        #: 「符合条件后」的收尾从 ``pause()``（永久卡住流程）
        #: 换成 **停止当前步骤**（流程才能走下一步）。
        #: 详见 ``okww_task._auto_stop_if_needed`` 的说明。
        try:
            from .okww_task import FLOW_MODE_FLAG  # noqa: PLC0415

            setattr(task, FLOW_MODE_FLAG, True)
        except Exception:  # noqa: BLE001 - 打标记失败不该挡住启动
            logger.warning("给任务打「流程模式」标记失败", exc_info=True)
        #: ★★★ 2026-11-04 指定声骸强化模式（见 ``OkwwTaskRunner.designated_only``）。
        #:
        #: 两处都设：
        #:   * ``_designated_mode`` —— 任务侧所有分支实际读的字段
        #:     （``select_0_level_echo`` / ``lock_and_esc`` / ``_auto_stop_if_needed``）
        #:   * ``DESIGNATED_ECHO_FLAG`` 常量名 —— 和 ``FLOW_MODE_FLAG`` 一样的
        #:     诊断/回读机制，将来别的工具也能用 ``getattr(task, 常量, False)`` 判模式
        if self.designated_only:
            try:
                from .okww_task import DESIGNATED_ECHO_FLAG  # noqa: PLC0415

                setattr(task, DESIGNATED_ECHO_FLAG, True)
                setattr(task, "_designated_mode", True)
                #: ★★★ 2026-11-05 用户：「这个【指定声骸】其实你已经做到了，
                #: 我鼠标停在哪个位置，你就强化那个……其他的应该跟正常强化
                #: 一样的，强化好了就停止或者强化完这个声骸停止，你这里是
                #: 强化完一个就停了」
                #:
                #: 指定模式关掉「有效词条数上限」的**提前弃置** —— 否则只开了
                #: 3 孔、有效 0 条时它会算「0 + 剩余 2 = 2 < 要求 3」当场弃置，
                #: 永远走不到满 5 条（``stats.judge`` 第 4 条）。关掉后一路打到
                #: 满级再判，满级那块自己会补同样的判断（够就 lock、不够就
                #: discard），不会把废声骸锁住。
                #:
                #: 普通强化模式不受影响（``strict_valid_cap`` 默认 True）。
                import dataclasses as _dc  # noqa: PLC0415

                task.judge_config = _dc.replace(
                    task.judge_config, strict_valid_cap=False)
                task.info_set("指定强化", "开（只强化玩家选中的那个声骸）")
                logger.info("【注入】指定声骸强化模式 → task#%s", id(task))
            except Exception:  # noqa: BLE001 - 打标记失败不该挡住启动
                logger.warning("给任务打「指定强化」标记失败", exc_info=True)


class RunnerSummary:
    """任务流程要的 ``.summary()`` 接口。"""

    def __init__(self, *, kept: int, dropped: int, checked: int = 0,
                 perfect: int | None = None, tally: dict[str, int] | None = None,
                 note: str = "", qualifying: list[dict] | None = None):
        self.kept = kept
        self.dropped = dropped
        #: 判定的声骸总数 / 满属性数（未启用满值保护时为 None）/ 弃置原因分布
        self.checked = checked
        self.perfect = perfect
        self.tally = dict(tally or {})
        #: ★ 2026-10-28：本步骤**为什么提前结束**（「出现符合条件的声骸」那种）。
        #: 用户要求「不用确认，记录」—— 就记在流程报告的这一步后面。
        self.note = str(note or "")
        #: ★ 2026-10-30 用户：
        #:
        #: > 任务里也是一样（要展示强化好的声骸图片）
        #:
        #: 这一步符合条件的声骸清单。任务页「本轮报告」据此画卡片
        #: （和工具页「结果报告」是同一套卡片控件）。
        #:
        #: 每项 ``{"index", "image", "stats", "perfect"}``，
        #: 只存截图文件名（不存绝对路径，换机器也能用）。
        self.qualifying: list[dict] = [
            dict(it) for it in (qualifying or []) if isinstance(it, dict)]

    def summary(self) -> str:
        text = format_result_report(
            checked=self.checked, kept=self.kept, dropped=self.dropped,
            perfect=self.perfect, tally=self.tally)
        note = _short_note(self.note)
        if note:
            #: 接在统计后面，**用「 —— 」分隔、不再包括号**。
            #:
            #: ⚠ 2026-10-30 用户截图报「括号糊成一团」：
            #: note 自己就带括号（"出现符合条件的声骸（第 2 个）：…"），
            #: 再包一层就成了「（…（第 2 个）：…）」，读起来像嵌套。
            #: 用破折号分隔既清楚又不会嵌套。
            text = f"{text} —— {note}"
        return text


#: note 太长的截断长度（完整内容在日志里）
NOTE_LIMIT = 40


def _short_note(note: str) -> str:
    """把「自动停止原因」压成**一句话**，别把整段报告塞进括号。

    ## 修的是什么（2026-10-29 用户截图）

    主动停止后，流程报告那行变成了这样（括号糊成一团）::

        …判定 121 个 · 符合条件 2 · 弃置 27 · 满属性 1
        弃置原因：有效词条不足 5、凑不齐核心属性 18、双爆不达标 4
        （出现符合条件的声骸（第 2 个）：攻击百分比 6.4、…、重击伤害加成 7.9））

    原因链条（**三层括号**）::

        ① 任务把 info["自动停止原因"] 设成
           "出现符合条件的声骸（第 2 个）：攻击百分比 6.4、…"
           ← 这一层括号是**数据本身**带的
        ② RunnerSummary.summary() 又包一层 "（note）"
        ③ FlowRunThread 主动停止时把 summary **整个**塞进 note，
           再交给 _finish → 报告里再显示一遍

    ## 两道修复

    1. ``summary()`` 里**改用 ``——`` 分隔**，不再包括号（见那里的注释）；
    2. 这里只留**简短原因**：
         * 去掉首尾多余的括号
         * 太长就截断（超过 :data:`NOTE_LIMIT` 字加省略号）
         * 空串照旧返回空
    """
    text = str(note or "").strip()
    if not text:
        return ""
    #: 剥掉可能已经带的成对括号（避免「（…））」这种）
    while len(text) >= 2 and text[0] == "（" and text[-1] == "）":
        text = text[1:-1].strip()
    while len(text) >= 2 and text[0] == "(" and text[-1] == ")":
        text = text[1:-1].strip()
    #: 太长就截断（完整内容在日志里，报告里要能一眼扫过去）
    if len(text) > NOTE_LIMIT:
        text = text[:NOTE_LIMIT].rstrip() + "…"
    return text


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.GAME,
    name="声骸自动强化",
    description="按核心属性 / 双爆下限 / 可选属性 / 有效词条数，自动强化并筛选声骸",
    icon_name="GAME",
    coming_soon=False,
)
class EchoEnhanceTool(BaseTool):
    key = "echo_enhance"
    version = "0.1.0"
    supports_task_run = True
    #: 自定义图标。放一张鸣潮的图标覆盖这个文件（256x256 的 png 最好），界面会自动用它
    icon_path = str(paths.resource_dir("assets", "icons", "echo_enhance.png"))

    def create_widget(self, parent=None):
        return EchoEnhanceWidget(self.meta(), parent)

    # ---------------------------------------------------------------- 任务系统
    def create_task_runner(self, options: dict, log, should_stop):
        """给「任务流程」用：把 ok-ww 宿主上的声骸强化任务包装成同步 runner。

        ## ★ 判定条件从哪来（用户 2026-09-26）

        用户要求："**声骸自动工具会启用声骸强化配置的条件进行强化**"。

        * 编排里挂了「角色声骸强化配置」→ **用它的条件**（见 :meth:`_settings_for_run`）；
        * 没挂 → 退回工具页保存的那份（"从任务页跑"和"从工具页点运行"仍然一致）。

        ## ★ 声骸白名单（2026-10-29）

        用户：「配置哪里我不是勾选了声骸吗，可以准确识别出声骸名和声骸类型
        （4C、3C、1C），我想要实现比如强化好了一个 融躯战士 1C……
        那么就跳过他」

        → 把编排里挂的「角色声骸筛选配置」勾选的那些声骸名，作为**白名单**
        传给任务（``task._allowed_echoes``）。名单外的声骸（如没勾的
        「融躯战士」）会被直接解锁跳过，一个判定都不做。

        **没挂筛选配置 → 白名单为空 → 不过滤**（保持原行为）。
        """
        settings, source = self._settings_for_run(options, log)
        log(f"判定配置（{source}）：{settings.describe()}")
        #: ★★★ 2026-11-04 指定声骸强化：这条路上**白名单/成套都不参与** ——
        #: 玩家已经用鼠标点名了要强化的那个，工具再去按名单筛就是反着来。
        #: 判定条件（核心属性/双爆/满值锁定…）照旧生效，只是"选中谁"改成玩家决定。
        designated = bool(options.get("designated"))
        if designated:
            log("【指定强化】只强化你鼠标选中的那个声骸，处理完就停"
                "（不按白名单/成套筛选，也不会替你换目标）")
            return OkwwTaskRunner(settings.to_judge_config(), log=log,
                                  should_stop=should_stop, designated_only=True)
        #: 取编排里挂的筛选配置 → 勾选的声骸名
        allowed: set[str] = set()
        #: 声骸名 → Cost（成套声骸判断用）
        picks_by_cost: dict = {}
        #: 套装结构 ``{Cost: 需要几种}``；空 = 不成套
        set_plan: dict = {}
        try:
            loadout = _bound_loadout(options)
            if loadout is not None:
                allowed = _allowed_echo_names(loadout)
                picks_by_cost = _picks_by_cost(loadout)
                if allowed:
                    log(f"声骸白名单（{len(allowed)} 个）："
                        + "、".join(sorted(allowed)))
                else:
                    log("⚠ 筛选配置里没勾任何声骸 → 不做白名单过滤")
            else:
                log("⚠ 编排里没挂「角色声骸筛选配置」→ 不做声骸白名单过滤"
                    "（配置里没勾的声骸也会被强化）")
        except Exception:  # noqa: BLE001 - 读不到就当没配，不该挡住启动
            logger.warning("读声骸白名单失败", exc_info=True)

        #: ★ 2026-10-29 从**流程名**读套装结构
        #: （``绯雪-声骸自动强化（小毕业 43311）`` 里的 43311）
        try:
            plan_name = _set_plan_of_flow(options.get("flow_name") or "")
            if plan_name:
                set_plan = dict(SET_BONUS_PLANS.get(plan_name) or {})
                if set_plan:
                    log(f"成套声骸 {plan_name} → " + "、".join(
                        f"{c}C 需要 {n} 种" for c, n in
                        sorted(set_plan.items(), reverse=True)))
                else:
                    log(f"⚠ 认不出套装结构「{plan_name}」→ 按不成套处理")
        except Exception:  # noqa: BLE001
            logger.warning("读套装结构失败", exc_info=True)

        return OkwwTaskRunner(settings.to_judge_config(), log=log,
                              should_stop=should_stop, allowed_echoes=allowed,
                              picks_by_cost=picks_by_cost, set_plan=set_plan,
                              designated_only=bool(options.get("designated")))

    def _settings_for_run(self, options: dict, log):
        """本次运行用哪套判定条件 → ``(EchoSettings, 来源说明)``。

        **优先用编排里挂的「角色声骸强化配置」** —— 一条流程可以按角色不同挂不同条件
        （比如"绯雪这条严格、清宵那条宽松"）。找不到配置（被删了）就打一声、退回工具页那份。

        配置的 key 是 ``EchoProfile.id``（**稳定 id**，改名也不变）；
        兼容 09-26 之前存的、按角色名指的老流程（``by_id`` 找不到再按名字试）。
        """
        keys = list(options.get("config_keys") or [])
        kinds = list(options.get("config_kinds") or [])
        names = list(options.get("configs") or [])
        for index, key in enumerate(keys):
            kind = kinds[index] if index < len(kinds) else ""
            if kind != ECHO_PROFILE_KIND:
                continue
            profile = _find_echo_profile(key)
            if profile is None:
                shown = names[index] if index < len(names) else key
                log(f"⚠ 编排里挂的强化配置「{shown}」已经找不到了 —— 改用工具页保存的设置")
                continue
            try:
                return EchoSettings.from_dict(profile.settings), f"编排里挂的「{profile.name}」"
            except Exception:  # noqa: BLE001 - 配置坏了不该把任务带崩
                logger.warning("强化配置读不出来：%s", key, exc_info=True)
                log(f"⚠ 编排里挂的强化配置「{profile.name}」读不出来 —— 改用工具页保存的设置")
        return EchoSettings.load(), "工具页保存的设置"

    def create_task_prep(self, options: dict, log, should_stop):
        """「开始」步的准备动作（用户 2026-09-26 第 (1) 条）：

        > **可以按照声骸筛选配置，按 B 打开背包筛选指定的声骸**

        做三件事：

        1. 读**编排里挂的「角色声骸筛选配置」**（``Loadout``），把这次要筛的目标
           （套装 / 各档声骸）打进日志 —— 让用户看到"这次要筛什么"；
        2. **按 B 打开背包**（这一步是**已验证**的）；
        3. 剩下的「切声骸页签 / 开过滤器 / 筛未调谐 / 按等级排序」**还没校准**，
           默认**跳过不去点**（见 ``prepare.py`` 顶部：猜坐标可能触发分解、弃置这类
           破坏性操作），改为跑一次**探测**：把当前画面 + OCR 出来的每行文字/坐标
           落到 ``data/probe/``，拿那张图就能把待校准的步骤填成真的。
        """
        settings, source = self._settings_for_run(options, log)
        log(f"判定配置（{source}）：" + settings.describe())

        #: ★★★ 2026-11-04 指定声骸强化：**准备动作全部跳过**。
        #:
        #: 玩家是自己用鼠标在背包里点好那个声骸才点「指定强化」的 ——
        #: 这时候再去按 B 开背包、切页签、点筛选条件、改排序，
        #: 会把他辛辛苦苦筛好的界面弄乱，光标也一起丢。
        #: 所以这里直接返回一个什么都不做的 prep（``EchoPrep(steps=[])``）。
        if options.get("designated"):
            log("【指定强化】跳过准备动作（不按 B、不重筛）—— 直接用你当前选中的界面")
            from .prepare import EchoPrep  # noqa: PLC0415

            return EchoPrep(log=log, should_stop=should_stop, steps=[])

        target = _bound_loadout(options)
        if target is not None:
            # ⚠ 别写成 f"{len(picks)}{cost}C" —— 拼出来是「14C」，看着像 14C 档
            want = "、".join(
                f"{cost}C×{len(picks)}" for cost, picks in _loadout_picks(target).items()
            )
            log(f"筛选目标（来自「{target.character}-声骸筛选」）："
                f"套装「{target.echo_set}」" + (f"；各档 {want}" if want else ""))
        else:
            # ⚠ 这句话必须说清楚**后果**和**怎么办**。
            #   用户 2026-09-27 报「没有按流程 筛选声骸→强化声骸，而是直接强化声骸」
            #   —— 就是这条：没挂配置 → 只按 B → 没筛 → 直接把界面交给 ok-ww。
            #   原来的文案「请自己筛好」太轻，看不出"工具根本不会筛"。
            log("⚠ 编排里没挂「角色声骸筛选配置」→ 本次**不会自动筛选**"
                "（只会按 B 打开背包）。ok-ww 会以「必须在背包声骸界面过滤后开始!」"
                "拒绝执行。要让工具自动筛，请在编排里挂上「角色声骸筛选配置」。")

        from .prepare import EchoPrep, build_filter_steps  # noqa: PLC0415

        # 挂了筛选配置 → 按它生成"切声骸页 / 开筛选 / 选状态·品质·合鸣 / 排序"那一串；
        # 没挂 → 用默认步骤（只按 B 开背包 + 未校准的跳过），不猜。
        steps = build_filter_steps(target) if target is not None else None
        if steps is not None:
            log(f"准备动作共 {len(steps)} 步（切页签 / 开筛选 / 选条件 / 关面板 / 排序）")
        return EchoPrep(log=log, should_stop=should_stop, steps=steps)
