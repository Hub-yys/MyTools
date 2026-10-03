# -*- coding: utf-8 -*-
"""库街区账号数据客户端 —— 登录取 token + 拉角色/声骸数据。

## ★★★ 完整可用流程（2026-10-03 **全部实测跑通**）

    ┌─ ① APP 端登录（source=android）
    │     手机号 + 短信验证码 → token
    ├─ ② 取游戏角色
    │     POST /gamer/role/list  {gameId:3}  → roleId(特征码) + serverId
    ├─ ③ 换「数据令牌」★ 打开 /aki/ 的钥匙
    │     POST /aki/roleBox/requestToken  {roleId, serverId}
    │       → accessToken（数据令牌）
    └─ ④ 之后所有 /aki/ 请求：**只带 b-at 头，不带 token**
          /aki/roleBox/akiBox/roleData         → 角色列表（含每个角色的 id）
          /aki/roleBox/akiBox/getRoleDetail    → ★ 声骸详情（body 加 id=<角色id>）

## ★★ 踩过的坑（每条都是实测，别再踩）

============================  ==========================  ============================
坑                             现象                        正解
============================  ==========================  ============================
用**网页登录**的令牌调 /aki/    ``10901 禁止访问``          **必须 APP 端登录**
``source=h5``                 ``/aki/`` 全 10901          ``source=android``
``b-at`` + ``token`` 同时带    ``10000 参数错误``          **只带 ``b-at``**
``getRoleDetail`` 参数名       ``charId``/``roleId`` 都错  真名是 **``id``**
角色 id vs 特征码               传特征码当 ``id`` → 10000   见下表
``findRoleList`` 不带 gameId    只返回**战双**的号         必须带 ``gameId=3``
serverId 当数字                 参数错误                    它是 **32 位 hex 字符串**
============================  ==========================  ============================

**两个 ``roleId`` 是完全不同的东西**（这是最容易搞混的）::

    roleId = "113152489"                    ← 特征码（**账号级**）
    id     = 1103（白芷）/ 1404（忌炎）      ← 角色 id（**角色级**）
                                              getRoleDetail 要的是**这个**

## 验证码不用自己发

**API 文档明确：验证码 APP 端与 Web 端通用。**
所以用户在**任意官方入口**（App / 网页）点"获取验证码"，
那个码就能拿来这里换 App 令牌 —— **我们不需要碰极验**
（那条路不通用，见 :func:`send_sms_code` 的说明）。

## 这是**另一套接口**，别和 wiki 混

============================  ====================================  ==============
用途                           前缀                                  认证
============================  ====================================  ==============
图鉴数据（套装/声骸/角色）      ``api.kurobbs.com/wiki/...``          **公开，无 token**
**账号数据（本模块）**          ``api.kurobbs.com/aki/...``           **数据令牌**
============================  ====================================  ==============

图鉴那套在 :mod:`src.core.wuwa_update` 里，**这两个不要互相 import**。
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- 常量

API_ROOT = "https://api.kurobbs.com"

#: 短信验证码
API_SMS_CODE = "/user/getSmsCode"
#: 验证码换 token
API_SDK_LOGIN = "/user/sdkLogin"
#: 账号绑定的游戏角色列表（拿 roleId / serverId）
API_ROLE_LIST = "/gamer/role/list"

#: 王者/数据终端各接口（都是 POST + token）
API_BASE_DATA = "/aki/roleBox/akiBox/baseData"
API_ROLE_DATA = "/aki/roleBox/akiBox/roleData"
API_CALABASH = "/aki/roleBox/akiBox/calabashData"
API_EXPLORE = "/aki/roleBox/akiBox/exploreIndex"
API_CHALLENGE = "/aki/roleBox/akiBox/challengeIndex"
API_TOWER = "/aki/roleBox/akiBox/towerIndex"
API_SLASH = "/aki/roleBox/akiBox/slashIndex"
API_ROLE_DETAIL = "/aki/roleBox/akiBox/getRoleDetail"
API_PHANTOM_DATA = "/aki/roleBox/akiBox/phantomData"
API_ALL_SUB_PROPS = "/aki/roleBox/akiBox/getAllSubProps"

#: ★★★ **换「数据令牌」** —— 这是打开 `/aki/roleBox/*` 的钥匙。
#:
#: 从数据终端 JS 里挖到的权威流程::
#:
#:     const [i, s] = await api_requestToken({roleId, serverId, userId});
#:     this.dataToken = i.data.accessToken;      // ← 数据令牌
#:     this.tokenRequire = i.data.tokenRequire;
#:
#: 之后所有 `/aki/roleBox/*` 请求带::
#:
#:     b-at: <dataToken>       ← ★ 不是 token 头！
#:     devCode: REQUEST_IP + ", " + navigator.userAgent
#:     did: <设备指纹>
API_REQUEST_TOKEN = "/aki/roleBox/requestToken"

#: 拿权威 ``userId``（`requestToken` 要它）
API_QUERY_USER_ID = "/user/role/queryUserId"

#: 鸣潮的 gameId（固定 3）
GAME_ID_WUWA = 3
#: 渠道 id（实测 19）
CHANNEL_ID = 19
#: 隍陇 = 1（国服默认）
COUNTRY_CODE_DEFAULT = 1

#: 官方 APP 的 ``devcode`` 兜底值（文档里给的固定值）。
#:
#: ## ⚠ 2026-10-03 实测：这个**不该硬编码**
#:
#: 用 QtWebEngine 真开一次 kurobbs.com，读它的 ``localStorage`` 发现官方网页版
#: 会往 ``dc`` 这个 key 写一个**动态 devCode**（每次会话不同）::
#:
#:     {"dc": "lhgTkfVoZTfbLmY07NUp4Bv6e8EGOQRd", ...}
#:
#: 所以 ``devCode`` 是**可传入的**（见 :func:`_headers`）：
#: 登录时从浏览器拿到什么就用什么，拿不到才退回这个文档值。
DEV_CODE_FALLBACK = "2fba3859fe9bfe9099f2696b8648c2c6"

#: 兼容旧名字
DEV_CODE = DEV_CODE_FALLBACK

#: 浏览器 UA —— ``source=h5``（网页端）时用。
#: ⚠ 别用 ``okhttp``：那是 App 的 UA，配 h5 会不伦不类。
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

#: 单请求超时（秒）
TIMEOUT = 30

#: 令牌文件（用户数据目录）
TOKEN_FILE_NAME = "kuro_account.json"

#: 取过一次就别在短时间内重复取（秒）—— 给"刷新"按钮一个最小间隔
MIN_REFRESH_INTERVAL = 3.0


def token_file() -> Path:
    """令牌文件位置（用户数据目录）。

    ⚠ 走 :func:`paths.user_data_dir`，打包后自动落到 ``%LOCALAPPDATA%`` ——
    绝不能写在程序目录里（装到 Program Files 时是只读的）。
    """
    return paths.user_data_dir() / TOKEN_FILE_NAME


# --------------------------------------------------------------------- 异常

class KuroError(Exception):
    """库街区接口返回了失败（带 code / msg）。"""

    def __init__(self, code, msg: str, *, path: str = "") -> None:
        self.code = code
        self.msg = msg or ""
        self.path = path
        super().__init__(f"[{code}] {self.msg}" + (f"（{path}）" if path else ""))


class TokenExpired(KuroError):
    """令牌失效 —— 需要重新登录（``code`` 220 / 1002 等）。"""


class NeedHumanVerify(KuroError):
    """★ 服务端要求**人机验证**（``data.geeTest == true``）—— 短信**没有发出去**。

    ## 这是 2026-10-03 踩的坑

    ``POST /user/getSmsCode`` 在要求人机验证时，仍然返回::

        {"code":200, "data":{"geeTest":true}, "msg":"请求成功", "success":true}

    **状态码和 ``code`` 都是成功的样子** —— 只看 ``code == 200`` 就会报
    "验证码已发送"，而用户手机一条短信都没有（用户就是这么反馈的）。

    极验要跑 JS + 采集行为轨迹，**纯 Python 绕不过去**，也不该绕。
    正路是内嵌浏览器让用户本人过验证，见
    ``src/tools/game/character_build/login_dialog.py``。
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            "库街区要求先过人机验证，短信**没有发出去**。"
            "请用「打开登录窗口」在浏览器里完成登录。",
            path=API_SMS_CODE)


