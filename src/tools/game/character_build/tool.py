# -*- coding: utf-8 -*-
"""「查询角色练度」工具页 —— 手机号 + 验证码登录，拉角色/声骸数据。

## ★★★ 完整流程（2026-10-03 实测跑通）

    ┌─ ① 手机号 + 短信验证码 → **APP 端登录**（source=android）→ token
    ├─ ② 取游戏角色  /gamer/role/list {gameId:3} → 特征码 + serverId
    ├─ ③ 换「数据令牌」/aki/roleBox/requestToken → accessToken
    └─ ④ 之后所有 /aki/ 请求**只带 b-at 头** → 角色列表 + 声骸详情

## 验证码不用本工具发

**API 文档明确：验证码 APP 端与 Web 端通用。**
所以用户在**任意官方入口**（App / 网页）点"获取验证码"，
把码填到这里就行 —— 我们不需要碰极验。

## ⚠ 为什么不用内嵌浏览器了

之前做过一版内嵌浏览器登录（读 ``localStorage.auth_token``）。
**那条路拿到的令牌 `/aki/` 不认**（回 `10901 禁止访问`）——
网页登录和 App 端登录是**两套令牌**。
现在直接用手机号 + 验证码走 App 端登录，**简单得多也正确**。

## 账号安全

* 令牌只存本地（``data/kuro_account.json``，权限收紧到仅本人可读）
* **只存手机号后 4 位**用于显示，不存全号
* 界面上有明确的「退出登录」= 删掉令牌文件
* 网络请求全在后台线程里跑，不卡界面
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
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

logger = logging.getLogger(__name__)

#: 工具 key
TOOL_KEY = "character_build"

#: 手机号长度（大陆 11 位）
MOBILE_LEN = 11


# --------------------------------------------------------------------- 线程

class LoginThread(QThread):
    """后台 APP 端登录 + 换数据令牌。"""

    succeeded = Signal(object)                 # Account
    failed = Signal(str)

    def __init__(self, mobile: str, code: str, parent=None):
        super().__init__(parent)
        self._mobile = mobile
        self._code = code

    def run(self) -> None:                     # noqa: D102
        try:
            account = kuro_account.app_login_with_code(self._mobile,
                                                       self._code)
            kuro_account.save_account(account)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(account)


class FetchThread(QThread):
    """后台拉账号数据（基础 + 角色列表 + 声骸）。"""

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, account, parent=None):
        super().__init__(parent)
        self._account = account

    def run(self) -> None:                     # noqa: D102
        try:
            acc = self._account
            roles = acc.roles or []
            if not roles:
                self.failed.emit("没拿到绑定的游戏角色")
                return
            role = next((r for r in roles
                         if str(r.get("gameId")) == "3"), roles[0])
            role_id = str(role.get("roleId"))
            server_id = str(role.get("serverId"))

            self.progress.emit("正在换数据令牌…")
            data_token, _req = kuro_account.request_data_token(
                acc.token, role_id, server_id)
            acc.data_token = data_token
            acc.user_id = str(role.get("userId") or "")

            self.progress.emit("正在拉账号数据…")
            base = kuro_account.fetch_base_data(data_token, role_id,
                                                server_id)
            self.progress.emit("正在拉角色列表…")
            rd = kuro_account.fetch_role_data(data_token, role_id, server_id)
            role_list = (rd or {}).get("roleList") or []

            self.progress.emit(f"正在拉声骸详情（{len(role_list)} 个角色）…")
            details = {}
            for r in role_list:
                cid = r.get("roleId")
                try:
                    details[str(cid)] = kuro_account.fetch_role_detail(
                        data_token, role_id, server_id, cid)
                except Exception:              # noqa: BLE001 - 单个失败不中断
                    continue

            try:
                kuro_account.save_account(acc)
            except Exception:                  # noqa: BLE001
                pass

            self.succeeded.emit({
                "role": role, "base": base,
                "roleList": role_list, "details": details,
            })
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------- 面板

class CharacterBuildPanel(ScrollArea):
    """登录卡片 + 数据卡片 + 日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterBuildPanel")
        self._account = kuro_account.load_account()
        self._thread: QThread | None = None
        self._data: dict = {}
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
        # ⚠ 登录态最后刷新（它管着「获取数据」按钮，那按钮在后面才建）
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
        self._mobile_edit.setFixedWidth(150)
        row.addWidget(self._mobile_edit)

        self._code_edit = QLineEdit(card)
        self._code_edit.setPlaceholderText("短信验证码")
        self._code_edit.setMaxLength(8)
        self._code_edit.setFixedWidth(120)
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
            "★ 验证码请在**任意官方入口**获取（库街区 App，或电脑网页的"
            "登录框点「获取验证码」）—— 两边通用。\n"
            "⚠ 令牌只存本机（data/kuro_account.json），只记手机号后 4 位。"
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
        self._log.setMinimumHeight(180)
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
        for b in (self._login_button, self._fetch_button):
            b.setEnabled(not busy)
        if not busy:
            self._refresh_login_state()

    # ------------------------------------------------------------- 登录
    def _on_login(self) -> None:
        mobile = self._mobile_edit.text().strip()
        code = self._code_edit.text().strip()
        if len(mobile) != MOBILE_LEN or not mobile.isdigit():
            self._toast(f"手机号要填 {MOBILE_LEN} 位数字", ok=False)
            return
        if not code:
            self._toast("请填短信验证码", ok=False)
            return
        self._busy(True)
        self._say("正在登录（APP 端）…")
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
        self._say(f"✓ 登录成功。绑定的游戏角色：{names or '（没拿到）'}")
        self._toast("登录成功")

    # ------------------------------------------------------------- 数据
    def _on_fetch(self) -> None:
        if not self._account.logged_in:
            self._toast("请先登录", ok=False)
            return
        self._busy(True)
        self._say("开始拉取数据…")
        thread = FetchThread(self._account, self)
        thread.progress.connect(self._say)
        thread.succeeded.connect(self._on_fetched)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_fetched(self, data) -> None:
        self._busy(False)
        self._data = data or {}
        base = self._data.get("base") or {}
        role_list = self._data.get("roleList") or []
        details = self._data.get("details") or {}

        self._summary.setText(self._format_base(base))

        self._say(f"✓ 角色 {len(role_list)} 个，"
                  f"拿到声骸详情的 {len(details)} 个")
        # 挑几个角色展示（让用户一眼看到声骸）
        shown = 0
        for r in sorted(role_list, key=lambda x: -(x.get("level") or 0)):
            d = details.get(str(r.get("roleId")))
            if not d:
                continue
            eq = ((d.get("phantomData") or {})
                  .get("equipPhantomList") or [])
            self._say(f"── {r.get('roleName')} Lv{r.get('level')}"
                      f"  COST {((d.get('phantomData') or {}).get('cost'))}"
                      f"  声骸 {len(eq)} 个")
            for item in eq:
                main = (item.get("mainProps") or [{}])[0]
                subs = item.get("subProps") or []
                valid = sum(1 for s in subs if s.get("valid"))
                self._say(
                    f"     COST{item.get('cost')} +{item.get('level')} "
                    f"{(item.get('phantomProp') or {}).get('name', '?')}"
                    f"  主 {main.get('attributeName', '?')}"
                    f"{main.get('attributeValue', '?')}"
                    f"  副词条 {len(subs)} 条（有效 {valid}）")
            shown += 1
            if shown >= 3:
                break
        self._toast("数据拉取完成")

    @staticmethod
    def _format_base(base: dict) -> str:
        """把基础数据拼成一行摘要（字段名来自实测）。"""
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
        self._data = {}
        self._summary.setText("尚未拉取")
        self._refresh_login_state()
        self._say("已退出登录（令牌文件已删除）")
        self._toast("已退出登录")

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self._say(f"✗ 失败：{message}")
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
    #: ⚠ BaseTool 默认 coming_soon = True（占位页）
    coming_soon = False
    #: 不参与任务流程：它不操作游戏，是"查数据"的工具
    supports_task_run = False

    def create_widget(self, parent=None):
        return CharacterBuildPanel(parent)
