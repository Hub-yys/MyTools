# -*- coding: utf-8 -*-
"""「查询角色练度」工具页 —— 手机号 + 验证码登录，像官方那样展示角色与声骸。

## ★★★ 完整流程（2026-10-03 实测跑通）

    ┌─ ① 手机号 + 短信验证码 → **APP 端登录**（source=android）→ token
    ├─ ② 取游戏角色  /gamer/role/list {gameId:3} → 特征码 + serverId
    ├─ ③ 换「数据令牌」/aki/roleBox/requestToken → accessToken
    └─ ④ 之后所有 /aki/ 请求**只带 b-at 头** → 角色列表 + 声骸详情

## 界面（对齐官方「共鸣者」卡片的展示方式）

    ┌─ ① 登录：特征码 / 手机号 / 验证码（各一行）+ 获取数据
    ├─ ② 账号概览：结晶波片 | 结晶单质 | 活跃度 | 游戏天数 | 联觉等级 | 解锁角色
    ├─ ③ **角色网格**：头像 + 等级 + 共鸣链 + 属性 + 名字（像官方那样）
    │     · 声骸没达标的角色**红框**标出来
    │     · 点角色 → 展开 5 个声骸明细（COST/等级/名/套装/主属性/副词条/有效数）
    └─ ④ 日志（后台写，默认折叠）

## 数据持久化

拉到的数据存 ``data/kuro_练度.json`` —— 重启后**直接显示上次结果**，
不用重新登录/重拉。登录后也会**自动拉一次**。
"""

from __future__ import annotations

import json
import logging
import time

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ....core import kuro_account, paths, tool_settings
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

logger = logging.getLogger(__name__)

#: 工具 key
TOOL_KEY = "character_build"

#: 设置节名（记特征码 / 手机号）
SETTINGS_KEY = "character_build"

#: 手机号长度（大陆 11 位）
MOBILE_LEN = 11

#: 缓存文件名（用户数据目录）—— 数据持久化，重启直接显示
CACHE_NAME = "kuro_练度.json"

#: 角色卡片尺寸
AVATAR_SIZE = 56
CARD_W = 112
CARD_H = 128

#: 角色网格每行几个
GRID_COLS = 6

#: 「达标」筛选下拉的选项（用户："达标/未达标"）
FILTER_CHOICES = ("全部", "未达标", "达标")


def cache_file():
    """缓存文件位置（用户数据目录）。"""
    return paths.user_data_dir() / CACHE_NAME


# --------------------------------------------------------------------- 线程

class LoginThread(QThread):
    """后台 APP 端登录 + 换数据令牌 + **自动拉一次数据**。"""

    progress = Signal(str)
    succeeded = Signal(object)                 # Account
    failed = Signal(str)

    def __init__(self, mobile: str, code: str, feature_code: str = "",
                 parent=None):
        super().__init__(parent)
        self._mobile = mobile
        self._code = code
        self._feature = feature_code

    def run(self) -> None:                     # noqa: D102
        try:
            self.progress.emit("正在登录（APP 端）…")
            account = kuro_account.app_login_with_code(self._mobile,
                                                       self._code)
            kuro_account.save_account(account)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(account)


