# -*- coding: utf-8 -*-
"""「检查更新」界面 —— 配置页里的一张卡片。

## 用户要求（2026-10-05）

    "增加检查更新功能，如果有更新，可以自动更新"

## 卡片长什么样

::

    ┌───────────────────────────────────────────────┐
    │  🔄 检查更新                                   │
    │  当前版本 0.5.3                                │
    │  [检查更新]  [ ] 启动时自动检查                 │
    │  ─────────────────────────────────────────     │
    │  发现新版本 0.6.0                              │
    │  更新说明…                                     │
    │  [下载并安装]                                  │
    │  下载中 ████████░░░░░░ 62%                     │
    └───────────────────────────────────────────────┘

## ⚠ 网络活儿全在**后台线程**

``check_for_update()`` / ``download()`` 都是阻塞的（实测超时 20 秒）。
放主线程 = 界面**冻住 20 秒**。所以走 ``QThread`` + 信号回主线程。

## ⚠ "自动更新" = **自动下载 + 自动启动安装器**

不是"偷偷装"。用户点「自动更新」之后：
下载 → 校验 → 启动 Inno 安装包（它自带向导）→ 本程序退出。
**最终那一下还是用户点的**（安装器界面），只是不用自己找文件了。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import updater
from ..core import ui_state
from .compat import ScrollArea

logger = logging.getLogger(__name__)


def _settings():
    """自动检查开关存哪儿 —— 复用 ``UiState``（项目已有的设置存储）。"""
    return ui_state.UiState()


#: 自动检查的存储键
AUTO_CHECK_KEY = "update_auto_check"


class CheckThread(QThread):
    """后台查有没有新版本。"""

    done = Signal(object)                      #: updater.ReleaseInfo

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self._current = current

    def run(self) -> None:                     # noqa: D102 - QThread 接口
        try:
            info = updater.check_for_update(self._current)
        except Exception as exc:               # noqa: BLE001 - 兜底不炸线程
            logger.exception("检查更新线程炸了")
            info = updater.ReleaseInfo(
                current=self._current, error=f"检查失败：{exc}")
        self.done.emit(info)


class DownloadThread(QThread):
    """后台下载安装包。"""

    progress = Signal(int, int)                #: 已下载, 总字节（0=未知）
    done = Signal(str)                         #: 本地路径
    failed = Signal(str)                       #: 错误消息

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self) -> None:                     # noqa: D102 - QThread 接口
        try:
            path = updater.download(
                self._url,
                on_progress=lambda done, total:
                self.progress.emit(done, total))
        except Exception as exc:               # noqa: BLE001
            logger.exception("下载更新失败")
            self.failed.emit(str(exc))
            return
        self.done.emit(str(path))


class UpdateCard(QWidget):
    """★ 配置页里的「检查更新」卡片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateCard")
        self._info: updater.ReleaseInfo | None = None
        self._check_thread: CheckThread | None = None
        self._dl_thread: DownloadThread | None = None
        self._installer: str = ""
        self._build()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(9)

        #: ── 标题行
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("🔄 检查更新", self)
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        head.addWidget(title)
        head.addStretch(1)
        box.addLayout(head)

        #: ── 当前版本
        self.version_label = QLabel(
            f"当前版本 {updater._current_version()}", self)
        self.version_label.setStyleSheet("font-size: 12px; color: #6b7280;")
        box.addWidget(self.version_label)

        #: ── 按钮行
        #:
        #: ⚠⚠ 「启动时自动检查」那个勾选框**去掉了**（用户 2026-10-05）：
        #:
        #:     "这个不用显示出来"
        #:
        #: 自动检查**一直开着**（见 :func:`auto_check_enabled` —— 恒为 True）。
        #: 用户不需要这个开关：有更新时侧栏会亮黄字提示，
        #: 没更新就什么都不显示，本来也不打扰人。
        row = QHBoxLayout()
        row.setSpacing(10)
        self.check_btn = QPushButton("检查更新", self)
        self.check_btn.setObjectName("updateCheckBtn")
        self.check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_btn.clicked.connect(self.check)
        row.addWidget(self.check_btn)

        self.install_btn = QPushButton("下载并安装", self)
        self.install_btn.setObjectName("updateInstallBtn")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.clicked.connect(self.download_and_install)
        self.install_btn.setVisible(False)
        row.addWidget(self.install_btn)

        row.addStretch(1)
        box.addLayout(row)

        #: ── 状态文字
        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 12px;")
        box.addWidget(self.status)

        #: ── 更新说明
        self.notes = QLabel("", self)
        self.notes.setWordWrap(True)
        self.notes.setVisible(False)
        self.notes.setStyleSheet(
            "font-size: 12px; color: #6b7280;"
            " background: rgba(127,127,127,0.10);"
            " border-radius: 6px; padding: 8px;")
        box.addWidget(self.notes)

        #: ── 进度条
        self.bar = QProgressBar(self)
        self.bar.setVisible(False)
        self.bar.setTextVisible(True)
        box.addWidget(self.bar)

    # ------------------------------------------------------------ 设置
    def auto_check_enabled(self) -> bool:
        """启动时要不要自动检查 —— **恒为 True**。

        ## ⚠ 为什么不再是个开关（用户 2026-10-05）

            用户（截图圈出那个勾选框）："这个不用显示出来"

        用户不需要这个开关：
          · 有更新时**侧栏会亮黄字**提示（看得见）
          · 没更新就什么都不显示（不打扰）

        所以自动检查一直开着，界面上去掉了那个框。

        ⚠ 保留这个方法（和 :meth:`set_auto_check`）是为了**兼容旧设置**：
        以前用户关过的话，这里**仍然返回 True** —— 因为那个开关
        已经不在界面上了，再读旧值会让人"找不到地方打开"。
        """
        return True

    def set_auto_check(self, enabled: bool) -> None:
        """（保留接口）—— 现在恒开，写进去也不影响行为。"""
        try:
            _settings().set(AUTO_CHECK_KEY, True)
        except Exception:                      # noqa: BLE001
            logger.debug("存自动检查开关失败", exc_info=True)

    # ------------------------------------------------------------ 检查
    def check(self) -> None:
        """点「检查更新」→ 后台查。"""
        if self._check_thread is not None and self._check_thread.isRunning():
            return
        self.check_btn.setEnabled(False)
        self.status.setText("正在检查…")
        self.install_btn.setVisible(False)
        self.notes.setVisible(False)

        self._check_thread = CheckThread(updater._current_version(), self)
        self._check_thread.done.connect(self._on_checked)
        self._check_thread.start()

    def _on_checked(self, info) -> None:
        self._info = info
        self.check_btn.setEnabled(True)

        if not info.ok:
            self.status.setText(info.error or "检查失败")
            return
        if not info.has_update:
            latest = info.latest or "（仓库还没有发布版本）"
            self.status.setText(f"已是最新版本（{info.current}）")
            if info.latest:
                self.status.setText(
                    f"已是最新版本（{info.current}）")
            return

        #: ── 有更新
        size = f"（{info.size / 1024 / 1024:.1f} MB）" if info.size else ""
        self.status.setText(
            f"发现新版本 **{info.latest}**{size}　"
            f"（当前 {info.current}）".replace("**", ""))
        if info.notes.strip():
            self.notes.setText(info.notes.strip()[:1200])
            self.notes.setVisible(True)
        self.install_btn.setVisible(bool(info.url))

    # ------------------------------------------------------- 下载安装
    def download_and_install(self) -> None:
        """点「下载并安装」→ 后台下载 → 完成后启动安装器。"""
        if self._dl_thread is not None and self._dl_thread.isRunning():
            return
        if self._info is None or not self._info.url:
            return

        self.install_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)                #: 未知总数 → 转圈
        self.status.setText("正在下载…")

        self._dl_thread = DownloadThread(self._info.url, self)
        self._dl_thread.progress.connect(self._on_progress)
        self._dl_thread.done.connect(self._on_downloaded)
        self._dl_thread.failed.connect(self._on_download_failed)
        self._dl_thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, 100)
            pct = int(done * 100 / total)
            self.bar.setValue(pct)
            self.bar.setFormat(
                f"{done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB"
                f"（{pct}%）")
        else:
            self.bar.setRange(0, 0)
            self.bar.setFormat(f"{done / 1024 / 1024:.1f} MB")

    def _on_downloaded(self, path: str) -> None:
        self._installer = path
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.status.setText("下载完成，正在启动安装程序…")
        self.install_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.install()

    def _on_download_failed(self, msg: str) -> None:
        self.bar.setVisible(False)
        self.install_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.status.setText(msg)

    def install(self) -> None:
        """启动安装包并退出本程序。

        ⚠ Windows 上正在运行的 exe 是**锁着**的 —— 不退出的话
        Inno 覆盖不了文件。所以启动完安装器就 ``quit()``。
        """
        if not self._installer:
            return
        try:
            updater.launch_installer(self._installer)
        except Exception as exc:               # noqa: BLE001
            logger.exception("启动安装包失败")
            self.status.setText(f"启动安装程序失败：{exc}")
            return

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()


