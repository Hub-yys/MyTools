# -*- coding: utf-8 -*-
"""库街区「数据终端」客户端 —— 登录取 token + 拉玩家账号数据。

## 这是**另一套接口**，别和 wiki 混

============================  ====================================  ==========
用途                           前缀                                  认证
============================  ====================================  ==========
图鉴数据（套装/声骸/角色）      ``api.kurobbs.com/wiki/...``          **公开，无 token**
**账号数据（本模块）**          ``api.kurobbs.com/aki/...``           **必须登录 token**
============================  ====================================  ==========

图鉴那套在 :mod:`src.core.wuwa_update` 里，**这两个不要互相 import**。

## 接口从哪来的

用户截图的网页 ``web-static.kurobbs.com/mcbox``（库街区「数据终端」），
把它的 JS bundle 拉下来，扒出全部路径（实测可解析）：

    /aki/roleBox/akiBox/baseData        结晶波片/活跃度/游戏天数/联觉等级/角色数
    /aki/roleBox/akiBox/roleData        共鸣者列表（等级/共鸣链）
    /aki/roleBox/akiBox/calabashData    数据坞信息 + 声骸收集进度
    /aki/roleBox/akiBox/exploreIndex    探索数据（地图探索度）
    /aki/roleBox/akiBox/challengeIndex  挑战数据
    /aki/roleBox/akiBox/towerIndex      逆境深塔
    /aki/roleBox/akiBox/slashIndex      逆境深塔·超载区
    /aki/roleBox/akiBox/getRoleDetail   **单个角色的详情（含 phantomList 声骸）**
    /aki/roleBox/akiBox/phantomData     声骸图鉴
    /aki/roleBox/akiBox/getAllSubProps  **副词条列表（含官方 recommend 推荐）**
    /aki/roleBox/requestToken           换 token

## 登录链路（★ 2026-10-03 **实测**验证过，不是照抄文档）

    POST /user/getSmsCode   {mobile, devCode, gameList}
        → 实测回 ``10000 手机号格式有误``（说明接口存在、在校验参数）
    POST /user/sdkLogin     {mobile, code, devCode, gameList}
        → 实测回 ``132 验证码已经过期``（说明接口存在）

⚠ 两个接口都**不需要登录态**（带了 token 反而多余）。

## 请求头

从 API 文档抄的**最小集**（实测够用）::

    osversion / devcode / countrycode / source / lang / version /
    versioncode / model / User-Agent: okhttp/3.10.0
    Content-Type: application/x-www-form-urlencoded
    distinct_id: <每次随机 uuid>

登录之后所有 ``/aki/...`` 接口再额外带 ``token``。

## 令牌存哪

``data/kuro_account.json``（用户数据目录，见 :mod:`src.core.paths`）。
**文件权限收紧到仅本人可读**（能收多紧收多紧 —— 这是账号凭证）。

## 纯逻辑

本模块**不依赖 Qt**，方便单测（``tests/test_kuro_account.py``）。
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

#: 鸣潮的 gameId（固定 3）
GAME_ID_WUWA = 3
#: 渠道 id（实测 19）
CHANNEL_ID = 19
#: 隍陇 = 1（国服默认）
COUNTRY_CODE_DEFAULT = 1

#: 官方 APP 的 ``devcode``。
#:
#: ## ⚠⚠ 2026-10-03 实测：这个**不该硬编码**
#:
#: 用 QtWebEngine 真开一次 kurobbs.com，读它的 ``localStorage`` 发现官方网页版
#: 会往 ``dc`` 这个 key 写一个**动态 devCode**（每次会话不同）::
#:
#:     {"dc": "lhgTkfVoZTfbLmY07NUp4Bv6e8EGOQRd", ...}
#:
#: 用文档里那个固定值虽然有时也能通，但和真实会话不一致 ——
#: 是"发不出短信"的可疑原因之一。
#:
#: 所以 ``devCode`` 现在是**可传入的**（见 :func:`_headers`）：
#: 登录时从浏览器拿到什么就用什么，拿不到才退回这个文档值。
DEV_CODE_FALLBACK = "2fba3859fe9bfe9099f2696b8648c2c6"

#: 兼容旧名字
DEV_CODE = DEV_CODE_FALLBACK

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


def _headers(token: str = "", dev_code: str = "") -> dict[str, str]:
    """库街区 APP 的请求头（实测够用的最小集）。

    :param token: 登录令牌（没有就不带这个头）
    :param dev_code: 动态 devCode；空则退回 :data:`DEV_CODE_FALLBACK`
    """
    h = {
        "osversion": "Android",
        "devcode": dev_code or DEV_CODE_FALLBACK,
        "countrycode": "CN",
        "source": "android",
        "lang": "zh-Hans",
        "version": "1.0.9",
        "versioncode": "1090",
        "model": "2211133C",
        "distinct_id": str(uuid.uuid4()),
        "User-Agent": "okhttp/3.10.0",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if token:
        h["token"] = token
    return h


def _post(path: str, body: dict, token: str = "", dev_code: str = "",
          timeout: int = TIMEOUT) -> dict:
    """POST 一个接口，返回解析后的 JSON（**不做业务码判断**）。"""
    url = API_ROOT + path
    data = urllib.parse.urlencode(
        {k: v for k, v in body.items() if v is not None}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers=_headers(token, dev_code))
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
    """取账号绑定的游戏角色（``roleId`` / ``serverId`` 从这来）。"""
    data = _call(API_ROLE_LIST, {}, token, dev_code)
    if isinstance(data, dict):
        for key in ("list", "roles", "roleList"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


# --------------------------------------------------------------------- 查询

def fetch_base_data(token: str, role_id, server_id,
                    country_code: int = COUNTRY_CODE_DEFAULT,
                    dev_code: str = "") -> dict:
    """账号基础数据：结晶波片 / 活跃度 / 游戏天数 / 联觉等级 / 角色数。

    ⚠ ``energy`` = 结晶波片、``storeEnergy`` = 结晶单质、
    ``liveness`` = 活跃度、``activeDays`` = 游戏天数、
    ``level`` = 联觉等级、``roleNum`` = 解锁角色数。
    """
    return _base_body_call(API_BASE_DATA, token, role_id, server_id,
                           country_code, dev_code)


def fetch_role_data(token: str, role_id, server_id,
                    country_code: int = COUNTRY_CODE_DEFAULT,
                    dev_code: str = "") -> object:
    """共鸣者列表（等级 / 共鸣链 / 武器）。"""
    return _base_body_call(API_ROLE_DATA, token, role_id, server_id,
                           country_code, dev_code)


def fetch_role_detail(token: str, role_id, server_id, char_id,
                      country_code: int = COUNTRY_CODE_DEFAULT,
                      dev_code: str = "") -> dict:
    """**单个角色的详情 —— 含 ``phantomList``（身上那 5 个声骸）。**

    这是"练度对比"的数据来源：``phantomList`` 里每一项是
    ``{"phantom": {...}, "star": ..., "maxStar": ...}``（从网页 JS 的
    渲染逻辑里读出来的）。
    """
    body = _base_body(token, role_id, server_id, country_code)
    if char_id is not None:
        body["roleId"] = role_id
        body["charId"] = char_id
    return _call(API_ROLE_DETAIL, body, token, dev_code)


def fetch_all_sub_props(token: str, role_id, dev_code: str = "") -> object:
    """副词条列表 —— 网页 JS 里看到它带 ``recommend`` 字段（官方推荐）。"""
    return _call(API_ALL_SUB_PROPS, {"roleId": role_id}, token, dev_code)


def _base_body(token: str, role_id, server_id, country_code: int) -> dict:
    return {
        "gameId": GAME_ID_WUWA,
        "roleId": role_id,
        "serverId": server_id,
        "channelId": CHANNEL_ID,
        "countryCode": country_code,
    }


def _base_body_call(path: str, token: str, role_id, server_id,
                    country_code: int, dev_code: str = "") -> object:
    return _call(path, _base_body(token, role_id, server_id, country_code),
                 token, dev_code)
