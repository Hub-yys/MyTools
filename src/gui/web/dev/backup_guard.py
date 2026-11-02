# -*- coding: utf-8 -*-
"""★ 用户数据备份/恢复 —— **所有破坏性测试必须用**。

## 为什么有这个（2026-11-02 事故）

我的 ``web_shell_config_write.py`` 做「新建 → 验证 → 删掉」时，
底座是 ``EchoProfileStore`` 那个 **auto-load=False** 的坑：

    没 load → _items 是空的 → add(1条) → save() 整个覆盖文件
    → 用户原有 5 条配置**全没了**

我还在报告里写「测试垃圾已清」—— **那不是垃圾，是用户的真实配置**。
lead 从打包备份恢复了。

## 教训

1. 破坏性测试**必须先备份**，不管你觉得它多安全；
2. 「清理测试数据」这个动作本身就可能删掉真数据；
3. 根因（Store 不 load）要修，但**不能只靠修根因** —— 测试自己的
   隔离层是第二道防线，两道都要。
4. ★★★ **备份清单必须覆盖全部数据文件，不是"这次用到的几个"**
   （2026-11-02 事故二：``gacha_history.json`` 不在清单里 →
   测试清空了用户 549 KB 抽卡历史 → 备份里没有 → 只能从打包备份找回）。
   现在改成扫 ``data/*.json`` 全部，清单只做兜底。

## ★★ 测试对用户数据的处置规则（写新测试前先看这张表）

============================  ==========================================
操作类型                        该怎么测
============================  ==========================================
只读                            冒烟直接调用
写（幂等 / 只动自己建的数据）      冒烟调用 + 本模块 ``UserDataGuard``
写（**可能覆盖用户数据**）        加入 ``SMOKE_SKIP`` + 专项测试 + 本模块
打网络 / 拉引擎                  加入 ``SMOKE_SKIP``
============================  ==========================================

本项目对应：

* **只读** —— ``getTools`` / ``getOkwwState`` / ``getNestSweepData`` /
  ``getCharacterBuildCache``
* **写但幂等** —— ``setSkin``（切到当前那款）/ ``setWallpaper``
* **写且覆盖用户数据** —— ``setNestSweepSelection``（覆盖 10 个真实勾选）/
  ``setConfig`` / ``deleteConfig`` / ``saveFlow``
* **打网络 / 拉引擎** —— ``checkLibraryUpdate`` / ``runOkwwTask``

三条硬规矩：

1. 冒烟测试只验「能调通 + 返回值是合法 JSON」，**不承担功能验证**
   （功能验证要准备数据、会碰用户数据）；
2. 任何写用户数据的测试，必须本模块包住、``finally`` 恢复，
   并比对 ``snapshot()`` 前后条目数（不一致直接 FAIL）；
3. 跳过的项要**明确列出来**，不能静默跳过 —— 否则
   「33 个方法全部无异常」会让人误以为 35 个都测了。

## 用法

.. code:: python

    from backup_guard import UserDataGuard

    guard = UserDataGuard()
    guard.start()               # 进入时备份
    before = guard.snapshot()   # 条目数快照
    try:
        ... 随意增删改 ...
    finally:
        guard.restore()         # 退出时（哪怕异常）恢复
        #: 比对 before / guard.snapshot() 是否一致

也可以 ``with user_data_backup(): ...``（自动恢复，但拿不到 snapshot）。
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: 会被 Web 桥接层写入的用户数据文件（相对 ``paths.user_data_dir()``）
#:
#: ★★★ 2026-11-02 事故二：这份清单**不全**，导致我又清了一次用户数据。
#:
#: ``web_shell_gacha_clear.py`` 清空了 ``gacha_history.json``（549 KB、
#: 用户的全部抽卡记录），而清单里**没有这个文件** —— ``UserDataGuard``
#: 压根没备份它，``restore()`` 自然恢复不了。最后从
#: ``build/stage/.../_internal/data/`` 的打包备份找回。
#:
#: **教训：清单必须覆盖 ``data/`` 下所有会被写的 JSON，
#: 而不是"我这次测试用到的几个"。**
#:
#: 现在改成「备份 ``data/`` 下**全部** ``*.json``」（见
#: :func:`_collect_targets`）+ 这份显式清单做兜底 ——
#: 以后新增数据文件**不用改这里**也不会漏。
GUARDED_FILES: tuple[str, ...] = (
    "echo_profiles.json",      #: 角色声骸强化配置（EchoProfileStore）
    "loadouts.json",           #: 声骸配置（LoadoutStore）
    "tasks.json",              #: 任务流程（TaskStore）
    "tool_settings.json",      #: 工具设置
    "ui_state.json",           #: 界面状态
    #: ★ 2026-11-02 补的 —— 之前漏了，出过事故
    "gacha_history.json",      #: 抽卡历史（GachaHistoryStore，549 KB）
    "kuro_练度.json",           #: 角色练度缓存（1.2 MB）
    "run_report.json",         #: 本轮报告累计
    "notifications.json",      #: 消息通知
    "battle_profile.json",     #: 战斗配置
)


def _collect_targets(root: Path) -> list[str]:
    """**实际要备份的文件名** = ``data/*.json`` 全部 ∪ ``GUARDED_FILES``。

    ## 为什么要扫目录而不只信清单

    清单是人维护的，**新加一个数据文件时很容易忘了往里加** ——
    2026-11-02 的 ``gacha_history.json`` 就是这么漏掉的，
    结果测试把用户 549 KB 的抽卡记录清空了、备份里却没有。

    扫目录是「**默认安全**」：新增文件自动被保护，忘记维护清单也不出事。

    ⚠ 只扫 ``data/`` **顶层**的 ``*.json`` —— 子目录（``wallpaper_webm/``
    那种几百 MB 的缓存）不该拷。
    """
    names: set[str] = set(GUARDED_FILES)
    try:
        for item in root.glob("*.json"):
            if item.is_file():
                names.add(item.name)
    except OSError:
        logger.warning("扫描用户数据目录失败：%s", root, exc_info=True)
    return sorted(names)


class UserDataGuard:
    """把用户数据文件备份到临时目录，退出时原样恢复。"""

    def __init__(self, files: tuple[str, ...] = GUARDED_FILES):
        self._files = files
        self._backup_dir: Path | None = None
        #: [(原路径, 备份路径)] —— 只记录**原来就存在**的
        self._pairs: list[tuple[Path, Path]] = []
        #: 原来**不存在**的文件 —— 恢复时要删掉（测试新建的）
        self._absent: list[Path] = []
        self._active = False

    # ---------------------------------------------------------------- 备份
    def start(self) -> "UserDataGuard":
        """备份所有存在的数据文件。

        ★ 2026-11-02：备份范围改成 ``data/*.json`` **全部** ∪ ``GUARDED_FILES``
        （见 :func:`_collect_targets`）—— 清单漏项不会再造成数据丢失。
        """
        from src.core import paths

        root = paths.user_data_dir()
        self._backup_dir = Path(tempfile.mkdtemp(prefix="mytools_bak_"))
        #: ★ 扫目录 + 清单，取并集（清单只是兜底，目录扫描才是主力）
        targets = _collect_targets(root)
        self._files = tuple(targets)
        for name in targets:
            src = root / name
            if not src.is_file():
                self._absent.append(src)
                continue
            dst = self._backup_dir / name
            try:
                shutil.copy2(src, dst)
                self._pairs.append((src, dst))
            except OSError:
                logger.warning("备份失败：%s", src, exc_info=True)
        self._active = True
        logger.info("用户数据已备份 %d 个文件 → %s",
                    len(self._pairs), self._backup_dir)
        return self

    # ---------------------------------------------------------------- 恢复
    def restore(self) -> bool:
        """把备份写回去；测试期间**新建**的文件删掉。

        :return: 全部成功返回 True
        """
        if not self._active:
            return False
        ok = True
        for src, dst in self._pairs:
            try:
                shutil.copy2(dst, src)
            except OSError:
                logger.error("恢复失败：%s ← %s", src, dst, exc_info=True)
                ok = False
        for src in self._absent:
            #: 测试前不存在 → 测试期间被建出来了 → 删掉，恢复原状
            try:
                if src.is_file():
                    src.unlink()
            except OSError:
                logger.warning("清理测试新建文件失败：%s", src, exc_info=True)
        self._active = False
        #: 临时目录清掉
        if self._backup_dir is not None:
            try:
                shutil.rmtree(self._backup_dir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
        logger.info("用户数据已恢复（%d 个文件）", len(self._pairs))
        return ok

    # ---------------------------------------------------------------- 校验
    def snapshot(self) -> dict[str, int]:
        """当前各文件的条目数（用于测试前后对比）。"""
        from src.core import paths

        root = paths.user_data_dir()
        out: dict[str, int] = {}
        for name in self._files:
            src = root / name
            if not src.is_file():
                out[name] = -1
                continue
            try:
                raw = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                out[name] = -2
                continue
            #: 尽量数出"条目数"：dict 里有 list 就数那个 list，
            #: 否则数顶层 key
            if isinstance(raw, dict):
                lists = [v for v in raw.values() if isinstance(v, list)]
                out[name] = len(lists[0]) if lists else len(raw)
            elif isinstance(raw, list):
                out[name] = len(raw)
            else:
                out[name] = 0
        return out


@contextlib.contextmanager
def user_data_backup(files: tuple[str, ...] = GUARDED_FILES):
    """``with`` 用法：进入备份、退出恢复（异常也恢复）。"""
    guard = UserDataGuard(files)
    guard.start()
    try:
        yield guard
    finally:
        guard.restore()


__all__ = ["GUARDED_FILES", "UserDataGuard", "user_data_backup"]
