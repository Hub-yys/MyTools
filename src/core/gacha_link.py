"""从**本机游戏的日志**里读出声骸/抽卡记录链接。

用户 2026-09-30 要求"上面加个获取抽卡记录按钮，获取到后自动填充"。

## 原理（照 mc-tools 的做法，逆向确认过）

鸣潮客户端会把**带参数的抽卡记录链接**写进日志文件：

    <游戏目录>/Client/Saved/Logs/Client.log

日志是**逐行混淆**的，解出来要两步：

1. **前 3 个字节原样**；
2. 其余每字节：``(b & 1) ? b ^ 165 : b ^ 239`` —— 按最低位选不同的异或值。

解密后在里面找 ``"url":"https://…&platform=PC"``，那就是抽卡链接
（含 ``svr_id`` / ``player_id`` / ``record_id`` / ``resources_id``）。

## 为什么这是"用户主动触发"而不是开机就扫

- 它是**读本机文件**：只在用户点按钮时读，不后台常驻扫描；
- 读不到就老实说读不到，让用户走手动粘贴那条路（见 GUI 的说明）。

## 找不到游戏目录怎么办

游戏可能装在**任何盘**。这里按"常见路径 → 全盘找 Client.log"的顺序，
并把找到的目录**记到用户配置**里，下次直接用（全盘扫很慢）。
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import string
import subprocess

logger = logging.getLogger(__name__)

#: 日志相对游戏目录的位置（鸣潮的目录结构）
LOG_RELATIVE = pathlib.Path("Client/Saved/Logs/Client.log")

#: 链接在解密文本里的形态：``"url":"https://…&platform=PC"``
_URL_START = '"url":"https://'
_URL_END = "&platform=PC"
#: 认定这是抽卡链接的关键参数（缺一不可）
_REQUIRED_PARAMS = ("svr_id=", "player_id=", "record_id=")

#: 记住游戏目录的小文件（放用户数据目录）
_CONFIG_NAME = "gacha_game_dir.json"


class GrabError(Exception):
    """读链接失败。消息是**写给用户看的**。"""


def decrypt_log_line(raw: bytes) -> bytes:
    """按鸣潮客户端日志的混淆方式还原一段字节。

    ⚠ 前 3 字节**原样保留**（它们没被混淆）。

    ## ★ 必须**整块**解密，不能逐行

    这里的 ``(b & 1)`` 是**该字节自身**的最低位 —— 逐行解开在数学上等价于
    整块解开（每个字节只依赖自己）。但**实测踩过坑**：

    ``Client.log`` 里的记录**不是保证一行一条**的 —— 链接可能被写在
    超长的一行里、也可能跨行。我第一版按 ``splitlines()`` 逐行解密，
    结果**一条都没匹配到**（42663 行全落空），而整块解开立刻就找到了。

    → 所以 :func:`scan_log` 走的是**整块**解密，这个函数只是它的底层原语。
    """
    out = bytearray(len(raw))
    for index, byte in enumerate(raw):
        if index < 3:
            out[index] = byte
        else:
            out[index] = (byte ^ 165) if (byte & 1) else (byte ^ 239)
    return bytes(out)


def extract_url(text: str) -> str | None:
    """从**解密后**的文本里抠出抽卡链接；没有就返回 ``None``。

    ⚠ ``rfind`` 取**最后一个**匹配 —— 日志是追加写的，最新的链接在末尾
    （旧的容易过期，接口会回 ``code=-1``）。

    ⚠ 找到的位置**在 https:// 之后**（``_URL_START`` 本身以 ``https://`` 结尾），
    但日志里那个 ``https://`` 是在引号里的，所以拼回去时要补上协议头 ——
    否则得到一个 ``aki-gm-resources...`` 开头的残缺串（实测踩过：
    ``parse_link`` 恰好能过，但那是运气，不该依赖）。
    """
    start = text.rfind(_URL_START)
    if start < 0:
        return None
    start += len(_URL_START)
    end = text.rfind(_URL_END)
    if end < start:
        return None
    url = "https://" + text[start:end + len(_URL_END)]
    # 关键参数一个都不能少 —— 否则是别的链接（比如充值页）
    if not all(param in url for param in _REQUIRED_PARAMS):
        return None
    return url


def scan_log(path: pathlib.Path) -> str | None:
    """在日志里找抽卡链接。返回链接；找不到返回 ``None``。

    ## 实现要点（都是实测踩出来的）

    1. **整块解密**，不逐行 —— 记录不保证一行一条，逐行会一条都匹配不到
       （见 :func:`decrypt_log_line` 的说明）。
    2. **从后往前找**：日志追加写，最新的记录在**末尾**；
       而我们要的就是最新那条（旧的容易过期，接口会回 ``code=-1``）。
       所以整块解密之后，用 ``rfind`` 取**最后一个**匹配。
    3. 日志可能很大（实测 7 MB+），但整块解密是**一次线性扫描**，
       在这个量级上很快（毫秒级），不必分块。
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GrabError(f"读不了游戏日志：{exc}") from exc

    text = decrypt_log_line(raw).decode("utf-8", errors="replace")
    # rfind 取最后一个 —— 最新的链接在文件末尾
    return extract_url(text)


