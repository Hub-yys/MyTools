"""声骸批量调频（改主属性）—— ok-ww ``ChangeEchoTask`` 的 MyTools 版本。

## 这个工具做什么

游戏里的「**调频**」＝ 花材料**改声骸的主属性**（主音属性），走声骸详情页的
「数据重构」。ok-ww 的对应任务叫 ``ChangeEchoTask``。

⚠ 别和「声骸自动强化」混：
**强化**改的是**副词条**（强化并调谐），**调频**改的是**主属性**（数据重构）。

## 为什么这里**整段抄了** ok-ww 的 ``run()``

上一版「声骸自动强化」的原则是"流程整段用 ok-ww 的、只覆盖判定"。
**这个工具不行** —— 要改的三处全在 ``run()`` **函数体内部**，没有可以覆盖的钩子：

1. **"目标属性和当前属性相同" 是 ``raise``**：过滤器筛出的一批声骸里
   必然混着已经是目标属性的，一遇到就**整个任务中断**。要改成跳过/停止。
2. **``raise_if_not_found=True`` 有五处**（``声骸强化`` / ``主音属性`` /
   目标属性 / ``数据重构`` / ``获得声骸``）：UI 过渡期 OCR 抓空一个就炸整局。
3. **属性名比较用的是 ``in``（子串匹配）** —— ``"攻击" in "攻击百分比"`` 是 **True**，
   于是"目标 攻击、当前 攻击百分比"会被**误判成"已经相同"**并直接抛异常。
   必须改成精确比较。

所以这里把 ``run()`` 搬过来按 MyTools 的容错标准重写。
**上游改了 ``ChangeEchoTask.run()`` 就要重新 diff 一次**（见
``docs/声骸批量调频工具设计.md`` 的风险一节）。

## ⚠ 2026-10-03：属性名**改回裸名**（我 2026-09-26 改错过一次）

用户给了游戏「可选主音属性」面板的截图，上面写的是「**攻击**」「**生命**」
「**防御**」—— 就两个字，**没有「百分比」**。

我 2026-09-26 看到 ok-ww ``FiveToOneTask.main_stats`` 用的是
``攻击力百分比``，就**推断**游戏 UI 也这么写，把选项改成了「攻击百分比」。
**那个推断是错的** —— 实测：改完之后
**攻击 / 生命 / 防御 / 暴击 / 暴击伤害 五个全都识别不到**
（只有属性伤害加成和共鸣效率能用，因为那六个没被动过）。

现在选项表 = ok-ww 原版 = 游戏 UI 的真实文案。
检索仍走 :func:`target_pattern`（「力 / 值」可选），所以写成「攻击力」也能命中。

**教训：拿别人代码里的字符串当"游戏 UI 长什么样"的证据，是不成立的。**
ok-ww 的 ``FiveToOneTask`` 处理的是**另一个界面**（数据坞五合一），
它的 ``black_list = ["主属性攻击力", ...]`` 恰恰说明那边的主属性确实带「力」——
但**调频面板**上不带。两个界面文案不同。

## 和原版的其余差异

* ``supported_languages`` 清空（原版是 ``["zh_CN"]``）——
  ok-script 不满足门禁就**静默不注册**，宿主 locale 是 en_US，
  任务会"凭空消失"。这是「声骸自动强化」踩过的头号坑，别再踩第二次。
* 统计口径拆开：**成功 / 跳过 / 失败**三个数（原版只有成功）。
  「跳过 ≠ 失败」，混在一起用户会以为工具坏了。
"""

from __future__ import annotations

import os
import re
import sys
import time

# ---------------------------------------------------------------- vendor 挂载

def _ensure_vendor_on_path() -> None:
    """把 vendored ok-ww 挂到 ``sys.path``。

    本模块要在**任何**上下文里都能 import：ok 的 ``init_class_by_name``（boot 时，
    vendor 已在 path 上）、PyInstaller 的静态分析、以及单测。所以不假设调用方
    已经把 vendor 加进过 path。
    """
    from ....core import paths  # noqa: PLC0415 - 避免模块级循环导入

    vendor = str(paths.resource_dir("vendor", "okww"))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


_ensure_vendor_on_path()

from okww.task.ChangeEchoTask import ChangeEchoTask  # noqa: E402


