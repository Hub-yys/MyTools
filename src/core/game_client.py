"""游戏客户端是否在运行 —— 任务流程「开始」步的前置检查。

判据两条，**任一命中**就算客户端已经启动：

1. **窗口标题**含关键字（``鸣潮`` / ``Wuthering Waves`` / …）—— 和强化工具
   找窗口用的是同一套关键字，所以这条通过就意味着后面能抓到画面；
2. **进程名**匹配（``Client-Win64-Shipping.exe``）—— 游戏刚启动、窗口还没建出来，
   或者窗口标题被改过时，靠这条兜住。

**纯逻辑**：只用 pywin32（枚举进程/窗口）和 ctypes（取进程名），
不依赖 Qt / mss / OCR。:func:`window_hit` / :func:`process_hit` 是纯函数，
可以随便单测；:func:`check` 要读真实环境，测试里靠"用一个绝不存在的关键字"
验否定分支、拿当前 python 进程验肯定分支。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: 鸣潮客户端：窗口标题关键字。**和 ``echo_enhance/controller.py`` 的
#: ``WINDOW_KEYWORDS`` 保持同一套** —— 这里判"客户端在跑"，那边判"能不能抓图"，
#: 判据不一致会出现"检查通过但抓不到窗口"的错位。
WUWA_WINDOW_KEYWORDS: tuple[str, ...] = (
    "鸣潮",
    "Wuthering Waves",
    "WutheringWaves",
    "Client-Win64-Shipping",
)

#: 鸣潮客户端进程名（只比文件名，不比全路径；大小写不敏感）
WUWA_PROCESS_NAMES: tuple[str, ...] = ("Client-Win64-Shipping.exe",)

#: 打开进程只用"查询受限信息"权限 —— 权限要得越小，能打开的进程越多
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class ClientSpec:
    """一个游戏客户端的判据。"""

    display_name: str
    window_keywords: tuple[str, ...] = ()
    process_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClientStatus:
    """一次检查的结果。"""

    running: bool
    display_name: str = ""
    matched_by: str = ""      # "窗口" / "进程" / ""（没命中）
    detail: str = ""          # 命中的标题 / 进程名，或失败说明

    def describe(self) -> str:
        if not self.running:
            return f"{self.display_name}客户端没在运行"
        return f"{self.display_name}客户端已启动（{self.matched_by}：{self.detail}）"


#: 鸣潮
WUWA = ClientSpec(
    display_name="鸣潮",
    window_keywords=WUWA_WINDOW_KEYWORDS,
    process_names=WUWA_PROCESS_NAMES,
)


# --------------------------------------------------------------------- 匹配
def window_hit(title: str, keywords: tuple[str, ...]) -> bool:
    """窗口标题是否含任一关键字（大小写不敏感）。"""
    text = (title or "").lower()
    if not text:
        return False
    return any(k.lower() in text for k in keywords if k)


def process_hit(image_name: str, process_names: tuple[str, ...]) -> bool:
    """进程名是否命中（允许传全路径，只比文件名；大小写不敏感）。"""
    name = os.path.basename((image_name or "").strip()).lower()
    if not name:
        return False
    return any(name == p.lower() for p in process_names if p)


# --------------------------------------------------------------------- 枚举
def list_window_titles() -> list[str]:
    """当前所有**可见且有标题**的窗口标题。取不到（非 Windows / 没装 pywin32）返回空列表。"""
    try:
        import win32gui
    except Exception:  # noqa: BLE001 - 环境不全时退化成"查不到"，由调用方报"未启动"
        return []

    titles: list[str] = []

    def callback(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd)
                if text:
                    titles.append(text)
        except Exception:  # noqa: BLE001 - 单个窗口取不到不该影响整体
            pass

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:  # noqa: BLE001
        return []
    return titles


def list_process_names() -> list[str]:
    """当前所有进程的**文件名**（不含路径）。取不到返回空列表。

    ⚠ 用 ctypes 直调 kernel32，**不能用** ``win32process.QueryFullProcessImageName``
    —— 实测本机 pywin32 312 **没有这个函数**（``GetModuleFileNameEx`` 又要更高权限），
    用它会导致一个进程都查不到，而"查不到"在这里等于"游戏没启动"= **误报任务失败**。
    """
    try:
        import ctypes
        from ctypes import wintypes

        import win32process

        pids = win32process.EnumProcesses()
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception:  # noqa: BLE001 - 非 Windows / 环境不全时退化成"查不到"
        return []

    names: list[str] = []
    for pid in pids:
        # 权限只要"查询受限信息"：要得越少，能打开的进程越多
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue                     # 系统 / 受保护进程打不开是常态，跳过
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                names.append(os.path.basename(buffer.value))
        finally:
            k32.CloseHandle(handle)
    return names


# --------------------------------------------------------------------- 检查
def check(spec: ClientSpec | None) -> ClientStatus:
    """检查客户端是否在运行：窗口标题、进程名**任一命中**即可。"""
    if spec is None:
        return ClientStatus(running=False, detail="没指定要检查哪个游戏")

    for title in list_window_titles():
        if window_hit(title, spec.window_keywords):
            return ClientStatus(True, spec.display_name, "窗口", title)

    for name in list_process_names():
        if process_hit(name, spec.process_names):
            return ClientStatus(True, spec.display_name, "进程", name)

    windows = "/".join(spec.window_keywords) or "—"
    processes = "/".join(spec.process_names) or "—"
    return ClientStatus(
        False,
        spec.display_name,
        "",
        f"没找到标题含「{windows}」的窗口，也没找到进程 {processes}",
    )
