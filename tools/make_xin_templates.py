"""给 ok-ww 加「心」的识别模板 —— 生成模板底图 + COCO 标注。

## ★ 放哪里：`ok_tasks/assets/`（**上游的官方扩展点**）

我本来打算加一份独立的 json 放 `vendor/okww/assets/` 旁边，但读了 ok-script
的 `FeatureSet.process_data()` 后发现**上游早就留了扩展位**：

```python
# ok/feature/FeatureSet.py
ok_tasks_coco = os.path.join('ok_tasks', 'assets', 'coco_annotations.json')
if os.path.exists(ok_tasks_coco) and ... != self.coco_json:
    extra_features, extra_boxes, ... = read_from_json(ok_tasks_coco, ...)
    self._merge_features(extra_features, extra_boxes, ...)   # 自动合并！
```

而且 MyTools 启动 ok-ww 时会 `os.chdir(VENDOR_DIR)`（见
``okww_boot.py``），所以那个相对路径正好落在
``vendor/okww/ok_tasks/assets/`` —— **实测该目录存在且是空的**。

**为什么这是最稳的位置**：它是上游设计的用户扩展目录，不是打包资源；
上游更新不会覆盖它，也不会有"改了 assets/ 被冲掉"的问题。

产出：
    vendor/okww/ok_tasks/assets/coco_annotations.json
    vendor/okww/ok_tasks/assets/images/xin_templates.png

## 模板内容（都从用户的实机截图裁）

| 类别名 | 用途 | 来源 |
|---|---|---|
| `char_xin` | 队伍栏认人 | 队伍栏截图 |
| `xin_red` | 红狐-紫条（应世心攒能中） | 战斗截图 |
| `xin_red_idle` | 红狐-白条（常态） | 站街截图 |
| `xin_white` | 白狐-金条（一段大已开） | 战斗截图 |
| `xin_dominion` | 统御众机-金柱 | 战斗截图 |

⚠ 所有 bbox 都**由本脚本自己算**，不手写 —— 手写坐标迟早对不上。
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHOTS = pathlib.Path(r"D:\DeepSeek Work\xin_shots")

#: ★ 上游的扩展目录（不是 assets/ —— 那个会被上游更新覆盖）
EXT_DIR = ROOT / "vendor" / "okww" / "ok_tasks" / "assets"
COCO_OUT = EXT_DIR / "coco_annotations.json"
IMAGE_OUT = EXT_DIR / "images" / "xin_templates.png"

#: ★ 截图时的**游戏分辨率** —— 用你实际的显示设置。
#: 1280×720 = 你给的截图分辨率（那台机器就是按它玩的）。
#: ⚠ 写进 COCO 的 images.width/height 用的是这个（不是底图尺寸），
#:   否则 ok-script 会按"底图很窄"去缩放模板，把模板拉糊。
#:
#: ★ 2026-10-01 定稿：用户的游戏是 **1920x1080**（他给了图像设置截图）。
#:   所以底图和声明都用 1920x1080 —— 在用户的环境里 scale=1，模板原样使用。
SCREEN = (1920, 1080)

#: 能量条模板的来源截图是 **1280x720**（QQ 缩略图），要放大到 1920 尺度。
BAR_SCALE = 1920 / 1280

#: ★★ 认人模板的来源：**队伍栏截图**（151x385，三个人竖排）。
#:
#: ## 为什么最终用这张，而不是单人头像特写
#:
#: 我试过三种来源，全部实测过（拿心的模板去匹配战斗画面里心的位置）：
#:
#: ====================================  ======  ==================
#: 来源                                   得分    结论
#: ====================================  ======  ==================
#: 素材库立绘 240x320                      0.350   ❌ 立绘≠游戏内头像
#: QQ 竖条截图 365x644（被缩放）            0.501   ❌ 糊
#: 单人头像特写 140x113                     0.694   ⚠ 勉强，仍不够稳
#: **队伍栏截图 151x385（本版）**           **0.958**  ✅ 4/4 全中
#: ====================================  ======  ==================
#:
#: ## 关键：**自标定尺度**
#:
#: 用户的截图经过 QQ 压缩，**不是** 1:1 的游戏像素。硬猜尺度必然失败。
#: 所以这里反过来 —— 用 ok-ww **认得出的**守岸人模板当标尺：
#: 在队伍栏第 3 段上扫描缩放系数，找到得分最高的那个（实测 **1.01**，得分
#: **0.984**），那个系数就是"这张图 : 游戏"的真实比例。
#:
#: 标定后交叉验证（同一尺度下）：
#:   3位=守岸人 **0.984** ✓   2位=坎特蕾拉 **0.928** ✓   1位=心 0.683
#: 前两个都对得上 → 尺度可信。
TEAM_BAR = pathlib.Path(r"D:\DeepSeek Work\xin_shots\new_bar.png")

#: 队伍栏里"心"是第几段（0 起）
XIN_SEGMENT = 0

#: 模板里要**内缩**多少（去掉圆形头像的外圈）。
#: 实测扫描：0%→0.399  18%→0.533  30%→0.719  **36%→0.948**  42%→0.929
#: 36% 正好把圆环和背景都去掉、只留人脸那块 —— 和 ok-ww 原生模板的裁法一致。
AVATAR_INSET = 0.36

#: 从 1280×720 战斗截图里裁能量条的框
BAR_BOX = (500, 645, 770, 692)
HEAD_BOX = (590, 640, 690, 695)

#: 每个模板：类别名 → (来自哪张截图, 用 bar 还是 head)
TEMPLATES = [
    ("xin_red", "99a35152d30d216c8b7d733b16b408e6_720.png", "bar"),
    ("xin_red_idle", "f403f9b216ce18e37245e251db2a1270_720.png", "bar"),
    ("xin_white", "e1c1f2d66ba42d85979580cfd2870384_720.png", "bar"),
    ("xin_dominion", "b7b405fb2a34989673e4d168e3174f3f_720.png", "bar"),
]


def _build_avatar() -> tuple[Image.Image | None, str]:
    """造认人模板：**自标定尺度** + 内缩。返回 (图, 说明)。"""
    if not TEAM_BAR.exists():
        return None, f"⚠ 没有队伍栏图（{TEAM_BAR}）—— char_xin 无法生成"

    src = Image.open(TEAM_BAR).convert("RGB")
    seg_h = src.height // 3
    top = XIN_SEGMENT * seg_h
    seg = src.crop((0, top, src.width, top + seg_h))

    # ★ 自标定：用 ok-ww 认得出的角色当标尺，反推这张图的真实尺度
    factor, score, detail = _calibrate_scale(src)
    if factor is None:
        # 标定不出来就按 1.0 硬来（至少尺寸量级对）
        factor = 1.0
        note = "⚠ 标定失败，按 1.0 处理"
    else:
        note = f"标定 {factor:.3f}（{detail} 得分 {score:.3f}）"

    if factor != 1.0:
        seg = seg.resize((max(1, round(seg.width / factor)),
                          max(1, round(seg.height / factor))),
                         Image.LANCZOS)

    w, h = seg.size
    p = int(min(w, h) * AVATAR_INSET)
    avatar = seg.crop((p, p, w - p, h - p))
    return avatar, (f"char_xin        {src.size} 第{XIN_SEGMENT + 1}段 → "
                    f"{note} → 内缩 {AVATAR_INSET:.0%} → {avatar.size}")


#: 标定时用的"尺子"——ok-ww 认得出、且确实在用户队伍里的角色。
#: 每一项：(类别名, 在图里的第几段)
_CALIBRATORS = [("char_shorekeeper", 2), ("char_cantarella", 1)]


def _calibrate_scale(bar: Image.Image) -> tuple[float | None, float, str]:
    """扫描缩放系数，找出让"尺子角色"得分最高的那个。

    ⚠ 为什么要这样：用户的截图过了 QQ 压缩，**不是** 1:1 游戏像素，
    硬猜尺度必然失败（我前几轮就是这么错的）。用 ok-ww 自己的模板当尺子，
    让数据告诉我们真实比例。
    """
    try:
        import cv2
        import numpy as np

        # 用 ok-script 的加载器最稳（它处理尺寸换算，还会把扩展目录合并进来）
        import logging
        import os
        import sys

        vendor = EXT_DIR.parents[1]          # …/vendor/okww
        coords = vendor / "assets" / "coco_annotations.json"
        cwd = os.getcwd()
        os.chdir(vendor)
        sys.path.insert(0, str(vendor))
        logging.disable(logging.CRITICAL)
        try:
            from ok.feature.FeatureSet import read_from_json

            feats, _boxes, _c, _s, _k = read_from_json(str(coords), *SCREEN)
        finally:
            os.chdir(cwd)

        arr = cv2.cvtColor(np.array(bar), cv2.COLOR_RGB2BGR)
        seg_h = arr.shape[0] // 3
        best = (-1.0, None, "")
        for name, seg_index in _CALIBRATORS:
            feat = feats.get(name)
            if feat is None:
                continue
            tpl = feat.mat
            top = seg_index * seg_h
            seg = arr[top:top + seg_h]
            for i in range(50, 200):
                f = i / 100
                t = cv2.resize(seg, (max(1, round(seg.shape[1] / f)),
                                     max(1, round(seg.shape[0] / f))),
                               interpolation=cv2.INTER_AREA)
                if tpl.shape[0] > t.shape[0] or tpl.shape[1] > t.shape[1]:
                    continue
                try:
                    sc = float(cv2.matchTemplate(t, tpl,
                                                 cv2.TM_CCOEFF_NORMED).max())
                except Exception:
                    continue
                if sc > best[0]:
                    best = (sc, f, name)
        return best[1], best[0], best[2].replace("char_", "")
    except Exception as exc:  # noqa: BLE001
        print(f"    标定异常：{type(exc).__name__}: {exc}")
        return None, -1.0, ""


def build() -> int:
    if not SHOTS.exists():
        print(f"✗ 找不到截图目录 {SHOTS}")
        return 1

    # ---- 1) 收集所有要贴的图块 ----
    pieces: list[tuple[str, Image.Image]] = []

    # 认人模板（char_xin）—— 自标定尺度 + 内缩
    ok_avatar, message = _build_avatar()
    print(f"  {message}")
    if ok_avatar is not None:
        pieces.append(("char_xin", ok_avatar))

    # 状态条（源图是 1280 的缩略图，放大到 1920 尺度）
    for category, shot, which in TEMPLATES:
        path = SHOTS / shot
        if not path.exists():
            print(f"  ✗ {category}: 缺 {shot}")
            continue
        src = Image.open(path).convert("RGB")
        box = BAR_BOX if which == "bar" else HEAD_BOX
        tile = src.crop(box)
        if BAR_SCALE != 1.0:
            tile = tile.resize((round(tile.width * BAR_SCALE),
                                round(tile.height * BAR_SCALE)),
                               Image.LANCZOS)
        pieces.append((category, tile))
        print(f"  {category:16} {tile.size}  （来自 {shot[:12]}…）")

    if not pieces:
        print("✗ 一块都没裁到")
        return 1

    # ---- 2) 拼成 **1280×720 的画布** ----
    #
    # ★★ 为什么必须是 1280×720（而不是"刚好放下这些小图"的紧凑尺寸）
    #
    # ok-script 的 read_from_json 是这么缩放的：::
    #
    #     # FeatureSet.py:481
    #     x, y, w, h, scale = adjust_coordinates(
    #         x, y, w, h, width, height, image_width, image_height)
    #     #  image_width/height = **PNG 文件的实际尺寸**（读出来的，不是 json 里写的！）
    #     #  width/height      = 当前屏幕尺寸
    #     scale = min(width / image_width, height / image_height)
    #
    # 我第一版把画布做成"紧凑尺寸"（270×361），于是
    #     scale = min(1280/270, 720/361) = 1.99
    # 模板被**放大近 2 倍**（实测日志 `resized width 1280`，模板从 270 变 539），
    # 匹配率直接归零。
    #
    # 做成和游戏同分辨率（1280×720）后 scale = 1，模板**原样**使用。
    # 模板小图贴在左上角即可 —— 位置在 json 里由 bbox 指定，不影响匹配。
    canvas = Image.new("RGB", SCREEN, (0, 0, 0))
    y = 0
    gap = 12
    boxes: dict[str, tuple[int, int, int, int]] = {}
    for category, tile in pieces:
        canvas.paste(tile, (0, y))
        boxes[category] = (0, y, tile.width, tile.height)
        y += tile.height + gap

    IMAGES_DIR = IMAGE_OUT.parent
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    canvas.save(IMAGE_OUT)
    print(f"\n底图 -> {IMAGE_OUT}  {canvas.size}"
          f"（= 游戏分辨率，见代码里 SCREEN 的说明）")

    # ---- 3) 写 COCO ----
    #
    # ★★ 关键：**声明成游戏屏幕尺寸（1280×720），不是底图尺寸**
    #
    # ok-script 的 read_from_json 会按
    #     scale = min(screen_w / image_w, screen_h / image_h)
    # 把模板**缩放**到当前分辨率。如果这里写 canvas.size（270×361），
    # 它会以为模板来自一张 270px 宽的图 → scale = 1280/270 ≈ 4.74，
    # 把 270px 的模板拉成 539px（实测日志：`resized width 1280`）——
    # 匹配率直接归零。
    #
    # 声明成 1280×720 后 scale = 1，模板**原样**使用（我们的截图就是
    # 1280×720，和游戏分辨率一致）。以后换分辨率时改这一个常量即可。
    categories = [{"id": i + 1, "name": name, "supercategory": "xin"}
                  for i, (name, _im) in enumerate(pieces)]
    id_by_name = {c["name"]: c["id"] for c in categories}
    annotations = []
    for i, (name, _im) in enumerate(pieces):
        x, y_, w, h = boxes[name]
        annotations.append({
            "id": i + 1,
            "image_id": 1,
            "category_id": id_by_name[name],
            "bbox": [x, y_, w, h],
            "area": w * h,
            "iscrowd": 0,
        })

    coco = {
        # ⚠ description 必须是**纯 ASCII** —— ok-script 的 load_json 用
        #   ``open(path, 'r')``（**没指定 encoding**），在中文 Windows 上
        #   按 GBK 解码，写中文进去会 UnicodeDecodeError 把整个加载搞崩
        #   （实测踩过：`'gbk' codec can't decode byte 0x83`）。
        "info": {"description": "MyTools: recognition templates for character Xin "
                                "(generated from in-game screenshots)"},
        # ★ 声明成屏幕尺寸（见上面的说明）—— 模板保持原尺寸
        "images": [{"id": 1, "file_name": "images/xin_templates.png",
                    "width": SCREEN[0], "height": SCREEN[1]}],
        "categories": categories,
        "annotations": annotations,
    }
    # ⚠ 落盘时同样**不能用默认编码**，显式 utf-8 + ensure_ascii（双保险）
    COCO_OUT.write_text(
        json.dumps(coco, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"标注 -> {COCO_OUT}")
    for a in annotations:
        name = next(c["name"] for c in categories if c["id"] == a["category_id"])
        print(f"   {name:16} bbox={a['bbox']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