#: 可选的目标主属性 —— **和游戏 UI 上的文案一字不差**。
#:
#: ## ⚠ 2026-10-03 改回来了（我 2026-09-26 那次改错了）
#:
#: 用户给了游戏「可选主音属性」面板的截图，上面写的是::
#:
#:     冷凝伤害加成 / 热熔伤害加成 / 导电伤害加成
#:     气动伤害加成 / 衍射伤害加成 / 湮灭伤害加成
#:     **攻击 / 生命 / 防御**          ← 就这两个字，**没有「百分比」**
#:     共鸣效率
#:
#: 而我 2026-09-26 看到 ok-ww 的 ``FiveToOneTask.main_stats`` 用的是
#: ``攻击力百分比``，就**推断**游戏 UI 也这么写，把选项改成了「攻击百分比」。
#: **那个推断是错的** —— 实测复现：改完之后
#: **攻击 / 生命 / 防御 / 暴击 / 暴击伤害 五个全都识别不到**（只有属性伤害加成
#: 和共鸣效率能用，因为它们本来就没被改过）。
#:
#: 现在回归 ok-ww 原版的写法（也就是游戏 UI 的真实文案）。
#:
#: ⚠ 检索仍走 :func:`target_pattern` —— 它把「力 / 值」做成**可选**，
#: 所以即使某个游戏版本写成「攻击力」，也照样能命中。
TARGET_STATS: tuple[str, ...] = (
    "攻击",
    "暴击伤害",
    "暴击",
    "生命",
    "防御",
    "共鸣效率",
    "冷凝伤害加成",
    "热熔伤害加成",
    "导电伤害加成",
    "气动伤害加成",
    "衍射伤害加成",
    "湮灭伤害加成",
)

#: 默认目标属性（最常改的那一个）。
#: ⚠ 必须和 :data:`TARGET_STATS` 里的写法**完全一致** ——
#: 工具页用 ``saved not in TARGET_STATS`` 做校验，不一致会被当成脏数据。
DEFAULT_TARGET = "攻击"

#: 构建配置用的设置键（与工具页 / ``tool_settings`` 对齐）
SETTINGS_KEY = "echo_change"

#: 连续失败多少个就整体停下（避免在一个处理不了的声骸上无限重试）
MAX_CONSECUTIVE_FAILURES = 3

#: 单步 OCR 的有限重试（次数, 每次超时秒数）
STEP_RETRIES = (3, 1.0)

#: ``esc()`` 回列表的总时限（比原版 5 秒宽一点：详情页深的时候 5 秒不够）
ESC_TIMEOUT = 10.0


# ---------------------------------------------------------------- 属性名比较

#: 主属性在游戏 UI 里可能带「力 / 值」（``攻击力百分比`` / ``生命值百分比``），
#: 而副词条形态不带（``攻击百分比``）。比较和检索时都要把这一层差异吃掉。
_ATTRIBUTE_WORDS = ("攻击", "生命", "防御")

#: 这些名词后面可能缀「力」或「值」
_VALUE_SUFFIX = re.compile(r"(攻击|生命|防御)[力值]")


def _normalize_stat(text: str) -> str:
    """把 OCR 读到的属性名归一化，便于**精确**比较。

    干掉：空白 / 换行 / 前缀的 ``+`` / ``主属性·主音属性`` 修饰 / 全角百分号 /
    **属性名里的「力·值」**（``攻击力百分比`` ≡ ``攻击百分比``）。
    """
    s = str(text or "")
    s = s.replace("\u3000", "").replace(" ", "").replace("\n", "")
    s = s.replace("％", "%")
    s = s.replace("主属性", "").replace("主音属性", "")
    s = s.lstrip("+＋")
    s = _VALUE_SUFFIX.sub(r"\1", s)          # 攻击力→攻击、生命值→生命
    return s.strip()