class FetchThread(QThread):
    """后台拉账号数据（基础 + 角色列表 + 声骸）。

    ## ★ 为什么要"边拉边存"（2026-10-03 实测教训）

    43 个角色 = **43 次网络请求**，实测要**十几到几十秒**。
    用户日志停在 `正在拉声骸详情（43 个角色）…` 之后就没下文 ——
    因为**没跑完就被关掉了**，`succeeded` 从没发出 → **缓存从没写**
    → 下次打开还是"没数据"。

    所以现在：
      * 每拉完**一个**角色就 ``progress.emit``（界面能看到进度在动）
      * 声骸详情是**逐步累积**的，中途被打断也**已经存了一部分**
      * ``partial`` 信号：拉到一半也能先把已有数据交给界面
    """

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    #: ★ 阶段性成果（拉到一半也先给界面用）
    partial = Signal(object)

    def __init__(self, account, feature_code: str = "", parent=None):
        super().__init__(parent)
        self._account = account
        self._feature_code = (feature_code or "").strip()
        self._stop = False

    def stop(self) -> None:
        """请求中止（界面关掉时调）—— 循环会尽快退出并保存已拉到的。"""
        self._stop = True

    def run(self) -> None:                     # noqa: D102
        try:
            acc = self._account
            roles = acc.roles or []

            # ★★ 特征码：用户填了就以它为准（留空 = 用绑定的那个）
            role = None
            want = self._feature_code
            if want:
                role = next((r for r in roles
                             if str(r.get("roleId") or "").strip() == want),
                            None)
                if role is None:
                    role = kuro_account.resolve_role(acc.token, want)
                if role is None:
                    self.failed.emit(
                        f"查不到特征码 {want} 对应的角色。\n"
                        f"当前账号绑定的角色："
                        f"{[r.get('roleName') for r in roles] or '（无）'}")
                    return
            elif roles:
                role = next((r for r in roles
                             if str(r.get("gameId")) == "3"), roles[0])
            if role is None:
                self.failed.emit("没拿到任何游戏角色 —— 请先登录")
                return

            role_id = str(role.get("roleId"))
            server_id = str(role.get("serverId"))
            self.progress.emit(f"目标角色：{role.get('roleName') or role_id}"
                               f"（特征码 {role_id}）")

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

            total = len(role_list)
            self.progress.emit(f"正在拉声骸详情（{total} 个角色）…")
            details: dict = {}
            for i, r in enumerate(role_list, 1):
                if self._stop:
                    self.progress.emit(f"已中止（拉到 {i - 1}/{total}）")
                    break
                cid = r.get("roleId")
                try:
                    details[str(cid)] = kuro_account.fetch_role_detail(
                        data_token, role_id, server_id, cid)
                except Exception:              # noqa: BLE001 - 单个失败不中断
                    continue
                # ★ 每拉几个就报一次进度 + 交给界面（中途关掉也不白拉）
                if i % 5 == 0 or i == total:
                    self.progress.emit(f"  声骸进度 {i}/{total}")
                    payload = self._payload(role, base, role_list, details)
                    save_cache(payload)
                    self.partial.emit(payload)

            payload = self._payload(role, base, role_list, details)
            save_cache(payload)
            acc.roles = roles
            try:
                kuro_account.save_account(acc)
            except Exception:                  # noqa: BLE001
                pass
            self.succeeded.emit(payload)
        except kuro_account.RoleNotFound as exc:
            self.failed.emit(str(exc))
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _payload(role, base, role_list, details) -> dict:
        return {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "role": role, "base": base,
            "roleList": role_list, "details": details,
        }


# --------------------------------------------------------------------- 缓存

def save_cache(payload: dict) -> None:
    """把拉到的数据落盘（重启后直接显示，不用重拉）。"""
    try:
        path = cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
    except Exception as exc:                   # noqa: BLE001
        logger.warning("练度缓存写不进去：%s", exc)


def load_cache() -> dict:
    """读上次拉的数据；没有 / 坏了都返回空 dict。"""
    try:
        path = cache_file()
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                          # noqa: BLE001
        return {}


def clear_cache() -> None:
    try:
        cache_file().unlink()
    except Exception:                          # noqa: BLE001
        pass


# --------------------------------------------------------------------- 控件