#: 需要重新登录的响应码
AUTH_CODES = frozenset({220, 1002, 10900})


# --------------------------------------------------------------------- 传输

def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _headers(token: str = "", dev_code: str = "",
             data_token: str = "", source: str = "android") -> dict[str, str]:
    """库街区 APP 的请求头（实测够用的最小集）。

    :param token: 登录令牌（没有就不带这个头）
    :param dev_code: 动态 devCode；空则退回 :data:`DEV_CODE_FALLBACK`
    :param data_token: ★ **数据令牌** —— `/aki/roleBox/*` 要的是它，
        走 ``b-at`` 头（见 :data:`API_REQUEST_TOKEN` 的说明）
    :param source: ★ ``android``（App 端）/ ``h5``（网页端）。
        **实测有区别**：``/user/role/*`` 用 h5 通、用 android 回 220。
    """
    h = {
        "osversion": "Android",
        "devcode": dev_code or DEV_CODE_FALLBACK,
        "countrycode": "CN",
        "source": source,
        "lang": "zh-Hans",
        "version": "1.0.9",
        "versioncode": "1090",
        "model": "2211133C",
        "distinct_id": str(uuid.uuid4()),
        "User-Agent": "okhttp/3.10.0" if source == "android"
                      else _BROWSER_UA,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if token:
        h["token"] = token
    if data_token:
        h["b-at"] = data_token
    return h


def _post(path: str, body: dict, token: str = "", dev_code: str = "",
          timeout: int = TIMEOUT, data_token: str = "",
          source: str = "android") -> dict:
    """POST 一个接口，返回解析后的 JSON（**不做业务码判断**）。"""
    url = API_ROOT + path
    data = urllib.parse.urlencode(
        {k: v for k, v in body.items() if v is not None}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers=_headers(token, dev_code, data_token, source))
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:                      # noqa: BLE001
            raise KuroError(exc.code, raw[:200] or f"HTTP {exc.code}",
                            path=path) from exc
        raise KuroError(payload.get("code", exc.code),
                        payload.get("msg", ""), path=path) from exc
    except Exception as exc:                   # noqa: BLE001 - 网络层
        raise KuroError(None, f"{type(exc).__name__}: {exc}", path=path) from exc

    try:
        return json.loads(raw)
    except Exception as exc:                   # noqa: BLE001
        raise KuroError(None, f"返回的不是 JSON：{raw[:160]}",
                        path=path) from exc


def _call(path: str, body: dict, token: str = "",
          dev_code: str = "") -> object:
    """POST 并**检查业务码**，成功时返回 ``data``。

    ``data`` 有时是**字符串形式的 JSON**（``baseData`` 就是），这里统一解开，
    调用方不用管。
    """
    payload = _post(path, body, token, dev_code)
    code = payload.get("code")
    if code != 200:
        msg = str(payload.get("msg") or "")
        if code in AUTH_CODES:
            raise TokenExpired(code, msg, path=path)
        raise KuroError(code, msg, path=path)
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:                      # noqa: BLE001 - 不是 JSON 就原样返回
            pass
    return data


# --------------------------------------------------------------------- 令牌

@dataclass
class Account:
    """登录后存下来的账号信息。"""

    token: str = ""
    #: ★ **动态 devCode** —— 内嵌浏览器登录时从 ``localStorage.dc`` 取到。
    #: 空则请求时退回 :data:`DEV_CODE_FALLBACK`。
    dev_code: str = ""
    #: ★★★ **数据令牌** —— `/aki/roleBox/*`（角色 / 声骸数据）要的是它。
    #: 由 :func:`request_data_token` 用「特征码 + serverId + userId」换来，
    #: 走 ``b-at`` 请求头。**普通的登录 token 对那套接口无效。**
    data_token: str = ""
    #: 权威 ``userId``（换数据令牌要用）
    user_id: str = ""
    #: 登录用的手机号（只存后 4 位用于显示，**不存全号**）
    mobile_tail: str = ""
    #: ``{"userId":..., "nickname":..., ...}`` —— 接口返回什么存什么
    profile: dict = field(default_factory=dict)
    #: 绑定的游戏角色 ``[{"roleId":..., "serverId":..., "roleName":...}]``
    roles: list = field(default_factory=list)
    #: 上次登录成功的时间戳
    login_at: float = 0.0

    @property
    def logged_in(self) -> bool:
        return bool(self.token)


def save_account(account: Account, path: Path | None = None) -> Path:
    """写令牌文件，并把权限**收紧到仅本人可读**。"""
    target = path or token_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "token": account.token,
        "dev_code": account.dev_code,
        "data_token": account.data_token,
        "user_id": account.user_id,
        "mobile_tail": account.mobile_tail,
        "profile": account.profile,
        "roles": account.roles,
        "login_at": account.login_at,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    _harden(target)
    return target


def _harden(path: Path) -> None:
    """尽量把文件权限收成"只有本人"。失败不影响功能（Windows 上常失败）。"""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:                          # noqa: BLE001
        pass


def load_account(path: Path | None = None) -> Account:
    """读令牌文件；不存在 / 坏了都返回空账号（**不报错**）。"""
    target = path or token_file()
    if not target.is_file():
        return Account()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:                   # noqa: BLE001
        logger.warning("令牌文件读不出来（%s）：%s", target, exc)
        return Account()
    if not isinstance(raw, dict):
        return Account()
    return Account(
        token=str(raw.get("token") or ""),
        dev_code=str(raw.get("dev_code") or ""),
        data_token=str(raw.get("data_token") or ""),
        user_id=str(raw.get("user_id") or ""),
        mobile_tail=str(raw.get("mobile_tail") or ""),
        profile=raw.get("profile") or {},
        roles=raw.get("roles") or [],
        login_at=float(raw.get("login_at") or 0.0),
    )


def clear_account(path: Path | None = None) -> None:
    """退出登录：删掉令牌文件。"""
    target = path or token_file()
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:                   # noqa: BLE001
        logger.warning("删令牌文件失败（%s）：%s", target, exc)


# --------------------------------------------------------------------- 登录

def send_sms_code(mobile: str) -> None:
    """给手机号发短信验证码。

    ## ★★ 2026-10-03：我在这里犯过一个错，用户"手机没收到短信"

    实测响应::

        {"code":200, "data":{"geeTest":true}, "msg":"请求成功", "success":true}

    **``code`` 是 200，但短信根本没发** —— ``geeTest: true`` 表示服务端
    要求先过「极验」人机验证。我第一版只看 ``code == 200`` 就报"已发送"，
    界面上写着成功、用户手机一条短信都没有。

    **所以现在必须检查 ``data.geeTest``**，为真就抛 :class:`NeedHumanVerify`。

    ⚠ 这条路（自带短信登录）实际上**走不通**了 —— 极验要跑 JS + 采行为轨迹，
    纯 Python 做不到。真正能用的是内嵌浏览器登录（见
    ``src/tools/game/character_build/login_dialog.py``），
    人机验证由用户本人完成。

    :raises NeedHumanVerify: 服务端要求人机验证（**短信没发出去**）
    """
    payload = _post(API_SMS_CODE, {
        "mobile": mobile, "devCode": DEV_CODE_FALLBACK, "gameList": "",
    })
    code = payload.get("code")
    if code != 200:
        raise KuroError(code, str(payload.get("msg") or ""))

    # ★★ 关键：code=200 也可能是"要求人机验证"，此时短信**没有发**
    data = payload.get("data")
    if isinstance(data, dict) and data.get("geeTest"):
        raise NeedHumanVerify()


def check_sms_result(payload: dict) -> None:
    """给测试用的纯函数版：判断一个 getSmsCode 响应是不是"真发出去了"。

    :raises NeedHumanVerify: ``data.geeTest`` 为真（短信没发）
    :raises KuroError: 业务码不是 200
    """
    code = payload.get("code")
    if code != 200:
        raise KuroError(code, str(payload.get("msg") or ""))
    data = payload.get("data")
    if isinstance(data, dict) and data.get("geeTest"):
        raise NeedHumanVerify()


def login_with_code(mobile: str, code: str,
                    dev_code: str = "") -> Account:
    """用验证码换 token，成功返回 :class:`Account`（**不落盘**，由调用方决定）。

    ⚠ **这条路现在基本走不通** —— 发验证码那一步要先过极验，见
    :class:`NeedHumanVerify`。真正能用的是内嵌浏览器登录
    （``src/tools/game/character_build/login_dialog.py``）。

    保留这个函数是因为：① 极验以后可能取消；② 万一有别的渠道能拿到验证码。
    """
    data = _call(API_SDK_LOGIN, {
        "mobile": mobile, "code": code,
        "devCode": dev_code or DEV_CODE_FALLBACK, "gameList": "",
    }, dev_code=dev_code)
    if not isinstance(data, dict):
        raise KuroError(None, f"登录返回的结构不认识：{str(data)[:120]}")

    token = str(data.get("token") or "")
    if not token:
        raise KuroError(None, "登录成功但没拿到 token")

    account = Account(
        token=token,
        dev_code=dev_code,
        mobile_tail=mobile[-4:] if len(mobile) >= 4 else "",
        profile={k: v for k, v in data.items() if k != "token"},
        login_at=time.time(),
    )
    account.roles = fetch_roles(token, dev_code)
    return account


def account_from_browser(token: str, dev_code: str = "",
                         auth: dict | None = None) -> Account:
    """★ **从内嵌浏览器拿到的东西**组装一个 :class:`Account`（不落盘）。

    这是现在**真正在用**的登录路径：用户自己在浏览器窗口里过人机验证 +
    短信验证码，之后官方页面把 token 写进 ``localStorage.auth_token``，
    我们读出来（见 ``login_dialog.KuroLoginDialog``）。

    :param token: ``localStorage.auth_token``
    :param dev_code: ``localStorage.dc``（动态 devCode）
    :param auth: ``localStorage.auth`` 解出来的用户信息（可选）
    """
    token = str(token or "").strip()
    if not token:
        raise KuroError(None, "浏览器里没读到 token —— 可能还没登录成功")

    account = Account(
        token=token,
        dev_code=str(dev_code or "").strip(),
        profile=dict(auth or {}),
        login_at=time.time(),
    )
    # 手机号只留后 4 位（信息里可能带 mobile）
    mobile = str(account.profile.get("mobile") or "")
    if mobile:
        account.mobile_tail = mobile[-4:]
        account.profile.pop("mobile", None)     # ★ 不存完整号码
    return account


def fetch_roles(token: str, dev_code: str = "") -> list:
    """取账号绑定的游戏角色（``roleId`` = 特征码、``serverId`` 从这来）。

    ## ⚠⚠ 必须带 ``gameId``（实测）

    不带 ``gameId`` 只会返回**战双**的号（``gameId: 2``），
    带 ``gameId: 3`` 才返回**鸣潮**的号。

    实测返回（鸣潮）::

        {"roleId": "113152489",                          # 特征码
         "serverId": "76402e5b20be2c39f095a152090afddc", # 32 位 hex（不是数字）
         "roleName": "银月", "activeDay": 830, "roleNum": 43,
         "gameLevel": "80", "gameId": 3, "userId": "18706178"}
    """
    data = _call(API_ROLE_LIST, {"gameId": GAME_ID_WUWA}, token, dev_code)
    if isinstance(data, dict):
        for key in ("list", "roles", "roleList"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def fetch_user_id(token: str, role_id, server_id,
                  dev_code: str = "") -> str:
    """★ 拿**权威 userId** —— :func:`request_data_token` 要用它。

    ⚠ 实测：这个接口用**网页头**（``source=h5``）能通，
    用 ``android`` 头会回 ``220``。所以这里单独指定 h5。
    """
    payload = _post(API_QUERY_USER_ID, {
        "gameId": GAME_ID_WUWA, "roleId": role_id, "serverId": server_id,
    }, token, dev_code, source="h5")
    code = payload.get("code")
    if code != 200:
        raise KuroError(code, str(payload.get("msg") or ""),
                        path=API_QUERY_USER_ID)
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:                      # noqa: BLE001
            pass
    if isinstance(data, dict):
        return str(data.get("userId") or data.get("id") or "")
    return str(data or "")


def request_data_token(token: str, role_id, server_id, user_id: str = "",
                       dev_code: str = "") -> tuple[str, bool | None]:
    """★★★ **换「数据令牌」** —— 打开 `/aki/roleBox/*` 的钥匙。

    从数据终端 JS 里挖到的权威流程::

        const [i, s] = await api_requestToken({roleId, serverId, userId});
        this.dataToken    = i.data.accessToken;
        this.tokenRequire = i.data.tokenRequire;

    :return: ``(data_token, token_require)``
    :raises KuroError: 换不到（``10901`` 等）

    ## ⚠ 令牌来源

    **实测（2026-10-03）**：用**网页登录**拿到的令牌调这个接口，
    回 ``10901 禁止访问`` —— 它认**令牌来源**。
    必须配 **APP 端登录**（:func:`app_login_with_code`）才通。

    ## ``user_id`` 可以不给

    实测三种 body 都返回同一个 accessToken::

        {roleId, serverId}
        {gameId, roleId, serverId}
        {roleId, serverId, userId}

    → 所以 ``user_id`` 是**可选**的。
    """
    body: dict = {"roleId": str(role_id), "serverId": str(server_id)}
    if user_id:
        body["userId"] = str(user_id)
    payload = _post(API_REQUEST_TOKEN, body, token, dev_code)
    code = payload.get("code")
    if code != 200:
        if code in AUTH_CODES:
            raise TokenExpired(code, str(payload.get("msg") or ""),
                               path=API_REQUEST_TOKEN)
        raise KuroError(code, str(payload.get("msg") or ""),
                        path=API_REQUEST_TOKEN)
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:                      # noqa: BLE001
            pass
    if not isinstance(data, dict):
        raise KuroError(None, f"数据令牌返回结构不认识：{str(data)[:120]}",
                        path=API_REQUEST_TOKEN)
    return (str(data.get("accessToken") or ""),
            data.get("tokenRequire"))


# --------------------------------------------------- ★ App 端登录（数据用）

def app_login_with_code(mobile: str, code: str,
                        dev_code: str = "") -> Account:
    """★★★ **用手机号 + 短信验证码走 APP 端登录** —— 拿"数据用"令牌。

    ## 为什么必须走这条路（2026-10-03 实测得出）

    `/aki/roleBox/akiBox/*`（角色 / 声骸数据）对令牌的**来源**有要求：

    ======================  ============  ================
    令牌来源                 请求头         `/aki/*` 结果
    ======================  ============  ================
    **网页登录**             ``h5``        ❌ ``10901 禁止访问``
    **网页登录**             ``android``   ❌ ``220 登录已过期``
    ======================  ============  ================

    API 文档写得很明确：这些接口的令牌要
    「从**验证码登录 APP 端**获取」——
    **网页登录拿到的令牌，`/aki/` 不认**。

    → 鸣潮工坊要用户「手机号 + 验证码」，就是为了走 **APP 端登录**。

    ## ★ 验证码不用我们自己发

    文档原话：**「APP 端与 Web 端通用」** ——
    用户随便在哪儿（网页 / App）点了"获取验证码"，
    那个码就能拿来这里换 **App 令牌**。
    所以我们**不碰极验**（那条路走不通，见 :func:`send_sms_code`）。

    :param mobile: 手机号
    :param code: 短信验证码（用户在任意官方入口获取的即可）
    :param dev_code: 动态 devCode（可空）
    """
    data = _call(API_SDK_LOGIN, {
        "mobile": mobile, "code": code,
        "devCode": dev_code or DEV_CODE_FALLBACK, "gameList": "",
    }, dev_code=dev_code)
    if not isinstance(data, dict):
        raise KuroError(None, f"登录返回的结构不认识：{str(data)[:120]}")

    token = str(data.get("token") or "")
    if not token:
        raise KuroError(None, "登录成功但没拿到 token")

    account = Account(
        token=token,
        dev_code=dev_code,
        mobile_tail=mobile[-4:] if len(mobile) >= 4 else "",
        profile={k: v for k, v in data.items() if k != "token"},
        login_at=time.time(),
    )
    account.roles = fetch_roles(token, dev_code)
    return account


# --------------------------------------------------------------------- 查询
#
# ★★★ 下面这些 `/aki/` 接口**必须用数据令牌**（``b-at`` 头），
#     而且**不能同时带**普通 ``token``（带了会变 10000 参数错误）。
#     数据令牌由 :func:`request_data_token` 换（见模块文档的流程）。

def _aki(payload_target, data_token: str, body: dict) -> object:
    """调一个 `/aki/` 接口 —— 只带 ``b-at``。

    ⚠ 实测：带 ``token`` 会变 ``10000 参数错误``；带 ``source=h5`` 会
    ``10901 禁止访问``。所以这里**固定** ``source=android`` 且不带 token。
    """
    payload = _post(payload_target, body, token="", dev_code="",
                    data_token=data_token, source="android")
    code = payload.get("code")
    if code != 200:
        if code in AUTH_CODES:
            raise TokenExpired(code, str(payload.get("msg") or ""),
                               path=payload_target)
        raise KuroError(code, str(payload.get("msg") or ""),
                        path=payload_target)
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:                      # noqa: BLE001
            pass
    return data


def fetch_base_data(data_token: str, role_id, server_id,
                    country_code: int = COUNTRY_CODE_DEFAULT) -> dict:
    """账号基础数据：结晶波片 / 活跃度 / 游戏天数 / 联觉等级 / 角色数。

    ⚠ 实测字段：``energy`` = 结晶波片、``storeEnergy`` = 结晶单质、
    ``liveness`` = 活跃度、``activeDays`` = 游戏天数、
    ``level`` = 联觉等级、``roleNum`` = 解锁角色数。
    """
    return _aki(API_BASE_DATA, data_token,
                {"gameId": GAME_ID_WUWA, "roleId": role_id,
                 "serverId": server_id, "countryCode": country_code})


def fetch_role_data(data_token: str, role_id, server_id,
                    country_code: int = COUNTRY_CODE_DEFAULT) -> dict:
    """★ 角色列表 —— 返回 ``{"roleList": [...]}``（实测 43 个角色）。

    每个角色含：``roleId``（**角色 id**，如白芷=1103）、``roleName``、
    ``level``、``chainUnlockNum``（共鸣链）、``starLevel``、
    ``attributeName``（属性）、``weaponTypeName``（武器）。

    ⚠ 这里的 ``roleId`` 是**角色 id**，和特征码（账号级 roleId）**不是一回事**。
    """
    return _aki(API_ROLE_DATA, data_token,
                {"gameId": GAME_ID_WUWA, "roleId": role_id,
                 "serverId": server_id, "countryCode": country_code})


def fetch_role_detail(data_token: str, account_role_id, server_id,
                      char_id,
                      country_code: int = COUNTRY_CODE_DEFAULT) -> dict:
    """★★★ **单个角色的声骸详情** —— 练度对比的数据来源。

    :param data_token: 数据令牌（``b-at``）
    :param account_role_id: **特征码**（账号级 roleId，如 ``113152489``）
    :param server_id: 服务器 id（32 位 hex 字符串）
    :param char_id: ★ **角色 id**（角色级，如白芷 = ``1103``）——
        从 :func:`fetch_role_data` 的 ``roleList[].roleId`` 拿

    ## 返回结构（实测）

    ::

        {
          "role": {roleName, level, chainUnlockNum, attributeName, ...},
          "phantomData": {
            "cost": 12,
            "equipPhantomList": [          # 身上 5 个声骸
              {"cost": 4, "level": 25, "quality": 5,
               "phantomProp":  {"name": "无归的谬误"},
               "fetterDetail": {"name": "隐世回光", "num": 5},
               "mainProps": [{"attributeName","attributeValue","valid"}],
               "subProps":  [{"attributeName","attributeValue","valid"}]}
            ]
          },
          "roleAttributeList": [...],
          "equipPhantomAddPropList": [...],
          "weaponData": {...}, "skillList": [...], "chainList": [...]
        }

    ⚠⚠ **参数名是 ``id``，不是 ``charId`` / ``roleId``** ——
    实测传 ``charId`` 或把特征码塞进 ``roleId`` 都会回
    ``10000 查询的角色id不能为空``。只有 ``id=<角色id>`` 才 200。
    """
    body = {"gameId": GAME_ID_WUWA, "roleId": str(account_role_id),
            "serverId": str(server_id), "countryCode": country_code}
    if char_id is not None:
        body["id"] = str(char_id)
    return _aki(API_ROLE_DETAIL, data_token, body)


def fetch_calabash(data_token: str, role_id, server_id) -> dict:
    """数据坞信息 + 声骸收集进度（含 ``phantomList``）。"""
    return _aki(API_CALABASH, data_token,
                {"gameId": GAME_ID_WUWA, "roleId": role_id,
                 "serverId": server_id})


def fetch_phantom_data(data_token: str, role_id, server_id) -> dict:
    """声骸图鉴数据（含 ``phantomList`` / ``fetters``）。"""
    return _aki(API_PHANTOM_DATA, data_token,
                {"gameId": GAME_ID_WUWA, "roleId": role_id,
                 "serverId": server_id})


def fetch_all_sub_props(data_token: str, role_id) -> object:
    """副词条列表（含官方 ``recommend`` 推荐）。

    ⚠ 实测：带 ``roleId`` + 数据令牌会回 ``102 服务器外部错误``；
    这个接口可能只在特定条件下可用 —— 暂时保留，不依赖它。
    """
    return _aki(API_ALL_SUB_PROPS, data_token, {"roleId": role_id})
