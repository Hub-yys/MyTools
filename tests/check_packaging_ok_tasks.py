# -*- coding: utf-8 -*-
"""★ 模拟打包产物：把 ok_tasks 放进一个临时目录，验证 FeatureSet 真的能合并它。

这才是「修好了没有」的**决定性验证** —— 不是在源码树里查文件在不在，
而是让 **ok-script 自己**去 merge 一遍，看 char_xin 有没有进特征表。
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(r"D:\AI Work\workbuddy\MyTools")
sys.path.insert(0, str(ROOT / "vendor" / "okww"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

VENDOR = ROOT / "vendor" / "okww"
coco = VENDOR / "assets" / "coco_annotations.json"
ok_tasks_coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"

print("源文件:")
print("  assets/coco_annotations.json      ", coco.is_file())
print("  ok_tasks/assets/coco_annotations.json", ok_tasks_coco.is_file())
print()

#: ── 造一个"模拟打包目录"：把 vendor 拷过去，ok_tasks 按 spec 的规则收
tmp = pathlib.Path(tempfile.mkdtemp(prefix="pkg-sim-"))
stage = tmp / "_internal" / "vendor" / "okww"
stage.mkdir(parents=True)
for name in ("assets", "i18n", "config.py"):
    src = VENDOR / name
    if src.is_dir():
        shutil.copytree(src, stage / name)
    elif src.is_file():
        shutil.copy2(src, stage / name)


def feature_dict_keys(include_ok_tasks: bool) -> tuple[set, str]:
    """在 ``stage`` 目录下让 ok-script 真读一遍 ``char_xin``。

    :return: ``(特征表键集合, 复现出来的异常文本)``

    ⚠ 特征表是**按需加载**的（``ensure_feature`` 只认一个名字），
    所以必须**点名** ``char_xin`` 去要 —— 直接建完 FeatureSet 就查
    ``feature_dict`` 是空的（我第一版就是这样，两边都 0 个，得不出结论）。

    ⚠⚠ 缺模板时**抛异常的不是** ``ensure_feature``：``read_from_json``
    找不到那个 category 会**安静地返回空表**，真正的 ``ValueError``
    是后面 ``find_one_feature`` 查表查不到才抛的
    （就是用户日志里那条）。所以这里两步都走，把因果链走完整。
    """
    if include_ok_tasks:
        shutil.copytree(VENDOR / "ok_tasks", stage / "ok_tasks",
                        dirs_exist_ok=True)
    else:
        shutil.rmtree(stage / "ok_tasks", ignore_errors=True)

    old = os.getcwd()
    os.chdir(stage)          #: ok-script 按**相对路径**找 ok_tasks
    try:
        import importlib

        import ok.feature.FeatureSet as FS

        importlib.reload(FS)
        fs = FS.FeatureSet(False, str(stage / "assets" / "coco_annotations.json"),
                           0.002, 0.002, 0.8)
        fs.ensure_feature("char_xin")

        #: ★ 第二步：按 ok-ww 的真实调法走一遍（认人时就是这么查的）
        err = ""
        if "char_xin" not in fs.feature_dict:
            try:
                fs.find_one_feature(_blank_frame(), "char_xin")
            except ValueError as exc:
                err = str(exc)
        return set(fs.feature_dict.keys()), err
    finally:
        os.chdir(old)


def _blank_frame():
    """一张纯色截图占位（只为把 find_one_feature 引到"查表"那一步）。"""
    import numpy as np

    return np.zeros((1080, 1920, 3), dtype=np.uint8)


print("=== 让 ok-script 自己 merge 一遍（点名要 char_xin）===")
without, err_without = feature_dict_keys(include_ok_tasks=False)
print("  不带 ok_tasks : 拿到 %d 个特征，含 char_xin = %s"
      % (len(without), "char_xin" in without))
if err_without:
    print("                  ↳ 复现出用户日志里那个错：")
    print("                    ValueError: %s" % err_without[:80])

with_ot, err_with = feature_dict_keys(include_ok_tasks=True)
print("  带   ok_tasks : 拿到 %d 个特征，含 char_xin = %s"
      % (len(with_ot), "char_xin" in with_ot))
if err_with:
    print("                  ↳ 意外报错: %s" % err_with[:80])

print()
#: 三件事都要成立才算修好：
#:   ① 缺 ok_tasks 时 char_xin 不在表里
#:   ② 缺的时候**真的会抛**那个 ValueError（症状对得上）
#:   ③ 带上之后 char_xin 进表、且不再抛
ok = ("char_xin" not in without
      and "char_xin not found in featureDict" in err_without
      and "char_xin" in with_ot
      and not err_with)
print("★ 结论:", "修复有效（打包带上 ok_tasks → char_xin 进表、不再抛错）"
      if ok else "⚠ 结论不符，需复查")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok else 1)