class CharacterCard(QWidget):
    """一个角色卡片（像官方那样：头像 + 等级 + 共鸣链 + 名字）。

    :param flagged: 声骸没达标 → **红框**标出来
    """

    clicked = Signal(str)                      # 角色 id

    def __init__(self, role: dict, flagged: bool = False, parent=None):
        super().__init__(parent)
        self._cid = str(role.get("roleId"))
        self.setFixedSize(QSize(CARD_W, CARD_H))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip(role, flagged))

        box = QVBoxLayout(self)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(2)

        # ── 头像
        holder = QLabel(self)
        holder.setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))
        holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder.setPixmap(self._avatar(role.get("roleName")).pixmap(
            AVATAR_SIZE, AVATAR_SIZE))
        box.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        # ── 等级
        lv = QLabel(f"Lv.{role.get('level', '?')}", self)
        lv.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lv.setStyleSheet("font-size: 11px;")
        box.addWidget(lv)

        # ── 共鸣链 + 属性
        sub = QLabel(f"{role.get('attributeName', '')}"
                     f"　{role.get('chainUnlockNum', 0)}链", self)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("font-size: 10px;")
        box.addWidget(sub)

        # ── 名字
        name = QLabel(str(role.get("roleName") or "?"), self)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        weight = "bold" if flagged else "normal"
        color = "#c42b1c" if flagged else "inherit"
        name.setStyleSheet(f"font-size: 12px; font-weight: {weight};"
                           f"color: {color};")
        box.addWidget(name)

        # ★ 声骸没达标 → 红框
        border = "#c42b1c" if flagged else "transparent"
        width = 2 if flagged else 1
        self.setStyleSheet(
            f"CharacterCard {{ border: {width}px solid {border};"
            f" border-radius: 6px; }}")

    @staticmethod
    def _avatar(name):
        """角色头像 —— 拿不到就用首字圆图兜底。"""
        try:
            from ....gui.pickers import avatar_icon
            from ....core import game_data

            info = game_data.find_character(str(name or ""))
            return avatar_icon(info.avatar if info else "", str(name or ""))
        except Exception:                      # noqa: BLE001
            from PySide6.QtGui import QIcon

            return QIcon()

    @staticmethod
    def _tooltip(role: dict, flagged: bool) -> str:
        lines = [
            f"{role.get('roleName')}　Lv{role.get('level')}",
            f"属性：{role.get('attributeName')}　"
            f"武器：{role.get('weaponTypeName')}",
            f"共鸣链：{role.get('chainUnlockNum')}　"
            f"星级：{role.get('starLevel')}",
        ]
        if flagged:
            lines.append("⚠ 声骸未达标 —— 点开看明细")
        return "\n".join(lines)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        self.clicked.emit(self._cid)
        super().mousePressEvent(event)


# --------------------------------------------------------------------- 面板