def target_pattern(target: str) -> re.Pattern:
    """把目标属性名编成匹配式，用来在**选项面板**里找它。

    两个要求，缺一不可：

    **① 吃得下「力 / 值」的写法差异。**
    选项表写的是裸名（``攻击``，= 游戏 UI 上的文案），但游戏别处
    （ok-ww ``FiveToOneTask.main_stats``）用的是带「力」的形态
    （``攻击力百分比``）。字面量匹配会**漏掉** ——
    ``re.search("攻击力", "攻击")`` 是 **None**。所以「力 / 值」做成可选。

    **② 必须整串匹配，不能是子串！**
    面板上同时有 ``暴击`` 和 ``暴击伤害``；用 ``re.search("暴击", ...)``
    会**先撞上暴击伤害那个框**，于是把主属性改成用户没要的那个。
    （这和 ok-ww 原版在"已相同"判断上犯的错是同一类，别在这里再犯一次。）
    所以两头加锚点，只允许前缀 ``主属性/主音属性``、空白和 ``+``。
    """
    core = re.escape(target)
    for word in _ATTRIBUTE_WORDS:
        if target.startswith(word):
            core = (re.escape(word) + r"[力值]?"
                    + re.escape(target[len(word):]))
            break
    return re.compile(
        r"^\s*(?:主属性|主音属性)?\s*\+?\s*" + core + r"\s*$")


def stat_matches(current_text: str, target: str) -> bool:
    """当前主属性是不是**就是**目标属性。

    ⚠ 原版用的是子串匹配（``target in current``），而
    ``"攻击" in "攻击百分比"`` 是 True —— 于是「目标 攻击 / 当前 攻击百分比」
    被误判成"已经相同"并抛异常，**明明该改的却直接中断**。
    这里改成归一化后的**精确相等**。

    ``攻击百分比`` 与 ``攻击`` 是游戏里两个不同的属性，绝不能互相命中。
    """
    return _normalize_stat(current_text) == _normalize_stat(target)


class _AlreadyTarget(Exception):
    """当前主属性已经是目标属性（内部信号）。

    单独一个类型是为了跟"真的出错了"区分开：前者算**跳过**，后者算**失败**，
    两者在报告里必须分开显示，否则用户看到"12 个里只成功 9 个"会以为工具坏了。

    ⚠ 定义在 :class:`MyToolsChangeEchoTask` **之前** —— ``run()`` 里的
    ``except _AlreadyTarget`` 在调用时才解析，放后面其实也能跑，
    但读代码的人要往下翻才知道它是什么。
    """


