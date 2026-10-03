# -*- coding: utf-8 -*-
"""内嵌浏览器登录库街区 —— 人机验证 / 短信由**用户本人**完成，我们只取 token。

## 为什么非要做成这样

2026-10-03 实测：``POST /user/getSmsCode`` 返回::

    {"code":200, "data":{"geeTest":true}, "msg":"请求成功", "success":true}

**``code`` 是 200，但短信根本没发** —— ``geeTest: true`` 表示服务端要求先过
「极验」人机验证。我第一版只看 ``code == 200`` 就报"已发送"，
用户反馈"我手机没收到短信"才暴露出来。

极验要跑 JS + 采集行为轨迹，**纯 Python 做不了**，硬做也违背它的用意。

## 所以

让用户在一个**真实浏览器窗口**里正常登录（自己过人机验证、收短信），
登录成功后官方页面会把 token 写进 ``localStorage.auth_token``
（实测 key 名，见下），我们从窗口里**读出来存到本地**。之后就不用再登了。

## ★ 实测拿到的 localStorage 结构（2026-10-03）

未登录时就存在的 key::

    auth        用户信息 JSON（未登录时是空壳）
    auth_token  ★ **token 就在这里**（未登录时是空串）
    dc          ★ **动态 devCode** —— 不是固定值！
    isa / mc / KJQ_* / Hm_*   其它无关的

⚠ **``dc`` 是动态的**：官方页面每次会写一个新的 devCode。
我第一版把文档里的固定 devcode 硬编码进请求头，那也可能是发不出短信的原因之一。
登录成功后要把它一起带走，后续请求才和这次会话一致。

## 一点安全考虑

* 用**独立的 QWebEngineProfile**（``kuro_login``），不碰用户平时的浏览器数据；
  也便于「退出登录」时连带清掉。
* 取到 token 立刻写进 :mod:`src.core.kuro_account` 的令牌文件，
  浏览器窗口关掉、profile 里的痕迹清掉。
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    PushButton,
    SubtitleLabel,
)

logger = logging.getLogger(__name__)

#: ★★ 登录入口 —— **必须是论坛首页**，不能是 ``https://www.kurobbs.com/``。
#:
#: ## 2026-10-03 实测（用户："这也没办法登陆啊"）
#:
#: 我第一版写的是 ``https://www.kurobbs.com/`` —— 那个地址会**跳转到
#: ``main.html``，页面上只有页脚**（版权信息 / 友情链接），
#: **没有任何登录按钮**，用户打开窗口后无从下手。
#:
#: 实测对比::
#:
#:     https://www.kurobbs.com/          → 跳 main.html，只有页脚，**无登录入口**
#:     https://www.kurobbs.com/mc/home/9 → ★ 正常渲染，有「立即登录」按钮
#:
#: 而 ``/login.html``、``/pc/login.html`` 这些猜出来的地址都返回
#: ``NoSuchKey``（OSS 错误页）—— 说明**没有独立登录页**，
#: 登录是论坛首页上的一个弹窗。
LOGIN_URL = "https://www.kurobbs.com/mc/home/9"

#: 自动点一下「立即登录」，把登录弹窗拉出来。
#:
#: ⚠ 不点的话用户还得自己找那个按钮（它在页面顶部，SPA 渲染完才出现）。
#: 点完页面会出现两个输入框（实测）::
#:
#:     请输入手机号码
#:     请输入6位验证码
_CLICK_LOGIN_JS = r"""
(function () {
    var all = document.querySelectorAll("button,a,div,span");
    for (var i = 0; i < all.length; i++) {
        var e = all[i];
        if (e.children.length > 0) continue;
        var t = (e.innerText || "").trim();
        if (t === "立即登录" || t === "登录" || t === "登录/注册") {
            e.click();
            return t;
        }
    }
    return "";
})();
"""

#: profile 名字 —— 独立于用户平时的浏览器数据
PROFILE_NAME = "kuro_login"

#: token 在 localStorage 里的 key（**实测**，见模块文档）
TOKEN_KEY = "auth_token"
#: 动态 devCode 的 key（**实测**）
DEV_CODE_KEY = "dc"
#: 用户信息的 key
AUTH_KEY = "auth"

#: 轮询间隔（毫秒）—— 每 1.5 秒看一眼登录了没
POLL_MS = 1500

#: 读取 localStorage 的脚本。返回 JSON 字符串。
_READ_JS = """
(function () {
    try {
        return JSON.stringify({
            token: localStorage.getItem(%s) || "",
            dc: localStorage.getItem(%s) || "",
            auth: localStorage.getItem(%s) || ""
        });
    } catch (e) { return JSON.stringify({error: String(e)}); }
})();
""" % (json.dumps(TOKEN_KEY), json.dumps(DEV_CODE_KEY),
       json.dumps(AUTH_KEY))


class KuroLoginDialog(QDialog):
    """内嵌浏览器登录框。

    用法::

        dlg = KuroLoginDialog(parent)
        if dlg.exec() == QDialog.Accepted:
            account = dlg.result_account      # 已经落盘的 Account

    登录成功（检测到 localStorage 里有 token）会自动关窗。
    """

    #: 检测到登录成功 —— 参数是 ``(token, dev_code, auth_raw)``
    logged_in = Signal(str, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("登录库街区")
        self.resize(980, 760)

        self.result_token = ""
        self.result_dev_code = ""
        self.result_auth = ""
        self._closed_by_user = False

        # ---- 布局 ----
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(SubtitleLabel("登录库街区", self))
        root.addWidget(BodyLabel(
            "在下面的窗口里正常登录（人机验证和短信验证码都由你本人完成）。"
            "登录成功后窗口会自动关闭，令牌只存在本机，下次不用再登。", self))

        # ---- 浏览器 ----
        # ★ 独立 profile：不碰用户平时的浏览器数据
        self._profile = QWebEngineProfile(PROFILE_NAME, self)
        self._page = QWebEnginePage(self._profile, self)
        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        root.addWidget(self._view, 1)

        # ---- 底部 ----
        row = QHBoxLayout()
        self._status = CaptionLabel("等待登录…", self)
        row.addWidget(self._status, 1)

        self._reload = PushButton("重新加载", self)
        self._reload.clicked.connect(self._view.reload)
        row.addWidget(self._reload)

        self._cancel = PushButton("取消", self)
        self._cancel.clicked.connect(self._on_cancel)
        row.addWidget(self._cancel)
        root.addLayout(row)

        # ---- 轮询 ----
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        # ★ 页面加载完**自动点一下「立即登录」**，把登录弹窗拉出来 ——
        #   不然用户得自己在页面顶部找那个按钮（SPA 渲染完才出现，
        #   上一版就是因为地址不对、压根没这个按钮，用户无从下手）。
        self._page.loadFinished.connect(self._on_page_loaded)
        self._view.setUrl(QUrl(LOGIN_URL))

    # ------------------------------------------------------------- 页面
    def _on_page_loaded(self, ok: bool) -> None:
        """页面加载完 —— 等 SPA 渲染出来再点「立即登录」。"""
        if not ok:
            self._status.setText("页面加载失败，点「重新加载」再试")
            return
        # SPA 要一会儿才把按钮渲染出来，等 3 秒
        QTimer.singleShot(3000, self._click_login)

    def _click_login(self) -> None:
        def report(result) -> None:
            if result:
                self._status.setText("登录框已弹出 —— 请填手机号和验证码")
            else:
                self._status.setText(
                    "没找到「立即登录」按钮 —— 请自己在页面上点一下")

        try:
            self._page.runJavaScript(_CLICK_LOGIN_JS, report)
        except Exception as exc:               # noqa: BLE001
            logger.debug("点「立即登录」失败：%s", exc)

    # ------------------------------------------------------------- 轮询
    def _poll(self) -> None:
        """看 localStorage 里有没有 token —— 有就说明登录成功了。"""
        try:
            self._page.runJavaScript(_READ_JS, self._on_read)
        except Exception as exc:               # noqa: BLE001 - 页面没准备好
            logger.debug("读 localStorage 失败：%s", exc)

    def _on_read(self, result) -> None:
        if not result:
            return
        try:
            data = json.loads(result)
        except Exception:                      # noqa: BLE001
            return
        token = str(data.get("token") or "").strip()
        if not token:
            return
        self.result_token = token
        self.result_dev_code = str(data.get("dc") or "").strip()
        self.result_auth = str(data.get("auth") or "")
        self._status.setText("登录成功，正在保存…")
        self._timer.stop()
        self.logged_in.emit(self.result_token, self.result_dev_code,
                            self.result_auth)
        self.accept()

    # ------------------------------------------------------------- 收尾
    def _on_cancel(self) -> None:
        self._closed_by_user = True
        self._timer.stop()
        self.reject()

    def closeEvent(self, event) -> None:       # noqa: N802 - Qt 接口
        self._timer.stop()
        super().closeEvent(event)

    def parsed_auth(self) -> dict:
        """``auth`` 那个字段是 JSON 字符串，解出来（解不开就空 dict）。"""
        try:
            value = json.loads(self.result_auth or "{}")
        except Exception:                      # noqa: BLE001
            return {}
        return value if isinstance(value, dict) else {}
