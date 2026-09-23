"""进程权限：自身是否提权、目标进程的完整性级别、一键提权重启。

## 为什么需要这个模块

鸣潮带 **ACE 反外挂**（内核驱动 ``ACE-BASE.sys`` 等），它会要求游戏进程运行在
**受保护的提权环境**里 —— 也就是 **High 完整性级别（管理员）**。
而 Windows 的 **UIPI**（用户界面特权隔离）禁止低完整性进程向高完整性窗口注入输入：

* 鼠标类 API（``SetCursorPos`` / ``mouse_event``）**直接失败**，而且报错很坑：
  ``(0, 'SetCursorPos', 'No error message is available')`` —— 错误码是 0，
  用户完全看不出发生了什么；
* ``keybd_event`` 更糟：**静默丢弃**，连报错都没有（所以按 Z 弃置 / 按 C 上锁
  全都"看起来执行了"其实什么都没发生）。

结论：**游戏在管理员权限下运行时，本工具也必须是管理员**，否则一点都点不动。

## 判据

* 自身是否提权 → ``OpenProcessToken`` + ``GetTokenInformation(TokenElevation)``
* 目标进程级别 → ``GetTokenInformation(TokenIntegrityLevel)`` 取 SID 最后一节（RID）：
  低 ``0x1000`` / 中 ``0x2000``（普通程序）/ 高 ``0x3000``（管理员）/ 系统 ``0x4000``
* 自身级别 → 同上（拿自己进程的令牌）

**纯逻辑**：不依赖 Qt / mss / OCR，可以单测（见 ``tests/test_elevation.py``）。
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)


def _dlls():
    """拿 kernel32 / advapi32，并**把参数类型都钉死**。

    ⚠ 不设 ``argtypes`` 时 ctypes 按 C ``int`` 传参，而进程句柄（伪句柄 -1）会直接
    报 ``OverflowError: int too long to convert`` —— 报错还落在"参数 1"上，看着像
    业务代码传错了，其实只是原型没声明。
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)

    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE

    adv.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    adv.GetTokenInformation.restype = wintypes.BOOL
    return k32, adv

#: 完整性级别的常见档位（SID 最后一节）
LEVEL_LOW = 0x1000        # 低（受保护的浏览器进程之类）
LEVEL_MEDIUM = 0x2000     # 中 —— 普通双击启动的程序
LEVEL_HIGH = 0x3000       # 高 —— "以管理员身份运行"
LEVEL_SYSTEM = 0x4000     # 系统

_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20         # TOKEN_INFORMATION_CLASS
_TOKEN_INTEGRITY_LEVEL = 25   # TOKEN_INFORMATION_CLASS
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def is_windows() -> bool:
    """当前是不是 Windows（其它平台上所有检查都退化成"查不到"）。"""
    return os.name == "nt"


# --------------------------------------------------------------------- 查询

