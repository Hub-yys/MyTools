"""主线程卡死看门狗：卡住时把**所有线程的调用栈**写到文件（诊断用）。

## 为什么需要它（2026-09-27）

用户报「应用卡死」时，我们能拿到的只有日志的**最后一行**：

    ... start_controller:enabled task <MyToolsEnhanceEchoTask ...>

然后就没有然后了。日志停在某一行**只能说明"卡在这之后"**，不能说明卡在
**哪个线程的哪一行** —— 而"之后"往往横跨好几层调用（引擎的
``_do_start`` → ``og.executor.start()`` → 内部的锁 / 线程创建）。

于是只能靠猜测：一会儿怀疑跨线程碰 Qt、一会儿怀疑锁被占着 —— 猜了七八轮
全是错的。**没有栈就是在瞎猜。**

这个看门狗的价值是：下次卡死，日志文件旁边会多出一份 ``stall-*.txt``，
里面是**卡死那一刻所有线程的栈**，一眼看到谁在等谁。

## 怎么判断"卡死"

主线程（GUI）每 200ms 调一次 :meth:`StallWatchdog.beat`。看门狗线程发现
超过 :data:`DEFAULT_TIMEOUT` 秒没收到打点，就认定主线程不转了。

⚠ 不能只看"有没有输出日志"：正常空闲时也不打日志。**必须是主线程主动打点**，
   这才是"事件循环还在转"的直接证据。

## 为什么不用 faulthandler 的信号（SIGBREAK）

GUI 程序里 Ctrl+Break 不一定送得进来，而且用户不会知道要按。自动转储更可靠。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)

#: 主线程打点的间隔（毫秒）。200ms 足够细 —— 卡死判定看的是"多久没打点"。
#: 定在这里而不是 main.py：测试要按它推算超时，两边写死容易飘。
HEARTBEAT_MS = 200

#: 主线程多久没打点就认为卡死（秒）。
#: 20 秒够长：正常的慢操作（OCR、截图、开任务）都在几秒内；超时了就是真卡住。
DEFAULT_TIMEOUT = 20.0

#: 判定卡死后的**重复转储间隔**（秒）。
#: 卡死可能持续很久，而栈会随时间变化（比如主线程后来被别的线程 join 住）——
#: 每 30 秒再补一份，成本低、信息更多。不做成一次性的。
REDUMP_INTERVAL = 30.0


class StallWatchdog:
    """监视主线程的"心跳"；超时没心跳就把所有线程的栈转储出去。"""

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT,
                 dump_dir: Path | None = None) -> None:
        self.timeout = timeout
        self.dump_dir = Path(dump_dir) if dump_dir is not None else None
        self._last_beat = time.monotonic()
        self._last_dump = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: 已经转储过几次（诊断/测试用）
        self.dumps = 0

    # ------------------------------------------------------------ 主线程接口
    def beat(self) -> None:
        """主线程定期调用（挂在 QTimer 上）——「事件循环还在转」的证据。"""
        self._last_beat = time.monotonic()

    def silence(self) -> float:
        """主线程已经安静了多少秒。"""
        return time.monotonic() - self._last_beat

    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="StallWatchdog",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # ⚠ 轮询间隔必须**跟 timeout 挂钩**，不能写死 1 秒。
        #   写死时：timeout=0.3 的测试要等满 1 秒才被检查一次 —— 而测试早就
        #   stop() 了，于是"该转储却没转储"根本测不出来（护栏空转，
        #   2026-09-27 反证时才发现）。
        poll = max(0.02, min(1.0, self.timeout / 4))
        while not self._stop.wait(poll):
            silent = self.silence()
            if silent < self.timeout:
                continue
            now = time.monotonic()
            if self._last_dump and now - self._last_dump < REDUMP_INTERVAL:
                continue
            self._last_dump = now
            self.dump(silent)

    # ------------------------------------------------------------ 转储
    def dump(self, silent: float) -> Path | None:
        """把所有线程的栈写进 ``stall-<时间>.txt``；返回文件路径。

        单独一个文件（不混进主日志）：转储是多行原文，和 ``logging`` 交错会很难读。
        """
        self.dumps += 1
        path = self._dump_path()
        logger.error(
            "★ 界面已经 %.0f 秒没有响应（很可能卡在某个锁/调用上）。"
            "所有线程的调用栈已写到：%s"
            "—— 看 **MainThread** 和 **TaskExecutor** 各自停在哪一行。",
            silent, path,
        )
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n===== 卡死转储 #%d：主线程已安静 %.1f 秒（%s）=====\n"
                         % (self.dumps, silent, time.strftime("%Y-%m-%d %H:%M:%S")))
                fh.write(format_all_threads())
        except OSError as exc:      # 磁盘满/权限 —— 退到 stderr，别把看门狗也弄死
            logger.error("写卡死转储失败：%s", exc)
            return None
        return path

    def _dump_path(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if self.dump_dir is None:
            return Path(f"stall-{stamp}.txt")
        self.dump_dir.mkdir(parents=True, exist_ok=True)
        return self.dump_dir / f"stall-{stamp}.txt"


def format_all_threads() -> str:
    """所有线程的 Python 调用栈，**带线程名**、主线程排最前。

    ## 为什么不用 ``faulthandler.dump_traceback``

    它的输出是 ``Thread 0x00042834 (most recent call first):`` —— **只有线程 id，
    没有名字**。卡死时最要紧的就是"哪个线程停在哪"，一堆十六进制 id 根本对不上
    是 TaskExecutor 还是 MainThread。所以这里自己遍历 :func:`sys._current_frames`
    并把 :func:`threading.enumerate` 的名字对上去。
    """
    frames = sys._current_frames()
    names = {t.ident: t.name for t in threading.enumerate()}

    def sort_key(item):
        ident = item[0]
        name = names.get(ident, "")
        # 主线程第一（那才是"界面卡住"的本体），其余按名字排，方便对照
        return (name != "MainThread", name)

    out: list[str] = []
    for ident, frame in sorted(frames.items(), key=sort_key):
        name = names.get(ident) or f"(未登记线程 {ident})"
        out.append(f"\n--- {name} ---\n")
        out.extend(traceback.format_stack(frame))
    return "".join(out)
