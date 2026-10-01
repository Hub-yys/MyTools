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
SCREEN = (1280, 720)

#: 队伍头像（那张裁过的竖条图）
TEAM_BAR = pathlib.Path(
    r"C:\Users\86176\AppData\Roaming\dsh-desktop\harness\attachments\v1"
    r"\objects\2a\2a980a89653029fc56685daa89a438695aa8fcc2f011024de8099994d7f9b8a9")

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


def build() -> int:
    if not SHOTS.exists():
        print(f"✗ 找不到截图目录 {SHOTS}")
        return 1

    # ---- 1) 收集所有要贴的图块 ----
    pieces: list[tuple[str, Image.Image]] = []

    # 队伍头像（认人用）—— 需要从竖条图里裁
    if TEAM_BAR.exists():
        team = Image.open(TEAM_BAR).convert("RGB")
        avatar = team.crop((150, 90, 290, 215))
        pieces.append(("char_xin", avatar))
        print(f"  char_xin        队伍头像 {avatar.size}")
    else:
        print("  ⚠ 没有队伍栏截图 —— char_xin 无法生成（认人会失败）")

    # 状态条
    for category, shot, which in TEMPLATES:
        path = SHOTS / shot
        if not path.exists():
            print(f"  ✗ {category}: 缺 {shot}")
            continue
        src = Image.open(path).convert("RGB")
        box = BAR_BOX if which == "bar" else HEAD_BOX
        tile = src.crop(box)
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
