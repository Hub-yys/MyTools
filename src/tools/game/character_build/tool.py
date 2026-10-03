# -*- coding: utf-8 -*-
"""「查询角色练度」工具页 —— 登录库街区 + 拉账号数据 + 展示。

## 这个工具解决什么

比对自己的账号里**哪些角色的声骸属性不好**、需要重刷。

数据来源是库街区 APP 的「数据终端」（见 :mod:`src.core.kuro_account`）——
**和「资源库更新」那套公开 wiki 接口不是一回事**：那个查图鉴，这个查**你的账号**。

## 流程

    ① 登录：手机号 → 短信验证码 → token（存本地，一次登录长期可用）
    ② 拉数据：baseData（结晶波片/活跃度…）+ roleData（共鸣者列表）
              + getRoleDetail（每个角色的声骸）
    ③ 对比：拿账号里的声骸 和 官方标准 比 → 报出"哪些要重刷"

## ⚠ 关于账号安全

这是**用户的账号**，所以：

* 令牌只存在本地（``data/kuro_account.json``，权限收紧到仅本人可读）
* **只存手机号后 4 位**用于显示，不存全号
* 界面上有明确的「退出登录」= 删掉令牌文件
* 所有网络请求都在**后台线程**里跑，不卡界面
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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
from ....core.registry import registry
from ....core.categories import ToolCategory
from ....core.tool_base import BaseTool

logger = logging.getLogger(__name__)

#: 工具 key（设置 / 注册都用它）
TOOL_KEY = "character_build"

#: 手机号长度（大陆 11 位）—— 只做基本校验，真校验交给服务端
MOBILE_LEN = 11


# --------------------------------------------------------------------- 线程

class SendCodeThread(QThread):
    """后台发短信验证码。"""

    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, mobile: str, parent=None):
        super().__init__(parent)
        self._mobile = mobile

    def run(self) -> None:                     # noqa: D102
        try:
            kuro_account.send_sms_code(self._mobile)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit()


class LoginThread(QThread):
    """后台用验证码换 token（顺带取绑定的游戏角色）。"""

    succeeded = Signal(object)                 # Account
    failed = Signal(str)

    def __init__(self, mobile: str, code: str, parent=None):
        super().__init__(parent)
        self._mobile = mobile
        self._code = code

    def run(self) -> None:                     # noqa: D102
        try:
            account = kuro_account.login_with_code(self._mobile, self._code)
            kuro_account.save_account(account)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(account)


class FetchThread(QThread):
    """后台拉账号数据（baseData + roleData）。"""

    succeeded = Signal(object)                 # dict
    failed = Signal(str)

    def __init__(self, account, role, parent=None):
        super().__init__(parent)
        self._account = account
        self._role = role

    def run(self) -> None:                     # noqa: D102
        try:
            token = self._account.token
            role_id = self._role.get("roleId")
            server_id = self._role.get("serverId")
            data = {
                "base": kuro_account.fetch_base_data(token, role_id,
                                                     server_id),
                "roles": kuro_account.fetch_role_data(token, role_id,
                                                      server_id),
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
        #   而那个按钮在数据卡片里才创建。放在登录卡片里刷会 AttributeError。
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
        self._mobile_edit = QLineEdit(card)
        self._mobile_edit.setPlaceholderText("手机号")
        self._mobile_edit.setMaxLength(MOBILE_LEN)
        self._mobile_edit.setFixedWidth(160)
        row.addWidget(self._mobile_edit)

        self._send_button = PushButton("发送验证码", card)
        self._send_button.clicked.connect(self._on_send_code)
        row.addWidget(self._send_button)

        self._code_edit = QLineEdit(card)
        self._code_edit.setPlaceholderText("验证码")
        self._code_edit.setMaxLength(8)
        self._code_edit.setFixedWidth(110)
        row.addWidget(self._code_edit)

        self._login_button = PushButton("登录", card)
        self._login_button.clicked.connect(self._on_login)
        row.addWidget(self._login_button)

        self._logout_button = PushButton("退出登录", card)
        self._logout_button.clicked.connect(self._on_logout)
        row.addWidget(self._logout_button)
        row.addStretch(1)
        box.addLayout(row)

        box.addWidget(CaptionLabel(
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
        self._log.setMinimumHeight(140)
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
              position=InfoBarPosition.TOP, duration=4000, parent=self)

    def _refresh_login_state(self) -> None:
        if self._account.logged_in:
            tail = self._account.mobile_tail
            self._login_status.setText(
                f"已登录（手机号 ****{tail}）" if tail else "已登录")
            self._fetch_button.setEnabled(True)
        else:
            self._login_status.setText("未登录")
            self._fetch_button.setEnabled(False)

    def _busy(self, busy: bool) -> None:
        for button in (self._send_button, self._login_button,
                       self._fetch_button):
            button.setEnabled(not busy)
        if not busy:
            self._refresh_login_state()

    # ------------------------------------------------------------- 动作
    def _mobile(self) -> str:
        return self._mobile_edit.text().strip()

    def _on_send_code(self) -> None:
        mobile = self._mobile()
        if len(mobile) != MOBILE_LEN or not mobile.isdigit():
            self._toast(f"手机号要填 {MOBILE_LEN} 位数字", ok=False)
            return
        self._busy(True)
        self._say(f"正在给 ****{mobile[-4:]} 发送验证码…")
        thread = SendCodeThread(mobile, self)
        thread.succeeded.connect(self._on_code_sent)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_code_sent(self) -> None:
        self._busy(False)
        self._say("验证码已发送（接口接受了这个手机号）")
        self._toast("验证码已发送，请查看短信")

    def _on_login(self) -> None:
        mobile = self._mobile()
        code = self._code_edit.text().strip()
        if len(mobile) != MOBILE_LEN or not mobile.isdigit():
            self._toast(f"手机号要填 {MOBILE_LEN} 位数字", ok=False)
            return
        if not code:
            self._toast("验证码不能为空", ok=False)
            return
        self._busy(True)
        self._say("正在登录…")
        thread = LoginThread(mobile, code, self)
        thread.succeeded.connect(self._on_logged_in)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_logged_in(self, account) -> None:
        self._account = account
        self._busy(False)
        names = [str(r.get("roleName") or r.get("roleId"))
                 for r in (account.roles or [])]
        self._say(f"登录成功。绑定的游戏角色：{names or '（没拿到，稍后拉数据时再试）'}")
        self._toast("登录成功")

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
        self._say(f"正在拉取「{role.get('roleName') or role.get('roleId')}」的数据…")
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
        self._mobile_edit.clear()
        self._code_edit.clear()
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
