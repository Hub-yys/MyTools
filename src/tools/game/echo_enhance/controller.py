# ⚠ LEGACY（2026-09-23）：本模块属于 MyTools **自写**的声骸强化实现，已不是主路径。
# 强化流程现在整段走 ok-ww 引擎（echo_enhance/okww_task.py + auto_combat/okww_boot.py），
# 判定条件走 echo_enhance/stats.py。保留它只是因为还有测试覆盖它；
# **不要在新代码里引用**，也不要照着它改流程。
"""游戏窗口：定位、截屏、发送键鼠。

设计取舍（很重要，写在最前面）：

* **截屏用 mss**，不用 ``PrintWindow`` —— 后者对虚幻引擎的窗口经常抓到纯黑。
  ⚠ 2026-09-22 更正：这里原来写的是"mss = DXGI 桌面复制、不用 BitBlt"，**与实装版本不符**。
  实测本机 mss 10.2 的 Windows 后端**只有 GDI `BitBlt` 一个**：源是
  ``GetWindowDC(0)``（整个屏幕的 DC），目标是 mss 自己的 DIB，标志
  ``SRCCOPY|CAPTUREBLT``（``mss/windows/gdi.py``，整个包里没有 dxgi 字样）。
  它能用的原因是：拷的是**整屏 DC**、而不是单个窗口的 DC，且避开了 ``PrintWindow``。
  记住这条只关系到"能不能抓到画面" —— 无论走哪条路，读的都是**屏幕像素**，
  不是游戏进程的内存（本项目不读也不改游戏内存）。
* **输入用真实键鼠事件（win32api）而不是 PostMessage**：UE 游戏对后台消息
  常常不响应。代价是**运行期间鼠标和键盘会被占用**，所以运行中不要动电脑。
  （ok-ww 用的是后台方式，那需要 Windows.Graphics.Capture + 特制的后台点击，
   依赖更重，这里先不引入。）
* **本工具必须和游戏同级或更高权限**（实测：鸣潮带 ACE 反外挂，游戏跑在
  **High 完整性级别**，工具若以普通权限启动，UIPI 会拦掉全部输入 ——
  鼠标 API 报 ``(0, 'SetCursorPos', 'No error message is available')``，
  ``keybd_event`` 更是**静默丢弃**）。所以：打包版用 ``requireAdministrator``
  清单（见 ``packaging/mytools.spec`` 的 ``uac_admin``），运行前还会做一次
  :meth:`GameWindow.verify_input_allowed` 自检，别等到第一次点击才炸。
* **游戏需要窗口模式**（无边框窗口最稳）。独占全屏时抓到的画面不可靠。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

#: 游戏窗口标题关键字（官方启动器/游戏进程名不同版本略有差异）
WINDOW_KEYWORDS = ("鸣潮", "Wuthering Waves", "WutheringWaves", "Client-Win64-Shipping")

#: 常用按键 → Windows 虚拟键码
VK_CODES: dict[str, int] = {
    "esc": 0x1B,
    "enter": 0x0D,
    "space": 0x20,
    "tab": 0x09,
    "z": 0x5A,
    "c": 0x43,
    "b": 0x42,
    "f": 0x46,
    "m": 0x4D,
    "e": 0x45,
    "q": 0x51,
    "r": 0x52,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    "0": 0x30,
    "g": 0x47,
    "h": 0x48,
    "t": 0x54,
    "v": 0x56,
    "x": 0x58,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "lalt": 0xA4,
    "f1": 0x70,
    "f2": 0x71,
}

#: 鼠标按键 → （按下标志, 抬起标志）
MOUSE_FLAGS: dict[str, tuple[int, int]] = {
    "left": (0x0002, 0x0004),      # MOUSEEVENTF_LEFTDOWN / LEFTUP
    "right": (0x0008, 0x0010),     # RIGHTDOWN / RIGHTUP
    "middle": (0x0020, 0x0040),    # MIDDLEDOWN / MIDDLEUP
}


class WindowNotFound(RuntimeError):
    """没找到游戏窗口。"""


class InputBlocked(RuntimeError):
    """输入发不出去（权限不足 / 被反外挂拦下）。

    单独一个类型，是因为它和"找不到按钮"这类业务错误完全不同 ——
    前者改配置没用，只能提权；界面上要能把这句话原样展示给用户。

    ⚠ **只用于"权限/系统拒绝"**。代码自身的错误（参数写错、函数名打错）
    不许塞进这个类型 —— 见 :func:`_wrap_input_error`。
    """


#: 这几类是**代码写错了**（参数个数不对、属性名打错……），不是权限问题。
#: 包装成「权限不足」会把排查带偏。实测踩过（2026-09-27）：
#: `keybd_event` 多传了一个参数 → ``TypeError`` → 被翻译成
#: 「本工具已经是管理员权限，仍然被拦 —— 这多半是游戏反外挂（ACE）拦下了合成输入」。
#: 用户照着提示重新提权、去查反外挂，全白费 —— 真正该看的是那句
#: ``keybd_event() takes at most 4 arguments (5 given)``。
_PROGRAMMING_ERRORS = (TypeError, AttributeError, ValueError, KeyError,
                       IndexError, NameError)


def _wrap_input_error(action: str, exc: Exception) -> Exception:
    """把输入 API 的失败翻译成人话。

    pywin32 的报错格式是 ``(错误码, 函数名, 说明)``；错误码 0 = Windows 在输入层
    直接拒了（UIPI，且不给说明文字），这个提示对用户毫无意义，必须换掉。

    **但只有"像权限/系统拒绝"的才包装成** :class:`InputBlocked`；
    代码自身的错误（:data:`_PROGRAMMING_ERRORS`）**原样暴露**出来。
    """
    if isinstance(exc, _PROGRAMMING_ERRORS):
        return RuntimeError(
            f"{action} 失败 —— 这是**代码/环境问题，不是权限问题**：{exc}"
        )

    from ....core import elevation

    return InputBlocked(
        f"{elevation.admin_hint()}\n"
        f"（原始报错：{action} 失败 — {exc}）"
    )


@dataclass
class ClientRect:
    left: int
    top: int
    width: int
    height: int


class GameWindow:
    """找到游戏窗口后，用它来抓图和发输入。"""

    def __init__(self, keywords: tuple[str, ...] = WINDOW_KEYWORDS):
        self.keywords = keywords
        self.hwnd: int | None = None
        self.rect: ClientRect | None = None
        self._sct = None

    # ---------------------------------------------------------------- 定位
    def find(self) -> int | None:
        """找游戏窗口，返回窗口句柄；找不到返回 None。"""
        import win32gui

        found: list[int] = []

        def callback(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            if any(k.lower() in title.lower() for k in self.keywords):
                found.append(hwnd)

        win32gui.EnumWindows(callback, None)
        if not found:
            self.hwnd = None
            return None

        # 多个候选时取面积最大的那个（一般是主窗口）
        self.hwnd = max(found, key=lambda h: self._client_size(h)[0] * self._client_size(h)[1])
        self.refresh_rect()
        return self.hwnd

    @staticmethod
    def _client_size(hwnd: int) -> tuple[int, int]:
        import win32gui

        try:
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            return right - left, bottom - top
        except Exception:  # noqa: BLE001
            return 0, 0

    def refresh_rect(self) -> ClientRect:
        """把客户区左上角换算成屏幕绝对坐标。"""
        import win32gui

        if self.hwnd is None:
            raise WindowNotFound("还没找到游戏窗口")

        _, _, right, bottom = win32gui.GetClientRect(self.hwnd)
        # ClientToScreen 需要 POINT 结构，这里用左上角 (0,0) 求客户区原点
        origin_x, origin_y = win32gui.ClientToScreen(self.hwnd, (0, 0))
        self.rect = ClientRect(origin_x, origin_y, right, bottom)
        return self.rect

    def bring_to_front(self) -> bool:
        """把游戏窗口置前 —— 前台输入模式下必须先做这一步。

        返回**是否真的置前了**。以前这里静默吞掉失败，后果很隐蔽：
        ``SetForegroundWindow`` 在两种情况下会失败 —— 一是 Windows 的前台锁
        （不是当前前台进程就没资格抢），二是 **UIPI**（低权限进程抢不动高权限窗口）。
        失败时后面的截图会拍到"当前前台那个窗口"（实测踩过：探测产物里拍到的是
        MyTools 自己），点击也会落到别的窗口上 —— 但日志里什么都不说，很难查。
        """
        import win32con
        import win32gui

        if self.hwnd is None:
            raise WindowNotFound("还没找到游戏窗口")
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:  # noqa: BLE001 - 置前失败不抛，由返回值告诉调用方
            pass
        time.sleep(0.3)

        import ctypes

        try:
            return ctypes.windll.user32.GetForegroundWindow() == self.hwnd
        except Exception:  # noqa: BLE001 - 查不到就当没成功（宁可多提示一句）
            return False

    # ---------------------------------------------------------------- 抓图
    def grab(self) -> np.ndarray:
        """截取游戏客户区，返回 BGR ndarray（cv2 的顺序）。"""
        import mss

        if self.hwnd is None:
            raise WindowNotFound("还没找到游戏窗口")
        if self.rect is None:
            self.refresh_rect()
        assert self.rect is not None

        if self._sct is None:
            self._sct = mss.mss()

        monitor = {
            "left": self.rect.left,
            "top": self.rect.top,
            "width": self.rect.width,
            "height": self.rect.height,
        }
        raw = np.array(self._sct.grab(monitor))
        # mss 给的是 BGRA，丢掉 alpha 通道即为 BGR
        return raw[:, :, :3].copy()

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            finally:
                self._sct = None

    # ---------------------------------------------------------------- 输入
    def abs_point(self, relative_x: float, relative_y: float) -> tuple[int, int]:
        """相对坐标（0~1）→ 屏幕绝对坐标。"""
        if self.rect is None:
            self.refresh_rect()
        assert self.rect is not None
        return (
            self.rect.left + int(relative_x * self.rect.width),
            self.rect.top + int(relative_y * self.rect.height),
        )

    def click(self, relative_x: float, relative_y: float, after_sleep: float = 0.3) -> None:
        """点击窗口内的相对坐标。"""
        import win32api
        import win32con
        import win32gui

        x, y = self.abs_point(relative_x, relative_y)
        try:
            win32api.SetCursorPos((x, y))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception as exc:  # noqa: BLE001 - 统一转成"权限不足"这类可读信息
            raise _wrap_input_error("点击", exc) from exc
        if after_sleep:
            time.sleep(after_sleep)

    def move_cursor(self, relative_x: float, relative_y: float) -> None:
        """把光标移到窗口内的相对坐标（只移动，不点击）。

        给"滚轮"用 —— 滚轮只作用于**光标底下**的控件。
        """
        import win32api

        x, y = self.abs_point(relative_x, relative_y)
        try:
            win32api.SetCursorPos((x, y))
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error("移动光标", exc) from exc

    def scroll(self, clicks: int) -> None:
        """在**光标当前位置**滚轮。正数向上、负数向下。

        ★ 2026-09-27 加：给"列表比一屏长"的控件用（合鸣一共 34 套，
        那个下拉列表只看得到 7 项左右）。滚轮只作用于**光标底下**的控件，
        所以调用方要先把光标挪到列表上（见 ``prepare.EchoPrep._scroll_list``）。
        """
        import win32api
        import win32con

        try:
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0,
                                 int(clicks) * win32con.WHEEL_DELTA, 0)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error("滚轮", exc) from exc

    # ---------------------------------------------------------------- 鼠标
    #
    # 自动战斗必须用下面这几个"**不移动光标**"的方法：动作游戏里移动光标可能带动
    # 镜头/瞄准，而普攻只需要"在当前指向处点左键"。``click()`` 保留给"点界面按钮"
    # 用（那才需要先把光标移过去）。

    def mouse_down(self, button: str = "left") -> None:
        """在光标当前位置按下某个鼠标键（不移动光标）。"""
        import win32api

        flags = MOUSE_FLAGS.get(button)
        if flags is None:
            raise ValueError(f"不认识的鼠标键: {button}")
        try:
            win32api.mouse_event(flags[0], 0, 0, 0, 0)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error(f"鼠标 {button} 按下", exc) from exc

    def mouse_up(self, button: str = "left") -> None:
        """在光标当前位置抬起某个鼠标键。"""
        import win32api

        flags = MOUSE_FLAGS.get(button)
        if flags is None:
            raise ValueError(f"不认识的鼠标键: {button}")
        try:
            win32api.mouse_event(flags[1], 0, 0, 0, 0)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error(f"鼠标 {button} 抬起", exc) from exc

    def click_here(self, button: str = "left", hold: float = 0.01,
                   after_sleep: float = 0.0) -> None:
        """在**光标当前位置**点一下（不移动光标）。战斗里的普攻就是这个。"""
        self.mouse_down(button)
        if hold > 0:
            time.sleep(hold)
        self.mouse_up(button)
        if after_sleep:
            time.sleep(after_sleep)

    def move_to_client_center(self) -> tuple[int, int]:
        """把光标移到游戏客户区正中，返回屏幕坐标。

        战斗开始前做一次：让"在当前指向处点击"落在游戏画面里，而不是别的窗口上。
        （ok-ww 也带这个动作 —— 它有个专门的鼠标复位任务。）
        """
        import win32api

        if self.rect is None:
            self.refresh_rect()
        assert self.rect is not None
        point = (self.rect.left + self.rect.width // 2,
                 self.rect.top + self.rect.height // 2)
        try:
            win32api.SetCursorPos(point)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error("移动光标", exc) from exc
        return point

    def press(self, key: str, after_sleep: float = 0.3) -> None:
        """按一下某个键（名字见 :data:`VK_CODES`）。"""
        import win32api
        import win32con

        vk = VK_CODES.get(key.lower())
        if vk is None:
            raise ValueError(f"不认识的按键: {key}")

        try:
            # ⚠ keybd_event 是**4** 个参数 (bVk, bScan, dwFlags, dwExtraInfo)，
            #   别照 mouse_event 的 5 个抄 —— 多传一个会 TypeError。
            win32api.keybd_event(vk, 0, 0, 0)
            time.sleep(0.03)
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error(f"按键 {key.upper()}", exc) from exc
        if after_sleep:
            time.sleep(after_sleep)

    # ---------------------------------------------------------------- 权限
    @staticmethod
    def _pid_of_window(hwnd: int) -> int:
        """取窗口所属进程 pid。

        用 ctypes 直调 user32，不走 ``win32process`` —— 本机 pywin32 312 里
        ``win32process.QueryFullProcessImageName`` 根本不存在（见 ``core/game_client.py``
        的注释），这类"函数有没有"的差异不值得赌。
        """
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value)

    def process_id(self) -> int | None:
        """游戏进程 pid；没窗口返回 None。"""
        if self.hwnd is None:
            return None
        try:
            return self._pid_of_window(self.hwnd)
        except Exception:  # noqa: BLE001 - 取不到就当查不到，别影响主流程
            return None

    def verify_input_allowed(self) -> None:
        """跑之前先确认"输入发得出去"。不通过抛 :class:`InputBlocked`。

        两道判据，任一不过就停：

        1. **比完整性级别**（无副作用、最准）：自身比游戏低 → UIPI 必然拦，
           不用试也知道结果；
        2. **真实探针**：把光标移到"它现在所在的位置"（等于没动，无副作用），
           失败即说明输入被拦 —— 这一条能兜住"级别相同但被反外挂拦下"的情况。

        为什么要提前做：不做的话用户看到的是"开始运行 → 第 1 次强化 → 出错"，
        像功能坏了，其实一步都没走成。
        """
        from ....core import elevation

        own = elevation.own_integrity_level()
        target = elevation.integrity_level(self.process_id() or 0)
        if own is not None and target is not None and own < target:
            raise InputBlocked(elevation.admin_hint(own, target))

        import win32api

        try:
            current = win32api.GetCursorPos()
            ok = win32api.SetCursorPos(current)
        except Exception as exc:  # noqa: BLE001
            raise _wrap_input_error("输入自检", exc) from exc
        if not ok:
            raise InputBlocked(elevation.admin_hint(own, target))

    # ---------------------------------------------------------------- 状态
    def describe(self) -> str:
        if self.hwnd is None:
            return "未找到游戏窗口"
        title = ""
        try:
            import win32gui

            title = win32gui.GetWindowText(self.hwnd)
        except Exception:  # noqa: BLE001
            pass
        rect = self.rect
        size = f"{rect.width}x{rect.height}" if rect else "尺寸未知"
        return f"{title} (hwnd={self.hwnd}, {size})"