def build_update_card(parent=None) -> UpdateCard:
    """给配置页用。"""
    return UpdateCard(parent)


class UpdateInterface(ScrollArea):
    """★ 「检查更新」**页面**（侧栏导航项 → 右边整页）。

    ## 用户 2026-10-05

        "侧边栏的检查更新呢"（截图圈出侧栏那一列）

    ⚠⚠ 我第一版把更新卡**塞在配置页里** —— 用户要的是**侧边栏一个导航项**
    （跟「皮肤」一样）。所以这里做成独立页面，配置页那份**删掉**。

    ## ⚠ 必须继承 ``ScrollArea`` 并 ``setWidget(view)``

    这是本项目的**固定写法**（Home / Config / Tasks / Skin 都一样）。
    用裸 ``QWidget`` 的话**整页不显示**（``100x30``、切过去是空白）——
    皮肤页第一版就栽在这。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UpdateInterface")
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        view = QWidget(self)
        view.setObjectName("updateView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        title = QLabel("检查更新", view)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel(
            "有新版本时点「下载并安装」，程序会自动下载并启动安装向导。",
            view)
        hint.setStyleSheet("font-size: 13px; color: #6b7280;")
        layout.addWidget(hint)
        layout.addSpacing(10)

        self.card = UpdateCard(view)
        self.card.setMaximumWidth(720)         #: 别拉满整页，卡片更好看
        layout.addWidget(self.card)
        layout.addStretch(1)

        #: ⚠ 跟其它页面一样 —— 不写这几行整页不显示（见类文档）
        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#UpdateInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    #: 让外部（测试 / 主窗口）能像用卡片一样用它
    @property
    def check_btn(self):
        return self.card.check_btn

    @property
    def install_btn(self):
        return self.card.install_btn

    @property
    def version_label(self):
        return self.card.version_label

    def check(self) -> None:
        self.card.check()


def build_update_page(parent=None) -> UpdateInterface:
    """给侧栏用的更新页面。"""
    return UpdateInterface(parent)
