# -*- coding: utf-8 -*-
"""查缺补漏 —— 工具页：**上传视频** → 建参考库 → 标定 → 试跑。

## 用户要的是什么

原话：**"我上传一个视频，你能跟着视频做"**

所以这一页的核心动作就是**上传一个视频**，然后机器跟着它走。
不是读什么官方数据 —— 视频就是唯一的输入。

## ★ 一个视频 = 一条路线 = 一份库

⚠ 原来的实现里库是**一个固定文件名**，于是上传第二个视频会把
第一个**覆盖**掉。现在改成按视频分开存（见
:mod:`src.core.explore_gap.catalog`）：:

    <用户数据>/explore_gap/
        ├── 无光之森找宝箱_a1b2c3.npz
        └── 七丘声匣_d4e5f6.npz

上传方式两种都给：**拖进来** 或 **点按钮选文件**。
（拖放对"我上传一个视频"这个动作最自然。）

## ⚠ 建库是重活

27 分钟视频实测 **77 秒**（顺序读 3280 帧 + 算描述子），
所以必须放后台线程，否则界面卡死。

## 流程拆成三步，每步都能单独验

    ① 上传 + 建参考库   （离线，几分钟）  → 一个 .npz
    ② 标定转向          （开游戏，一两分钟）→ 量出秒/像素
    ③ 试跑              （开游戏）        → 看走得像不像
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    TitleLabel,
)

from ....core import notify, paths
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

#: 认哪些视频扩展名（拖放时用来判断"这是不是视频"）
VIDEO_SUFFIXES = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm")

#: 拖放/选择框用的过滤器
VIDEO_FILTER = "视频 (*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.webm)"

#: 上传区没东西时的提示
DROP_HINT = "把视频拖到这里，或点「选择视频」"


def looks_like_video(path: str) -> bool:
    """看着像不像视频（只按扩展名，不读文件头）。

    单独一个函数是因为拖放和选择框**两条路都要用同一个判断** ——
    两份实现迟早不一致（一个收 mkv、一个不收）。
    """
    return Path(str(path)).suffix.lower() in VIDEO_SUFFIXES


class BuildThread(QThread):
    """后台建库（几分钟，必须后台）。

    ★ 建库时**顺便学按键**（同一遍扫描，不多读一次视频）——
    这是"照视频做操作"的前提。没有按键表的话，机器只会
    转视角 + 一直按 W，遇到飞/解谜/长按机关/对话分支就卡住。
    """

    progress = Signal(int, int)
    done = Signal(object, str)          #: (library 或 None, 错误消息)
    #: 建好并存盘后的库路径（给界面刷新列表用）
    stored = Signal(str)
    #: 学按键的进度 / 结果说明
    note = Signal(str)

    def __init__(self, video: str, user_dir: str, parent=None,
                 *, learn_keys: bool = True):
        super().__init__(parent)
        self.video = video
        self.user_dir = user_dir
        self.learn_keys = learn_keys
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _key_learner(self):
        """造一个"每帧读按键提示"的回调；拿不到 OCR 就返回 ``None``。

        ⚠ **OCR 是注入的**，不是 import 死的 ——
        这样没有 ok-ww 的环境也能建库（只是学不到按键，
        跑起来只会转视角 + 按 W）。

        真正的取图判断在 :func:`src.core.explore_gap.reader.learn_from_ocr`
        —— 这里不重复实现一遍（两份实现迟早不一致）。
        """
        try:
            from ....core.explore_gap.reader import learn_from_ocr  # noqa: PLC0415
            from .ocr import make_ocr                               # noqa: PLC0415

            ocr = make_ocr()
            if ocr is None:
                self.note.emit("没找到 OCR —— 这次建库不学按键"
                               "（跑起来只会转视角 + 按 W）")
                return None
            return learn_from_ocr(ocr)
        except Exception as exc:                       # noqa: BLE001
            self.note.emit(f"学按键没启用（{type(exc).__name__}: {exc}）")
            return None

    def run(self) -> None:                          # noqa: D102
        try:
            from ....core.explore_gap import build_for   # noqa: PLC0415

            learn = self._key_learner() if self.learn_keys else None
            target, lib = build_for(
                self.video, self.user_dir,
                progress=lambda done, total: self.progress.emit(done, total),
                learn_keys=learn,
            )
        except Exception as exc:                    # noqa: BLE001
            self.done.emit(None, f"{type(exc).__name__}: {exc}")
            return
        if lib.has_keys():
            self.note.emit(lib.schedule().describe())
        elif learn is not None:
            self.note.emit("扫完了，但视频里没读到按键提示 —— "
                           "跑起来只会转视角 + 按 W")
        self.stored.emit(str(target))
        self.done.emit(lib, "")


class DropZone(QFrame):
    """拖放区：把视频拖进来即上传。

    单独一个控件是因为它要处理 Qt 的拖放事件（``dragEnterEvent`` /
    ``dropEvent``），而这些事件**只有顶层接收拖放的控件**才收得到 ——
    挂在 QLineEdit 上是不生效的（QLineEdit 自己吃掉了拖放）。
    """

    dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("videoDropZone")
        self.setAcceptDrops(True)
        #: ⚠ 原生 QFrame 会吃系统调色板底色 —— README 踩过的坑第 2 条
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(64)

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(2)
        self.hint = BodyLabel(DROP_HINT)
        self.hint.setAlignment(Qt.AlignCenter)
        box.addWidget(self.hint)
        self.detail = CaptionLabel("支持 mp4 / mkv / avi / mov …")
        self.detail.setAlignment(Qt.AlignCenter)
        box.addWidget(self.detail)

    # ------------------------------------------------------------ 拖放事件
    def dragEnterEvent(self, event):                 # noqa: N802 - Qt 命名
        if self._first_video(event) is not None:
            event.acceptProposedAction()
            self._set_hover(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):                 # noqa: N802
        self._set_hover(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):                      # noqa: N802
        self._set_hover(False)
        path = self._first_video(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.dropped.emit(path)

    def _set_hover(self, on: bool) -> None:
        """拖动悬停时给个视觉反馈（不然用户不知道能不能放这）。"""
        self.hint.setText("松手就上传" if on else DROP_HINT)

    @staticmethod
    def _first_video(event) -> str | None:
        """从拖放事件里取第一个视频文件。

        ⚠ 两个细节：

        **① 要遍历** ``mimeData().urls()``。用户可能一次拖好几个文件
        （或者拖了个文件夹），只取 ``urls()[0]`` 会挑中非视频的那个。

        **② 要转成原生路径**（``os.path.normpath``）。Qt 的
        ``url.toLocalFile()`` 在 Windows 上返回的是**正斜杠**
        （``C:/Users/...``），而文件选择框给的是反斜杠。
        两条路上传同一个文件会得到**不同的字符串** —— 后面按路径
        算库名（短哈希）时就会算出两份库。测试抓到的。
        """
        data = event.mimeData()
        if not data.hasUrls():
            return None
        for url in data.urls():
            local = url.toLocalFile()
            if local and looks_like_video(local) and os.path.isfile(local):
                return os.path.normpath(local)
        return None


class VideoRow(QFrame):
    """列表里的一行：一个已上传的视频 + 它的库状态。"""

    def __init__(self, entry, *, on_forget=None, parent=None):
        super().__init__(parent)
        self.setObjectName("videoRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(42)
        self.entry = entry

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)

        #: 能跑 = 库在 **且** 源视频在
        mark = QLabel("●" if entry.runnable else "○")
        mark.setFixedWidth(14)
        mark.setStyleSheet(
            "color: #3fbf6f;" if entry.runnable else "color: #c9a227;")
        row.addWidget(mark)

        name = StrongBodyLabel(entry.name)
        name.setMinimumWidth(160)
        row.addWidget(name)

        status = CaptionLabel(entry.status_text())
        row.addWidget(status, 1)

        forget = PushButton("移除")
        forget.setFixedWidth(64)
        forget.clicked.connect(
            lambda: on_forget(entry) if on_forget else None)
        row.addWidget(forget)


class ExploreGapPanel(QWidget):
    """查缺补漏主面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: BuildThread | None = None
        self._pending_video = ""
        self.setObjectName("VideoFollowInterface")
        self._build()
        self.refresh_list()

    # ------------------------------------------------------------- 构建界面
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(TitleLabel("查缺补漏"))
        root.addWidget(BodyLabel(
            "上传一个攻略视频，机器就跟着视频的画面走 —— "
            "不依赖世界坐标，每帧重新对齐，误差不累积。"))

        #: ① 上传
        root.addWidget(StrongBodyLabel("① 上传视频"))
        self.drop_zone = DropZone()
        self.drop_zone.dropped.connect(self.on_video_chosen)
        root.addWidget(self.drop_zone)

        pick_row = QHBoxLayout()
        pick_row.addWidget(CaptionLabel("或"))
        self.pick_button = PrimaryPushButton("选择视频…")
        self.pick_button.clicked.connect(self.pick_video)
        pick_row.addWidget(self.pick_button)
        pick_row.addStretch(1)
        root.addLayout(pick_row)

        self.video_edit = LineEdit()
        self.video_edit.setPlaceholderText("视频路径（也可以直接粘进来）")
        self.video_edit.textChanged.connect(self._on_path_typed)
        root.addWidget(self.video_edit)

        self.build_status = CaptionLabel("还没选视频")
        self.build_status.setWordWrap(True)
        root.addWidget(self.build_status)

        build_row = QHBoxLayout()
        self.build_button = PrimaryPushButton("开始建库")
        self.build_button.clicked.connect(self.start_build)
        self.build_button.setEnabled(False)
        build_row.addWidget(self.build_button)
        build_row.addStretch(1)
        root.addLayout(build_row)

        #: 已上传的视频列表
        root.addWidget(StrongBodyLabel("已上传的视频"))
        root.addWidget(CaptionLabel(
            "每个视频一份库，互不覆盖。⚠ 源视频别删/改名 —— "
            "库只存画面特征，对齐时要回源视频取帧。"))
        self._list_area = QScrollArea()
        self._list_area.setWidgetResizable(True)
        self._list_area.setFrameShape(QFrame.NoFrame)
        self._list_area.setAttribute(Qt.WA_StyledBackground, True)
        self._list_area.setStyleSheet("background: transparent;")
        self._list_area.viewport().setStyleSheet("background: transparent;")
        self._list_host = QWidget()
        self._list_host.setAttribute(Qt.WA_StyledBackground, True)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(4)
        self._list_area.setWidget(self._list_host)
        self._list_area.setMinimumHeight(120)
        root.addWidget(self._list_area, 1)

        #: ② 标定
        root.addWidget(StrongBodyLabel("② 标定转向比例"))
        root.addWidget(CaptionLabel(
            "⚠ 没标定就跑会乱走：像素→转向时长的换算取决于你的"
            "游戏灵敏度 / DPI / FOV，机器猜不出来。"))
        cal_row = QHBoxLayout()
        cal_row.addWidget(BodyLabel("当前换算（秒/像素）"))
        self.px_edit = LineEdit()
        from .executor import PX_PER_TURN_SEC       # noqa: PLC0415

        self.px_edit.setText(str(PX_PER_TURN_SEC))
        self.px_edit.setFixedWidth(120)
        cal_row.addWidget(self.px_edit)
        self.cal_button = PrimaryPushButton("自动标定")
        self.cal_button.clicked.connect(self.explain_calibration)
        cal_row.addWidget(self.cal_button)
        cal_row.addStretch(1)
        root.addLayout(cal_row)
        self.cal_status = CaptionLabel(
            "点「自动标定」看怎么做 —— 机器会自己按键并量出转动像素，"
            "不用你目测。")
        self.cal_status.setWordWrap(True)
        root.addWidget(self.cal_status)

        #: ③ 试跑
        root.addWidget(StrongBodyLabel("③ 试跑"))
        root.addWidget(CaptionLabel(
            "在「4C 自动战斗」页的工具里选「查缺补漏」运行。"
            "本页不直接驱动游戏 —— 试跑要开着游戏、还要能随时停。"))

    # --------------------------------------------------------------- 上传
    def pick_video(self) -> None:
        """弹文件选择框（"上传"的另一条路）。"""
        start = str(Path.home() / "Videos")
        if not os.path.isdir(start):
            start = str(Path.home())
        path, _selected = QFileDialog.getOpenFileName(
            self, "选择攻略视频", start, VIDEO_FILTER)
        if path:
            self.on_video_chosen(path)

    def on_video_chosen(self, path: str) -> None:
        """用户**上传**了一个视频（拖进来或选出来）。"""
        path = str(path or "").strip()
        if not path:
            return
        if not os.path.isfile(path):
            self._toast("找不到这个视频", path, error=True)
            return
        if not looks_like_video(path):
            self._toast("这看着不是视频文件",
                        f"{Path(path).suffix or '（没有扩展名）'}\n"
                        f"支持：{' '.join(VIDEO_SUFFIXES)}", error=True)
            return
        self._pending_video = path
        #: 回填到输入框（用户能看见、也能改）
        if self.video_edit.text().strip() != path:
            self.video_edit.setText(path)
        size_mb = os.path.getsize(path) / 1024 / 1024
        self.build_status.setText(
            f"已选：{Path(path).name}（{size_mb:.0f} MB）—— 点「开始建库」")
        self.build_button.setEnabled(True)

    def _on_path_typed(self, text: str) -> None:
        """手打/粘贴路径时同步状态（别让"开始建库"一直灰着）。"""
        text = text.strip()
        ok = bool(text) and os.path.isfile(text) and looks_like_video(text)
        self.build_button.setEnabled(ok)
        if ok:
            self._pending_video = text

    # --------------------------------------------------------------- 列表
    def refresh_list(self) -> None:
        """重画"已上传的视频"列表。"""
        from ....core.explore_gap import list_entries   # noqa: PLC0415

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            entries = list_entries(paths.user_data_dir())
        except Exception as exc:                    # noqa: BLE001
            self._list_layout.addWidget(
                CaptionLabel(f"列表读不出来：{type(exc).__name__}: {exc}"))
            self._list_layout.addStretch(1)
            return

        if not entries:
            self._list_layout.addWidget(
                CaptionLabel("还没有上传过视频"))
        else:
            for entry in entries:
                self._list_layout.addWidget(
                    VideoRow(entry, on_forget=self.forget_video))
        self._list_layout.addStretch(1)

    def forget_video(self, entry) -> None:
        """移除一个库（⚠ 不动源视频）。"""
        from ....core.explore_gap import forget         # noqa: PLC0415

        removed = forget(entry.library)
        if removed:
            self._toast("已移除", f"{entry.name}（源视频没动）")
        self.refresh_list()

    # --------------------------------------------------------------- 建库
    def start_build(self) -> None:
        video = (self.video_edit.text().strip() or self._pending_video)
        if not video:
            self._toast("先选一个视频", error=True)
            return
        if not os.path.isfile(video):
            self._toast("找不到视频", video, error=True)
            return
        if self._thread is not None and self._thread.isRunning():
            self._toast("正在建库，请稍等")
            return

        self.build_button.setEnabled(False)
        self.build_status.setText("正在建库…（这一步比较慢，别关窗口）")
        self._thread = BuildThread(video, str(paths.user_data_dir()), self)
        self._thread.progress.connect(self._on_progress)
        #: ★ 学按键的进度/结果要显示出来 —— 不然用户不知道
        #: "这次学没学到按键"（那决定跑起来能不能解机关）
        self._thread.note.connect(self._on_note)
        self._thread.done.connect(self._on_built)
        self._thread.stored.connect(lambda _p: self.refresh_list())
        self._thread.finished.connect(
            lambda: self.build_button.setEnabled(True))
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        pct = 100.0 * done / total if total else 0.0
        self.build_status.setText(f"正在建库… {pct:.0f}%（{done}/{total} 帧）")

    def _on_note(self, text: str) -> None:
        """建库过程中的补充说明（主要是**学按键**的结果）。"""
        self.build_status.setText(text)
        self._toast("建库", text)

    def _on_built(self, lib, error: str) -> None:
        if lib is None:
            self.build_status.setText(f"建库失败：{error}")
            self._toast("建库失败", error, error=True)
            notify.report_task_result("查缺补漏 · 建库", ok=False,
                                      detail=error)
            return
        minutes = len(lib) * lib.step / (lib.fps or 30.0) / 60.0
        text = (f"建好了：{len(lib)} 个参考帧，覆盖 {minutes:.1f} 分钟。"
                f"可以标定/试跑了。")
        self.build_status.setText(text)
        self._toast("建库完成", text)
        notify.report_task_result("查缺补漏 · 建库", ok=True, detail=text)

    # --------------------------------------------------------------- 标定
    def explain_calibration(self) -> None:
        """说明标定怎么做 —— 并强调**机器自己量**，不用人眼估。"""
        from .executor import (                      # noqa: PLC0415
            CALIBRATION_HOLDS,
            CALIBRATION_KEY,
        )

        holds = "、".join(f"{h:.2f}s" for h in CALIBRATION_HOLDS)
        text = "\n".join([
            "自动标定怎么做：",
            "1. 进游戏，站在一个**有大片场景**的地方"
            "（别对着纯色墙 / 打开着的地图界面）",
            "2. 确保「4C 自动战斗」页的引擎已经启动",
            "3. 在那边选「查缺补漏」运行，它会先做标定",
            "",
            f"机器会按 {CALIBRATION_KEY} 键若干次（{holds}），",
            "每次拍前后两帧，用相位相关量出画面横移了多少像素，",
            "再线性拟合出「秒/像素」。",
            "",
            "⚠ 实测这套测量精度是**亚像素级**（闭环残差最大 0.478px），",
            "所以比人眼估准得多。",
            "",
            "⚠ 画面里有大片 UI / 纯色时不能量 —— 那说明位置没选对。",
        ])
        InfoBar.info("自动标定", text, duration=20000, parent=self.window())

    # ------------------------------------------------------------ 生命周期
    def closeEvent(self, event):                    # noqa: N802 - Qt 命名
        """收线程（照 explore_gap 的做法，避免 Destroyed while running）。"""
        self._shutdown_thread()
        super().closeEvent(event)

    def _shutdown_thread(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._thread = None
        try:
            thread.stop()
            if thread.isRunning():
                if not thread.wait(3000):
                    thread.terminate()
                    thread.wait(1000)
        except RuntimeError:
            pass

    def _toast(self, title: str, message: str = "", *, error: bool = False):
        try:
            window = self.window()
            if error:
                InfoBar.error(title, message, duration=6000, parent=window)
            else:
                InfoBar.success(title, message, duration=6000, parent=window)
        except Exception:                            # noqa: BLE001
            pass


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.GAME,
    name="查缺补漏",
    description="上传一个攻略视频，机器跟着视频的画面走（视觉伺服，不用世界坐标）",
    icon_name="GAME",
    coming_soon=False,
)
class ExploreGapTool(BaseTool):
    key = "explore_gap"
    name = "查缺补漏"
    description = "上传攻略视频，机器跟着视频的画面走：每帧重新对齐，误差不累积"
    version = "0.1.0"
    tags = ("自动", "视频", "路线")
    coming_soon = False
    #: 可以在任务流程里跑（ok-ww 那边已注册 MyToolsExploreGapTask）
    supports_task_run = True
    icon_path = str(paths.resource_dir("assets", "icons", "explore_gap.png"))

    def create_widget(self, parent=None):
        return ExploreGapPanel(parent)