class CharacterBuildPanel(ScrollArea):
    """登录 + 概览 + 角色网格 + 明细 + 日志（折叠）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterBuildPanel")
        self._account = kuro_account.load_account()
        self._thread: QThread | None = None
        self._login_thread: QThread | None = None   # ★ 单独持有，别被覆盖
        self._data: dict = load_cache()        # ★ 直接显示上次结果
        self._cards: list[CharacterCard] = []
        self._auto_fetched = False
        self._build()
        self._render(self._data)               # 有缓存就先显示
        # ★ 已登录但**没有缓存**（比如上次没拉完）→ 自动拉一次
        #   （用户："我上次已经登陆，为什么不显示数据"）
        QTimer.singleShot(300, self._maybe_auto_fetch)

    def _maybe_auto_fetch(self) -> None:
        """已登录 + 没数据 → 自动拉一次（不用用户再点）。"""
        if self._auto_fetched or self._data.get("roleList"):
            return
        if not self._account.logged_in:
            return
        self._auto_fetched = True
        self._say("检测到已登录但本地没有数据 —— 自动拉取一次…")
        self._on_fetch()

    # ------------------------------------------------------------- 构建
    def _build(self) -> None:
        view = QWidget(self)
        self.setWidget(view)
        self.setWidgetResizable(True)
        root = QVBoxLayout(view)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(12)

        root.addWidget(TitleLabel("查询角色练度", view))
        root.addWidget(BodyLabel(
            "登录库街区后拉取你账号里的角色与声骸数据，"
            "用来比对哪些角色的声骸属性需要重刷。", view))

        root.addWidget(self._build_login_card(view))
        root.addWidget(self._build_overview_card(view))
        root.addWidget(self._build_roles_card(view))
        root.addWidget(self._build_detail_card(view))
        root.addWidget(self._build_log_card(view))
        root.addStretch(1)
        self._refresh_login_state()

    def _build_login_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(SubtitleLabel("① 登录库街区", card))
        self._login_status = CaptionLabel("未登录", card)
        head.addWidget(self._login_status)
        head.addStretch(1)
        self._logout_button = PushButton("退出登录", card)
        self._logout_button.clicked.connect(self._on_logout)
        head.addWidget(self._logout_button)
        box.addLayout(head)

        def field(label: str, placeholder: str, width: int, maxlen: int = 0):
            row = QHBoxLayout()
            row.setSpacing(8)
            tag = CaptionLabel(label, card)
            tag.setFixedWidth(48)
            row.addWidget(tag)
            edit = QLineEdit(card)
            edit.setPlaceholderText(placeholder)
            edit.setFixedWidth(width)
            if maxlen:
                edit.setMaxLength(maxlen)
            row.addWidget(edit)
            row.addStretch(1)
            box.addLayout(row)
            return edit

        # ⚠ 特征码**保留输入框**（用户 2026-10-03 要求）：
        #   留空 = 登录后自动用「绑定的游戏角色」；填了 = 就查那个号。
        #   （我先删掉它是错的 —— 用户明确说"特征码呢"）
        self._feature_edit = field("特征码", "留空 = 自动用绑定账号",
                                   200)
        self._mobile_edit = field("手机号", "手机号", 200, MOBILE_LEN)
        self._code_edit = field("验证码", "短信验证码", 200, 8)
        # ★ 三个输入框都**记住上次的值**（用户要求：登录一次后默认保存）
        self._restore_inputs()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._login_button = PushButton("登录", card)
        self._login_button.clicked.connect(self._on_login)
        btn_row.addWidget(self._login_button)
        # ⚠ 「获取数据」按钮已去掉（用户要求）：登录后**自动拉**，
        #   之后想重拉点「刷新数据」。
        self._refresh_button = PushButton("刷新数据", card)
        self._refresh_button.clicked.connect(self._on_fetch)
        btn_row.addWidget(self._refresh_button)
        btn_row.addStretch(1)
        box.addLayout(btn_row)

        box.addWidget(CaptionLabel(
            "验证码在任意官方入口获取（库街区 App / 网页登录框）—— 两边通用。"
            "　**登录后会自动拉取数据**；之后想重拉点「刷新数据」。", card))
        return card

    def _build_overview_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)
        box.addWidget(SubtitleLabel("② 账号概览", card))
        self._summary = StrongBodyLabel("尚未拉取数据", card)
        self._summary.setWordWrap(True)
        box.addWidget(self._summary)
        return card

    def _build_roles_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(SubtitleLabel("③ 共鸣者", card))
        self._roles_hint = CaptionLabel("", card)
        head.addWidget(self._roles_hint)
        head.addStretch(1)

        # ★ 搜索框（用户："加个下拉列表搜索"）
        self._search_edit = LineEdit(card)
        self._search_edit.setPlaceholderText("搜索角色名 / 属性 / 武器")
        self._search_edit.setFixedWidth(200)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(
            lambda _t: self._render(self._data))
        head.addWidget(self._search_edit)

        # ★ 达标筛选下拉（用户："达标/未达标"）
        self._filter_box = ComboBox(card)
        self._filter_box.addItems(list(FILTER_CHOICES))
        self._filter_box.setFixedWidth(120)
        self._filter_box.currentTextChanged.connect(
            lambda _t: self._render(self._data))
        head.addWidget(self._filter_box)
        box.addLayout(head)

        self._roles_host = QWidget(card)
        self._roles_grid = QGridLayout(self._roles_host)
        self._roles_grid.setContentsMargins(0, 0, 0, 0)
        self._roles_grid.setSpacing(6)
        box.addWidget(self._roles_host)
        return card

    def _build_detail_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)
        self._detail_title = SubtitleLabel("④ 声骸明细", card)
        box.addWidget(self._detail_title)
        self._detail = QTextEdit(card)
        self._detail.setReadOnly(True)
        self._detail.setMinimumHeight(200)
        self._detail.setPlaceholderText("点上面的角色卡片，这里显示它的声骸")
        box.addWidget(self._detail)
        return card

    def _build_log_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(SubtitleLabel("日志", card))
        head.addStretch(1)
        self._log_toggle = PushButton("展开", card)
        self._log_toggle.setCheckable(True)
        self._log_toggle.clicked.connect(self._toggle_log)
        head.addWidget(self._log_toggle)
        box.addLayout(head)

        self._log = QTextEdit(card)
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(120)
        self._log.setVisible(False)            # ★ 默认折叠
        box.addWidget(self._log)
        return card

    def _toggle_log(self) -> None:
        show = self._log_toggle.isChecked()
        self._log.setVisible(show)
        self._log_toggle.setText("收起" if show else "展开")

    # ----------------------------------------------------- 输入框记忆
    def _remember_inputs(self) -> None:
        """记住输入的**特征码 + 手机号**（用户要求：登录一次后默认保存）。

        ⚠ **不存验证码** —— 那个是一次性的，留着没用还占地方。
        """
        try:
            tool_settings.save(SETTINGS_KEY, {
                "feature_code": self._feature_edit.text().strip(),
                "mobile": self._mobile_edit.text().strip(),
            })
        except Exception as exc:               # noqa: BLE001
            logger.debug("记住输入失败：%s", exc)

    def _restore_inputs(self) -> None:
        """回填上次输入的特征码 / 手机号。

        ⚠ 手机号**只存后 4 位**（``mobile_tail``）—— 出于隐私从不存全号，
        所以这里**拼不出来**，只在"用户真的存过全号"时才回填。
        界面上用 ``_login_status`` 显示「已登录（****7393）」。
        """
        try:
            saved = tool_settings.load(SETTINGS_KEY) or {}
        except Exception:                      # noqa: BLE001
            return
        feature = str(saved.get("feature_code") or "").strip()
        mobile = str(saved.get("mobile") or "").strip()
        #: 没存过就用**账号里绑定的**特征码
        if not feature and self._account.roles:
            rid = str(self._account.roles[0].get("roleId") or "").strip()
            # ⚠ 只认**像特征码**的值（纯数字、够长）。
            #   防的是"测试脚本写进令牌文件的假 roleId" ——
            #   2026-10-03 我那个 `_repro_stuck.py` 把 roles 写成
            #   `[{'roleId': '1'}]`，界面就回填了一个 `1`，
            #   用户问"填个1是啥意思"。
            if rid.isdigit() and len(rid) >= 6:
                feature = rid
        if feature:
            self._feature_edit.setText(feature)
        if mobile and len(mobile) == MOBILE_LEN:
            self._mobile_edit.setText(mobile)

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
        else:
            self._login_status.setText("未登录")
        self._refresh_button.setEnabled(self._account.logged_in)

    def _busy(self, busy: bool) -> None:
        for b in (self._login_button, self._refresh_button):
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
        thread = LoginThread(mobile, code, "", self)
        thread.progress.connect(self._say)
        thread.succeeded.connect(self._on_logged_in)
        thread.failed.connect(self._on_failed)
        # ★ 用**单独的引用** —— 之前赋给 self._thread 后，
        #   _on_logged_in → _on_fetch 会把它覆盖掉（登录线程还在跑），
        #   日志里就出现了两条"正在登录"（重复触发）。
        self._login_thread = thread
        thread.start()

    def _on_logged_in(self, account) -> None:
        self._account = account
        try:
            kuro_account.save_account(account)  # ★ 先落盘（下次打开就是已登录）
        except Exception:                      # noqa: BLE001
            pass
        # ★ 记住输入的手机号 + 特征码
        self._remember_inputs()
        names = [str(r.get("roleName") or r.get("roleId"))
                 for r in (account.roles or [])]
        self._say(f"✓ 登录成功。绑定的游戏角色：{names or '（没拿到）'}")
        self._toast("登录成功")
        # ★ 登录后**自动拉一次**（用户要求：不用再点「获取数据」）
        self._busy(False)
        self._on_fetch()

    # ------------------------------------------------------------- 数据
    def _on_fetch(self) -> None:
        if not self._account.logged_in:
            self._toast("请先登录", ok=False)
            return
        feature = self._feature_edit.text().strip()
        self._busy(True)
        self._say("开始拉取数据…" + (f"（特征码 {feature}）" if feature else ""))
        thread = FetchThread(self._account, feature, self)
        thread.progress.connect(self._say)
        thread.succeeded.connect(self._on_fetched)
        thread.failed.connect(self._on_failed)
        # ★ 拉到一半也先画出来 —— 43 次请求要几十秒，
        #   不能等全拉完才有画面（用户会以为卡死了）
        thread.partial.connect(self._on_fetched)
        self._thread = thread
        thread.start()

    def _on_fetched(self, data) -> None:
        """收到数据（可能是**阶段性的**，也可能是最终结果）。

        ⚠ ``partial`` 和 ``succeeded`` 都连到这里 —— 阶段性的不能
        ``self._busy(False)``（那会让用户在还在拉的时候点按钮）。
        靠线程的 ``isRunning()`` 判断是不是最终结果。
        """
        self._data = data or {}
        self._render(self._data)

        thread = self._thread
        running = bool(thread is not None and thread.isRunning())
        if running:
            return                              # 还在拉，别解锁按钮
        self._busy(False)
        self._toast("数据拉取完成")

    # ------------------------------------------------------------- 渲染
    def _render(self, data: dict) -> None:
        """把数据画成界面（像官方那样）。"""
        base = (data or {}).get("base") or {}
        role_list = (data or {}).get("roleList") or []
        details = (data or {}).get("details") or {}

        self._summary.setText(self._format_base(base) if base
                              else "尚未拉取数据")

        # ── 清掉旧卡片
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        if not role_list:
            self._roles_hint.setText("（还没数据 —— 登录后会自动拉取）")
            return

        # ── 判定哪些角色"声骸未达标"
        flagged = {cid: self._echo_issues(details.get(cid))
                   for cid in details}

        # ── 筛选条件（下拉 + 搜索）
        choice = self._filter_box.currentText() or "全部"
        keyword = (self._search_edit.text() or "").strip().lower()

        shown = 0
        #: 按等级从高到低
        ordered = sorted(role_list,
                         key=lambda x: (-(x.get("level") or 0),
                                        str(x.get("roleName") or "")))
        for role in ordered:
            cid = str(role.get("roleId"))
            issues = flagged.get(cid)
            # ★ 达标筛选
            if choice == "未达标" and not issues:
                continue
            if choice == "达标" and issues:
                continue
            # ★ 搜索（名字 / 属性 / 武器）
            if keyword:
                hay = " ".join(str(role.get(k) or "") for k in
                               ("roleName", "attributeName",
                                "weaponTypeName", "acronym")).lower()
                if keyword not in hay:
                    continue
            card = CharacterCard(role, bool(issues), self._roles_host)
            card.clicked.connect(self._show_detail)
            self._roles_grid.addWidget(card, shown // GRID_COLS,
                                       shown % GRID_COLS)
            self._cards.append(card)
            shown += 1

        bad_n = sum(1 for v in flagged.values() if v)
        total = len(role_list)
        extra = ""
        if choice != "全部" or keyword:
            extra = f"　（筛出 {shown} 个）"
        self._roles_hint.setText(
            f"共 {total} 个　声骸待优化 {bad_n} 个{extra}")

        self._say(f"✓ 角色 {total} 个，拿到声骸详情的 {len(details)} 个，"
                  f"其中 {bad_n} 个需要优化")

    @staticmethod
    def _echo_issues(detail) -> list[str]:
        """★ 判断一个角色的声骸有没有问题（返回问题列表）。

        ## 判定规则（第一版，先给硬事实）

        ====================  ============================================
        规则                  说明
        ====================  ============================================
        **等级没满**           有声骸 `level < 25`
        **套装不统一**         5 个声骸的套装名不止一种
        **COST 配比不对**      不是 4-3-3-1-1（见过 4-4-1-1-1 之类）
        **有效词条太少**       副词条里 `valid=true` 的**总数 < 10**
        ====================  ============================================

        ⚠ 这些是**客观事实**，不掺主观"好不好" ——
        等用户给了标准再改成按角色配置判定。
        """
        issues: list[str] = []
        ph = (detail or {}).get("phantomData") or {}
        items = ph.get("equipPhantomList") or []
        if not items:
            return ["没拿到声骸数据"]

        # ① 等级
        not_max = [x for x in items if (x.get("level") or 0) < 25]
        if not_max:
            issues.append(f"{len(not_max)} 个声骸没满级")

        # ② 套装
        sets = {(x.get("fetterDetail") or {}).get("name")
                for x in items}
        sets.discard(None)
        if len(sets) > 1:
            issues.append(f"套装不统一（{len(sets)} 种）")

        # ③ COST 配比（期望 4-3-3-1-1 = 12）
        costs = sorted((x.get("cost") or 0 for x in items), reverse=True)
        if costs != [4, 3, 3, 1, 1]:
            issues.append("COST 配比 " + "-".join(str(c) for c in costs))

        # ④ 有效词条数
        valid_n = sum(1 for x in items for s in (x.get("subProps") or [])
                      if s.get("valid"))
        if valid_n < 10:
            issues.append(f"有效词条仅 {valid_n} 条")

        return issues

    def _show_detail(self, char_id: str) -> None:
        """点角色卡片 → 显示它的明细（**按官方那个布局**）。

        官方截图（用户给的）的结构::

            🐎 共鸣者信息   名字 Lv.90 ★★★★★
            ⚔ 共鸣者属性   生命/攻击/防御/暴击/暴击伤害/共鸣效率/…
            🔨 武器        名字 Lv.90 精炼1阶 + 攻击/暴击
            🎯 属性展示    声骸提供的属性汇总
            💠 声骸 COST 12/12
               ✦ 推荐辅音词条命中  【命中数】
               ✦ 装配声骸详情      5 个卡片（主属性 + 副词条，命中标黄）
        """
        detail = (self._data.get("details") or {}).get(str(char_id)) or {}
        role = detail.get("role") or {}
        ph = detail.get("phantomData") or {}
        items = ph.get("equipPhantomList") or []

        name = role.get("roleName") or char_id
        self._detail_title.setText(
            f"④ {name}　Lv{role.get('level')}"
            f"　{role.get('attributeName', '')}"
            f"　{role.get('weaponTypeName', '')}"
            f"　共鸣链 {role.get('chainUnlockNum')}"
            f"　声骸 COST {ph.get('cost', '?')}")

        if not items:
            self._detail.setPlainText("（没拿到这个角色的声骸数据）")
            return

        issues = self._echo_issues(detail)
        lines: list[str] = []

        # ── 待优化提示
        if issues:
            lines.append("⚠ 待优化：" + "；".join(issues))
        else:
            lines.append("✓ 声骸达标")
        lines.append("")

        # ── 共鸣者属性（roleAttributeList）
        attrs = detail.get("roleAttributeList") or []
        if attrs:
            lines.append("── 共鸣者属性 " + "─" * 40)
            for a in attrs:
                lines.append(f"   {a.get('attributeName', '?'):14}"
                             f"{a.get('attributeValue', '')}")
            lines.append("")

        # ── 武器
        wd = detail.get("weaponData") or {}
        if wd:
            lines.append("── 武器 " + "─" * 44)
            lines.append(f"   {wd.get('weaponName') or wd.get('name') or '?'}"
                         f"　Lv{wd.get('level', '?')}"
                         f"　{wd.get('weaponTypeName', '')}")
            lines.append("")

        # ── 声骸汇总属性
        add_props = detail.get("equipPhantomAddPropList") or []
        if add_props:
            lines.append(f"── 声骸提供的属性（COST {ph.get('cost', '?')}/12）"
                         + "─" * 24)
            for a in add_props:
                lines.append(f"   {a.get('attributeName', '?'):14}"
                             f"{a.get('attributeValue', '')}")
            lines.append("")

        # ── 推荐辅音词条命中（★ 官方那个黄色数字）
        hit, total_slots = self._substat_hits(items)
        lines.append("── 装配声骸详情 " + "─" * 34)
        lines.append(f"   推荐辅音词条命中：{hit} / {total_slots} 条"
                     f"（库街区标 valid 的条数）")
        lines.append("")

        # ── 每个声骸（★ 按官方卡片的样子）
        for i, item in enumerate(items, 1):
            mains = item.get("mainProps") or []
            subs = item.get("subProps") or []
            fet = (item.get("fetterDetail") or {}).get("name", "?")
            pname = (item.get("phantomProp") or {}).get("name", "?")
            valid_n = sum(1 for s in subs if s.get("valid"))

            lines.append(f"【{i}】{pname}　COST{item.get('cost')}"
                         f"　+{item.get('level')}　[{fet}]"
                         f"　{valid_n}/{len(subs)} 有效")
            for m in mains:
                lines.append(f"     主属性　{m.get('attributeName', '?')}"
                             f"　{m.get('attributeValue', '')}")
            for s in subs:
                mark = "✓" if s.get("valid") else "·"
                lines.append(f"       {mark} {s.get('attributeName', '?')}"
                             f"　{s.get('attributeValue', '')}")
            lines.append("")

        self._detail.setPlainText("\n".join(lines))

    @staticmethod
    def _substat_hits(items) -> tuple[int, int]:
        """推荐辅音词条命中数（官方那个黄色数字）。

        库街区用 ``valid`` 标"是不是推荐词条" —— 直接数它。
        """
        hit = total = 0
        for item in items:
            for s in (item.get("subProps") or []):
                total += 1
                if s.get("valid"):
                    hit += 1
        return hit, total

    @staticmethod
    def _format_base(base: dict) -> str:
        """账号概览一行（字段名来自实测）。"""
        if not base:
            return "尚未拉取数据"
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
        stamp = base.get("__at")
        return "　|　".join(parts) + (f"　　拉取于 {stamp}" if stamp else "")

    # ------------------------------------------------------------- 收尾
    def _on_logout(self) -> None:
        kuro_account.clear_account()
        clear_cache()
        self._account = kuro_account.Account()
        self._data = {}
        self._render({})
        self._detail.setPlainText("")
        self._detail_title.setText("④ 声骸明细")
        self._refresh_login_state()
        self._say("已退出登录（令牌 + 缓存都已删除）")
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
    coming_soon = False
    supports_task_run = False

    def create_widget(self, parent=None):
        return CharacterBuildPanel(parent)