class MyToolsChangeEchoTask(ChangeEchoTask):
    """把「批量修改声骸主属性」按 MyTools 的容错标准重写。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.name = "🎛️ 声骸批量调频（鸣潮工具箱）"
        self.description = (
            "点 B 进背包 → 声骸 → 用过滤器筛出要改主属性的 → 按等级升序排序后开始。"
            "流程与 ok-ww 一致，但「已经是目标属性」的声骸会跳过而不是中断任务。"
        )

        # ★★ 语言门禁：**必须清空**，否则任务会被静默跳过、界面显示「找不到任务」。
        #   原版 ``ChangeEchoTask`` 声明了 supported_languages = ["zh_CN"]，
        #   而宿主无 GUI → app.locale 是 en_US → ok-script 的 init_tasks() 不注册它。
        #   宿主场景下"引擎语言"这个代理量毫无意义：本工具就是给中文游戏用的。
        self.supported_languages = []

        self.default_config["目标属性"] = DEFAULT_TARGET

        #: 本次运行的统计（原版只有"成功"，这里拆成三个）
        self.ok_echoes = 0
        self.skipped_echoes = 0
        self.failed_echoes = 0
        #: 失败原因分布：{原因短串: 次数}
        self.fail_tally: dict[str, int] = {}
        #: 连续失败计数（成功 / 跳过都会清零）
        self._consecutive_failures = 0
        #: 停止原因（给报告用）
        self.stop_reason = ""

    # ------------------------------------------------------------------ 工具
    @property
    def target_stat(self) -> str:
        return str(self.config.get("目标属性") or DEFAULT_TARGET)

    @property
    def max_count(self) -> int:
        """本次最多**成功调频**多少个；``0`` = 不限（用户 2026-09-27 要求）。

        ⚠ 口径和「声骸自动强化」的 ``max_count`` **一致：数成功数**。
          「跳过」不计入 —— 跳过的是本来就合乎条件的声骸，工具没动它。
          值非法（空串 / 非数字 / 负数）一律当"不限"，不要在这里炸。
        """
        try:
            return max(0, int(self.config.get("数量上限") or 0))
        except (TypeError, ValueError):
            return 0

    def _step(self, label, action, *args, **kwargs):
        """带有限重试地做一步；全失败就把 ``label`` 抛出去（外层会接住）。

        原版这些步骤都是 ``raise_if_not_found=True`` —— 一次 OCR 抓空就炸整局。
        这里重试几次，仍失败才抛；外层把它记成"这个声骸失败了"并继续。
        """
        times, timeout = STEP_RETRIES
        last = None
        for _ in range(times):
            try:
                got = action(*args, **kwargs)
                if got:
                    return got
            except Exception as exc:  # noqa: BLE001 - 单次失败不该中断重试
                last = exc
            self.sleep(timeout)
        raise RuntimeError(label if last is None else f"{label}（{last}）")

    def _has_more_echoes(self) -> bool:
        """列表里还有待处理的声骸吗。

        原版靠 ``is_0_level()``（找「声骸技能」）判断"是不是还停在详情/选中了东西"。
        """
        return bool(self.find_echo_enhance()) and bool(self.is_0_level())

    def _enter_detail(self) -> None:
        """连点「培养」直到它消失（＝已经进了详情页）。"""
        enhance = self.find_echo_enhance()
        start = time.time()
        while time.time() - start < 5:
            if enhance:
                self.click(enhance, after_sleep=0.5)
            enhance = self.find_echo_enhance()
            if not enhance:
                break

    def _read_current_main(self) -> str:
        """读当前主属性（详情页左上角那块）。"""
        box = self._step("找不到当前主属性", self.wait_ocr,
                         0.09, 0.20, 0.15, 0.26)
        if isinstance(box, list):
            box = box[0] if box else None
        if box is None:
            raise RuntimeError("找不到当前主属性")
        return str(getattr(box, "name", box))

    def _do_change(self) -> None:
        """把一个声骸的主属性改成目标属性（对应原版 run() 里那段点击序列）。"""
        target = self.target_stat

        self._step("找不到「声骸强化」", self.wait_ocr,
                   match="声骸强化", raise_if_not_found=True)
        self.sleep(0.5)

        current = self._read_current_main()
        if stat_matches(current, target):
            # 已经是对的了 —— 交给外层按"跳过"处理（原版在这里直接 raise）
            raise _AlreadyTarget(current)

        self.click(0.04, 0.41)                    # 切到「主音属性」页
        self._step("找不到「主音属性」", self.wait_ocr,
                   match="主音属性", raise_if_not_found=True)
        self.sleep(0.8)
        self.click(0.52, 0.71)                    # 打开属性选择
        # 用宽松匹配式找选项：游戏可能写「攻击力」而选项表是「攻击」
        box = self._step(f"选项里找不到「{target}」", self.wait_ocr,
                         match=target_pattern(target))
        self.sleep(0.1)
        self.click(box, after_sleep=0.5)          # 选目标属性
        self._step("确认按钮没出现", self.wait_click_ocr,
                   match="确认", after_sleep=2)
        self._step("找不到「数据重构」", self.wait_click_ocr,
                   0.37, 0.82, 0.64, 0.99, match="数据重构",
                   after_sleep=0.5, raise_if_not_found=True)
        self._step("没等到「获得声骸」", self.wait_ocr,
                   match="获得声骸", raise_if_not_found=True)

    # ------------------------------------------------------------------ 统计
    def _push_stats(self) -> None:
        self.info_set("成功声骸数量", self.ok_echoes)
        self.info_set("跳过声骸数量", self.skipped_echoes)
        self.info_set("失败声骸数量", self.failed_echoes)
        self.info_set("调频统计", self.tally_text())

    def tally_text(self) -> str:
        parts = [f"成功 {self.ok_echoes}", f"跳过 {self.skipped_echoes}",
                 f"失败 {self.failed_echoes}"]
        if self.fail_tally:
            reasons = "、".join(f"{k} {v}" for k, v in self.fail_tally.items())
            parts.append(f"（失败原因：{reasons}）")
        return " · ".join(parts)

    def _record_failure(self, exc: Exception) -> None:
        # 报错信息会被拼进失败截图的文件名，去掉文件名非法字符
        short = re.sub(r'[<>:"/\\|?*]', "", str(exc))[:40] or "未知"
        self.failed_echoes += 1
        self.fail_tally[short] = self.fail_tally.get(short, 0) + 1
        self.log_info(f"这个声骸处理失败，跳过：{exc}")
        self._push_stats()

    def _record_skip(self, current: str) -> None:
        self.skipped_echoes += 1
        self.log_info(f"当前主属性已经是「{current}」→ 跳过")
        self._push_stats()

    def _check_language(self) -> None:
        """开跑前把会让结果完全不对的环境问题喊出来。"""
        locale = getattr(self.executor, "locale", None)
        name = locale.name() if hasattr(locale, "name") else str(locale or "")
        if name and not name.startswith("zh"):
            self.log_info(
                "⚠ 引擎语言是 %s，本任务按**简体中文游戏界面**做 OCR 匹配"
                "（'培养' / '声骸强化' / '主音属性' / '数据重构' …）；"
                "游戏界面不是简中就会识别失败。" % name,
                notify=True,
            )

    # ------------------------------------------------------------------ 收尾
    def _finish(self) -> None:
        """任务结束时的统一收尾（正常跑完 / 提前停下都走这里）。"""
        total = self.ok_echoes + self.skipped_echoes + self.failed_echoes
        head = self.stop_reason or "列表已空，正常结束"
        self.log_info(
            f"调频结束：{head} | 共处理 {total} 个 —— 成功 {self.ok_echoes}、"
            f"跳过 {self.skipped_echoes}、失败 {self.failed_echoes}",
            notify=True,
        )
        if self.ok_echoes >= 1:
            try:
                os.startfile(os.path.abspath("screenshots"))
            except Exception as exc:  # noqa: BLE001 - 打不开截图目录不算失败
                self.log_error(f"无法打开截图文件夹: {exc}")

    def esc(self) -> None:
        """回列表页 —— 比原版宽一点，并且**确认真的回来了**。

        原版上限 5 秒 / 每次 sleep 1 秒，详情页深的时候可能不够；
        没回来就会在下一轮找不到「培养」而抛出致命异常。
        """
        start = time.time()
        while not self.find_echo_enhance() and time.time() - start < ESC_TIMEOUT:
            self.send_key("esc", after_sleep=1)
        self.sleep(0.1)
        if not self.find_echo_enhance():
            self.log_info("⚠ 按了 esc 但没回到声骸列表 —— 再补一次")
            self.send_key("esc", after_sleep=1)

    # ------------------------------------------------------------------ 主流程
    def run(self) -> None:
        """改写自 ok-ww ``ChangeEchoTask.run()``（改动点见模块文档）。"""
        self.ok_echoes = 0
        self.skipped_echoes = 0
        self.failed_echoes = 0
        self.fail_tally = {}
        self._consecutive_failures = 0
        self.stop_reason = ""
        self._push_stats()
        self._check_language()

        if not self.find_echo_enhance():
            raise Exception("必须在背包声骸界面过滤后开始!")

        while True:
            # ★ 数量上限（用户 2026-09-27）：数**成功**数，0 = 不限。
            if self.max_count and self.ok_echoes >= self.max_count:
                self.stop_reason = f"已达到设定的数量上限 {self.max_count} 个"
                self.log_info(f"✔ {self.stop_reason}")
                break

            if not self._has_more_echoes():
                break

            self._enter_detail()

            try:
                self._do_change()
            except _AlreadyTarget as exc:
                # 已经是目标属性：既不该算失败，也不能无限重试 —— 它还在过滤器里，
                # 下一轮还是它。停下并给可操作的说明（原版在这里直接抛异常）。
                self._record_skip(str(exc))
                self.esc()
                self.stop_reason = (
                    f"过滤器里出现了已经是「{self.target_stat}」的声骸 —— "
                    f"请把过滤器条件收紧（排除目标属性）后重跑")
                break
            except Exception as exc:  # noqa: BLE001 - 单个声骸失败不该中断整局
                self._record_failure(exc)
                self._consecutive_failures += 1
                self.esc()
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.stop_reason = (
                        f"连续 {self._consecutive_failures} 个声骸都处理失败，已停下 —— "
                        f"详情见日志")
                    self.log_info(f"⚠ {self.stop_reason}", notify=True)
                    break
                continue

            # 成功
            self._consecutive_failures = 0
            self.ok_echoes += 1
            self._push_stats()
            self.esc()

        self._finish()
