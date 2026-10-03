# -*- coding: utf-8 -*-
"""「查询角色练度」工具页 —— 登录库街区 + 拉账号数据 + 展示。

## 这个工具解决什么

比对自己的账号里**哪些角色的声骸属性不好**、需要重刷。

数据来源是库街区 APP 的「数据终端」（见 :mod:`src.core.kuro_account`）——
**和「资源库更新」那套公开 wiki 接口不是一回事**：那个查图鉴，这个查**你的账号**。

## ★ 登录为什么是"开个浏览器窗口"

2026-10-03 实测：``/user/getSmsCode`` 返回::

    {"code":200, "data":{"geeTest":true}, "msg":"请求成功", "success":true}

**``code`` 是 200，但短信根本没发** —— 要先过「极验」人机验证。
我第一版只看 ``code == 200`` 就报"已发送"，用户反馈"我手机没收到短信"。

极验要跑 JS + 采集行为轨迹，纯 Python 做不到（也不该做）。所以改成:
**弹一个真实浏览器窗口，用户自己过人机验证 + 收短信，登录成功后官方页面
会把 token 写进 ``localStorage.auth_token``，我们读出来存到本地。**
之后就不用再登了。

## ⚠ 关于账号安全

这是**用户的账号**，所以：

* 令牌只存在本地（``data/kuro_account.json``，权限收紧到仅本人可读）
* **只存手机号后 4 位**用于显示，不存全号
* 界面上有明确的「退出登录」= 删掉令牌文件
* 浏览器用**独立 profile**，不碰用户平时的浏览器数据
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    InfoBarPosition,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ....core import kuro_account
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool
from .login_dialog import KuroLoginDialog

logger = logging.getLogger(__name__)

#: 工具 key（设置 / 注册都用它）
TOOL_KEY = "character_build"


# --------------------------------------------------------------------- 线程

class RolesThread(QThread):
    """后台取绑定的游戏角色（登录成功后要它拿 roleId）。"""

    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(self, token: str, dev_code: str, parent=None):
        super().__init__(parent)
        self._token = token
        self._dev_code = dev_code

    def run(self) -> None:                     # noqa: D102
        try:
            roles = kuro_account.fetch_roles(self._token, self._dev_code)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(roles)


class FetchThread(QThread):
    """后台拉账号数据（baseData + roleData）。"""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, account, role, parent=None):
        super().__init__(parent)
        self._account = account
        self._role = role

    def run(self) -> None:                     # noqa: D102
        try:
            token = self._account.token
            dev = self._account.dev_code
            role_id = self._role.get("roleId")
            server_id = self._role.get("serverId")
            data = {
                "base": kuro_account.fetch_base_data(
                    token, role_id, server_id, dev_code=dev),
                "roles": kuro_account.fetch_role_data(
                    token, role_id, server_id, dev_code=dev),
            }
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(data)


# --------------------------------------------------------------------- 面板

class CharacterBuildPanel(ScrollArea):
    """登录卡片 + 数据卡片 + 日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterBuildPanel")
        self._account = kuro_account.load_account()
        self._thread: QThread | None = None
        self._dialog: KuroLoginDialog | None = None
        self._build()

    # ------------------------------------------------------------- 构建
    def _build(self) -> None:
        view = QWidget(self)
        self.setWidget(view)
        self.setWidgetResizable(True)
        root = QVBoxLayout(view)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)

        root.addWidget(TitleLabel("查询角色练度", view))
        root.addWidget(BodyLabel(
            "登录库街区后拉取你账号里的角色与声骸数据，"
            "用来比对哪些角色的声骸属性需要重刷。", view))

        root.addWidget(self._build_login_card(view))
        root.addWidget(self._build_data_card(view))
        root.addWidget(self._build_log_card(view))
        root.addStretch(1)
        # ⚠ 登录态要**最后**刷新 —— 它同时管着「获取数据」按钮，
        #   而那个按钮在数据卡片里才创建。
        self._refresh_login_state()

    def _build_login_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        box.addWidget(SubtitleLabel("① 登录库街区", card))
        self._login_status = CaptionLabel("未登录", card)
        box.addWidget(self._login_status)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._open_login = PushButton("打开登录窗口", card)
        self._open_login.clicked.connect(self._on_open_login)
        row.addWidget(self._open_login)

        self._logout_button = PushButton("退出登录", card)
        self._logout_button.clicked.connect(self._on_logout)
        row.addWidget(self._logout_button)
        row.addStretch(1)
        box.addLayout(row)

        box.addWidget(CaptionLabel(
            "点「打开登录窗口」后，在弹窗里正常登录（人机验证和短信验证码"
            "都由你本人完成）。登录成功窗口会自动关闭。\n"
            "⚠ 令牌只存在本机（data/kuro_account.json），只记手机号后 4 位。"
            "「退出登录」会删掉它。", card))
        return card

    def _build_data_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        box.addWidget(SubtitleLabel("② 拉取账号数据", card))
        row = QHBoxLayout()
        self._fetch_button = PushButton("获取数据", card)
        self._fetch_button.clicked.connect(self._on_fetch)
        row.addWidget(self._fetch_button)
        row.addStretch(1)
        box.addLayout(row)

        self._summary = StrongBodyLabel("尚未拉取", card)
        self._summary.setWordWrap(True)
        box.addWidget(self._summary)
        return card

    def _build_log_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)
        box.addWidget(SubtitleLabel("日志", card))
        self._log = QTextEdit(card)
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(160)
        box.addWidget(self._log)
        return card

    # ------------------------------------------------------------- 小工具
    def _say(self, message: str) -> None:
        self._log.append(message)
        logger.info("查询角色练度：%s", message)

    def _toast(self, message: str, ok: bool = True) -> None:
        maker = InfoBar.success if ok else InfoBar.error
        maker(title="查询角色练度", content=message,
              orient=Qt.Horizontal, isClosable=True,
              position=InfoBarPosition.TOP, duration=5000, parent=self)

    def _refresh_login_state(self) -> None:
        if self._account.logged_in:
            tail = self._account.mobile_tail
            self._login_status.setText(
                f"已登录（手机号 ****{tail}）" if tail else "已登录")
            self._fetch_button.setEnabled(bool(self._account.roles))
        else:
            self._login_status.setText("未登录")
            self._fetch_button.setEnabled(False)

    def _busy(self, busy: bool) -> None:
        for button in (self._open_login, self._fetch_button):
            button.setEnabled(not busy)
        if not busy:
            self._refresh_login_state()

    # ------------------------------------------------------------- 登录
    def _on_open_login(self) -> None:
        """★ 弹内嵌浏览器 —— 人机验证和短信都由用户本人完成。"""
        self._say("已打开登录窗口，请在窗口里完成登录…")
        dialog = KuroLoginDialog(self)
        self._dialog = dialog
        dialog.logged_in.connect(self._on_browser_login)
        dialog.exec()

    def _on_browser_login(self, token: str, dev_code: str,
                          auth_raw: str) -> None:
        """浏览器里登录成功了 —— 组装账号、取游戏角色、落盘。"""
        import json

        try:
            auth = json.loads(auth_raw or "{}")
        except Exception:                      # noqa: BLE001
            auth = {}
        try:
            account = kuro_account.account_from_browser(
                token, dev_code, auth if isinstance(auth, dict) else {})
        except Exception as exc:               # noqa: BLE001
            self._say(f"组装账号失败：{exc}")
            self._toast(str(exc), ok=False)
            return

        self._account = account
        self._say(f"已拿到令牌（动态 devCode {'有' if dev_code else '无'}），"
                  f"正在取绑定的游戏角色…")
        thread = RolesThread(token, dev_code, self)
        thread.succeeded.connect(self._on_roles)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_roles(self, roles: list) -> None:
        self._account.roles = roles or []
        try:
            path = kuro_account.save_account(self._account)
        except Exception as exc:               # noqa: BLE001
            self._say(f"⚠ 令牌存不下来：{exc}")
        else:
            self._say(f"令牌已保存到 {path.name}")
        names = [str(r.get("roleName") or r.get("roleId"))
                 for r in self._account.roles]
        if names:
            self._say(f"绑定的游戏角色：{names}")
            self._toast("登录成功")
        else:
            self._say("⚠ 没取到绑定的游戏角色 —— 点「获取数据」时会再试")
            self._toast("登录成功，但没取到游戏角色", ok=False)
        self._refresh_login_state()

    # ------------------------------------------------------------- 数据
    def _on_fetch(self) -> None:
        if not self._account.logged_in:
            self._toast("请先登录", ok=False)
            return
        roles = self._account.roles or []
        if not roles:
            self._toast("没拿到绑定的游戏角色，请重新登录", ok=False)
            return
        self._busy(True)
        role = roles[0]
        self._say(f"正在拉取「{role.get('roleName') or role.get('roleId')}」"
                  f"的数据…")
        thread = FetchThread(self._account, role, self)
        thread.succeeded.connect(self._on_fetched)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_fetched(self, data) -> None:
        self._busy(False)
        base = (data or {}).get("base") or {}
        self._summary.setText(self._format_base(base))
        self._say("数据拉取完成")
        self._toast("数据拉取完成")

    @staticmethod
    def _format_base(base: dict) -> str:
        """把 baseData 拼成一行摘要。

        ⚠ 字段名来自接口实测：``energy`` = 结晶波片、``storeEnergy`` = 结晶单质、
        ``liveness`` = 活跃度、``activeDays`` = 游戏天数、
        ``level`` = 联觉等级、``roleNum`` = 解锁角色数。
        """
        if not base:
            return "没拿到基础数据"
        parts = [
            f"结晶波片 {base.get('energy', '?')}/{base.get('maxEnergy', '?')}",
            f"结晶单质 {base.get('storeEnergy', '?')}"
            f"/{base.get('storeEnergyLimit', '?')}",
            f"活跃度 {base.get('liveness', '?')}"
            f"/{base.get('livenessMaxCount', '?')}",
            f"游戏天数 {base.get('activeDays', '?')}",
            f"联觉等级 {base.get('level', '?')}",
            f"解锁角色 {base.get('roleNum', '?')}",
        ]
        return "　|　".join(parts)

    def _on_logout(self) -> None:
        kuro_account.clear_account()
        self._account = kuro_account.Account()
        self._summary.setText("尚未拉取")
        self._refresh_login_state()
        self._say("已退出登录（令牌文件已删除）")
        self._toast("已退出登录")

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self._say(f"失败：{message}")
        self._toast(message, ok=False)


# --------------------------------------------------------------------- 工具

@registry.register(
    category=ToolCategory.GAME,
    name="查询角色练度",
    description="登录库街区，拉取账号里的角色与声骸数据，比对哪些声骸需要重刷",
    icon_name="CERTIFICATE",
    coming_soon=False,
)
class CharacterBuildTool(BaseTool):
    """查询角色练度。"""

    key = TOOL_KEY
    #: ⚠ BaseTool 默认 coming_soon = True（占位页）—— 这个是真做完了的
    coming_soon = False
    #: 不参与任务流程：它不操作游戏，是"查数据"的工具
    supports_task_run = False

    def create_widget(self, parent=None):
        return CharacterBuildPanel(parent)