def is_elevated() -> bool:
    """当前进程是否以管理员（提权）身份运行。

    非 Windows / 取不到令牌时返回 False —— 宁可多提示一句，也别默默假设自己有权限。
    """
    if not is_windows():
        return False

    k32, adv = _dlls()
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(
        k32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        return False
    try:
        elevation = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not adv.GetTokenInformation(
            token, _TOKEN_ELEVATION, ctypes.byref(elevation),
            ctypes.sizeof(elevation), ctypes.byref(returned),
        ):
            return False
        return bool(elevation.value)
    finally:
        k32.CloseHandle(token)


def _integrity_from_handle(handle) -> int | None:
    """从一个进程句柄取它的完整性级别（RID）；取不到返回 None。"""

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", SID_AND_ATTRIBUTES)]

    k32, adv = _dlls()
    token = wintypes.HANDLE()
    if not adv.OpenProcessToken(handle, _TOKEN_QUERY, ctypes.byref(token)):
        return None

    try:
        size = wintypes.DWORD(0)
        # 第一次调用故意传空缓冲：只为问出需要多大（必定返回 False + INSUFFICIENT_BUFFER）
        adv.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(
            token, _TOKEN_INTEGRITY_LEVEL, buffer, size.value, ctypes.byref(size)
        ):
            return None

        label = ctypes.cast(buffer, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
        # ⚠ SID 这两个函数在 **advapi32** 里；kernel32 里同名函数不存在，
        #   拿错 DLL 会报 `AttributeError: function 'GetSidSubAuthorityCount' not found`
        #   （而且只在真正取完整性级别时才炸，光看代码看不出来）。
        adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

        count = adv.GetSidSubAuthorityCount(label.Label.Sid)
        if not count:
            return None
        last = adv.GetSidSubAuthority(label.Label.Sid, count[0] - 1)
        return int(last[0]) if last else None
    finally:
        k32.CloseHandle(token)


def integrity_level(pid: int) -> int | None:
    """某个进程的完整性级别；打不开（系统 / 受保护进程）返回 None。"""
    if not is_windows() or not pid:
        return None

    k32, _adv = _dlls()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        return _integrity_from_handle(handle)
    finally:
        k32.CloseHandle(handle)


def own_integrity_level() -> int | None:
    """自身进程的完整性级别。"""
    if not is_windows():
        return None

    k32, _adv = _dlls()
    handle = k32.GetCurrentProcess()
    try:
        return _integrity_from_handle(handle)
    except Exception:  # noqa: BLE001
        return None


def level_name(level: int | None) -> str:
    """把人看不懂的数字说成人话。"""
    if level is None:
        return "未知"
    if level >= LEVEL_SYSTEM:
        return "系统级"
    if level >= LEVEL_HIGH:
        return "管理员级"
    if level >= LEVEL_MEDIUM:
        return "普通级"
    return "低"


# --------------------------------------------------------------------- 提权

def _relaunch_target(argv: list[str] | None) -> tuple[str, str]:
    """算出"重新拉起自己"该用什么可执行文件 + 参数。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, "frozen", False):
        # 打包后：sys.executable 就是 MyTools.exe，参数直接跟上
        return sys.executable, subprocess.list2cmdline(args)
    # 开发态：python + main.py + 参数
    return sys.executable, subprocess.list2cmdline([sys.argv[0], *args])


def relaunch_as_admin(argv: list[str] | None = None) -> bool:
    """用 ``runas`` 重新拉起自己（会弹 UAC）。返回是否成功发起。

    用户点"否"时 ShellExecuteW 返回 ``ERROR_CANCELLED``（1223），这里统一当成 False。
    """
    if not is_windows():
        return False

    exe, params = _relaunch_target(argv)
    try:
        # SW_SHOWNORMAL = 1
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("提权重启失败：%s", exc)
        return False
    # 返回值 > 32 才算成功（<=32 是错误码）
    return int(result) > 32


# --------------------------------------------------------------------- 提示语

def admin_hint(own: int | None = None, target: int | None = None) -> str:
    """权限不足时给用户的**可操作**说明（别让他去看 ``(0, 'SetCursorPos')``）。"""
    own = own_integrity_level() if own is None else own
    lines = [
        "权限不足：游戏以管理员身份运行，本工具权限比它低，操作系统禁止向它发送鼠标/键盘。",
        f"（本工具 {level_name(own)}",
    ]
    if target is not None:
        lines[-1] += f"，游戏 {level_name(target)}"
    lines[-1] += "）"

    if not is_elevated():
        lines.append("请关掉本工具，右键 →「以管理员身份运行」，再点运行。")
    else:
        # 已经是管理员还被拦，说明是被 ACE 反外挂挡了输入，得换输入方式
        lines.append(
            "本工具已经是管理员权限，仍然被拦 —— 这多半是游戏反外挂（ACE）拦下了合成输入，"
            "此时自动化点击这条路走不通。"
        )
    return "\n".join(lines)