# --------------------------------------------------------------------- 找目录


def _config_path() -> pathlib.Path:
    from . import paths  # noqa: PLC0415 - 避免和 paths 的初始化顺序打架

    return paths.user_data_dir() / _CONFIG_NAME


def remembered_dir() -> pathlib.Path | None:
    """上次找到的游戏目录（存在且日志还在才算数）。"""
    try:
        raw = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(raw.get("game_dir") or "").strip()
    if not value:
        return None
    path = pathlib.Path(value)
    return path if (path / LOG_RELATIVE).exists() else None


def remember_dir(game_dir: pathlib.Path) -> None:
    """把找到的游戏目录记下来（下次不用再全盘扫）。"""
    try:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"game_dir": str(game_dir)}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - 记不住只是下次慢一点，不影响功能
        logger.warning("记不住游戏目录（%s）：%s", game_dir, exc)


def _common_candidates() -> list[pathlib.Path]:
    """常见安装位置先试一遍（比全盘扫快得多）。"""
    names = ("Wuthering Waves", "WutheringWaves", "鸣潮")
    roots: list[pathlib.Path] = []
    for drive in string.ascii_uppercase:
        base = pathlib.Path(f"{drive}:/")
        if not base.exists():
            continue
        for name in names:
            roots.append(base / name)
            roots.append(base / name / "Wuthering Waves Game")
    return roots


def _scan_drives() -> pathlib.Path | None:
    """全盘找 ``Client/Saved/Logs/Client.log``。

    ⚠ 很慢（几十秒），只在常见位置都没找到时才走这条路。
    用 ``where`` 命令找（Windows 自带，比 Python 递归快得多）。
    """
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["where", "/r", "C:\\", "Client.log"],
            capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001 - 找不到就当没有
        return None
    for line in (result.stdout or "").splitlines():
        path = pathlib.Path(line.strip())
        if "Saved" in str(path) and path.name == "Client.log":
            # 游戏目录 = Logs 往上 3 层（Logs → Saved → Client）
            return path.parents[2]
    return None


def find_log() -> pathlib.Path:
    """定位游戏日志。找不到抛 :class:`GrabError`（消息给用户看）。"""
    remembered = remembered_dir()
    if remembered is not None:
        return remembered / LOG_RELATIVE

    for root in _common_candidates():
        log = root / LOG_RELATIVE
        if log.exists():
            remember_dir(root)
            return log
        # 有些装在 <root>/Wuthering Waves Game/ 下
        log = root / "Wuthering Waves Game" / LOG_RELATIVE
        if log.exists():
            remember_dir(root / "Wuthering Waves Game")
            return log

    found = _scan_drives()
    if found is not None:
        remember_dir(found)
        return found / LOG_RELATIVE

    raise GrabError(
        "没找到游戏日志（Client.log）。\n"
        "可能是：游戏没装在本机 / 装在移动硬盘 / 从没在本机登录过。\n"
        "可以手动取链接：游戏里 唤取 → 唤取记录 → 打开页面多翻几页 → 复制链接，"
        "然后粘到输入框里。"
    )


def grab_link() -> str:
    """走完整流程：找日志 → 解密 → 取链接。失败抛 :class:`GrabError`。"""
    log = find_log()
    url = scan_log(log)
    if not url:
        raise GrabError(
            "日志里没有抽卡记录链接。\n"
            "请在游戏里打开一次：唤取 → 唤取记录（多翻几页），"
            "然后回到这里再点一次「获取抽卡记录」。"
        )
    return url
