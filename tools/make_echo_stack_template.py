"""生成声骸「层叠图标」模板 —— 强化时的"这个声骸未强化"判据。

## 为什么需要它

2026-10-02 用户报："3.7 更新后，更新了声骸堆叠，导致强化好了一个声骸后，
会自动跳到强化好的声骸位置，从而不能继续强化到其他声骸了"。

## 根因（读 `vendor/okww/okww/task/EnhanceEchoTask.py` 得出）

ok-ww 的循环**从不主动选下一个声骸**：

    while True:
        enhance = self.find_echo_enhance()   # 右边"培养"按钮在不在
        current_level = self.is_0_level()    # 当前声骸是不是 0 级
        if not current_level:
            return                            # ← 认为干完了，收工
        self.click(enhance)                   # 强化**当前光标**那个

它假设"强化完 ESC 回列表，光标还在原位"。**3.7 的堆叠打破了这个假设** ——
强化好的声骸被归类重排，光标被带过去，于是 `is_0_level()` 读到"不是 0 级"
→ 直接收工。

## 解法（用户确认过约束）

用户实测："滚动不能移动光标，上下左右也不能，**只能通过鼠标选择移动光标**"
→ **唯一的办法就是点格子**。

## 判据：卡片左下的**层叠图标**

用户给的截图证明：卡片底部有两种形态 ——

* **层叠图标 + 数字** → 数字是**持有数量**（未强化）
* **只有 `+N`** → 是**强化等级**（已强化）

实测（两张截图 × 18 格）：

========================  ==========================
未强化（有图标）           已强化（无图标）
========================  ==========================
得分 **0.756 ~ 1.000**    得分 **-0.18 ~ -0.06**
========================  ==========================

完全不重叠 —— 比 OCR 判 `+N` 可靠得多。

⚠ **模板必须从截图裁（22x18），不能用用户给的放大图（28x26）** ——
实测放大图匹配得分是负的。

产出（和「心」的模板同一套机制，放进上游的扩展目录）：
    vendor/okww/ok_tasks/assets/images/echo_stack.png
    vendor/okww/ok_tasks/assets/echo_stack.json
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

import cv2
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★ 上游的扩展目录（不是 assets/ —— 那个会被上游更新覆盖）
EXT_DIR = ROOT / "vendor" / "okww" / "ok_tasks" / "assets"
COCO_OUT = EXT_DIR / "echo_stack.json"
IMAGE_OUT = EXT_DIR / "images" / "echo_stack.png"

#: 用户的游戏分辨率（他给过图像设置截图：1920x1080 窗口模式）。
#: ⚠ 和「心」的模板一致 —— 底图和声明都用这个，保证 scale=1、模板原样使用。
SCREEN = (1920, 1080)

#: 截图是 **1280x720**（QQ 缩略图）。
#:
#: ## ⚠⚠ 2026-10-02 实测教训：**不要放大模板**
#:
#: 第一版我把 22x18 的图标放大到 1920 尺度（33x27）再存，
#: 结果在验证脚本里缩回 1280 匹配时得分只有 **0.34~0.38**（阈值 0.7）
#: —— 放大再缩小 = 细节全丢。
#:
#: **oc-ww 的匹配是"把模板缩放到当前屏幕"**（``read_from_json`` 的
#: ``adjust_coordinates``），所以：
#:
#: * 模板**按原始分辨率存**（1280x720 下裁的就存原尺寸）
#: * COCO 里声明 **1280x720**
#: * 用户也是 1280x720 玩 → scale=1，**模板原样使用**
#:
#: 这样匹配得分 0.9+（实测）。⭐ 关键：**模板分辨率要匹配"裁剪时"的分辨率**，
#: 而不是"游戏设置里的分辨率"—— 用户实际是 1280x720 窗口。
SHOT_RES = (1280, 720)

#: 第一张参考截图（3 排 × 6 列的完整列表）
SHOT = pathlib.Path(
    r"C:\Users\86176\AppData\Roaming\dsh-desktop\harness\attachments\v1"
    r"\objects\49"
    r"\497c0d6d1e949c008c5cb850ccbbb6007e1fb3945b98fa6ee69cd169b748c2e1")

#: 层叠图标在**第一排第一张卡**里的位置（1280x720 坐标）。
#: 量法：卡片 x 115~217.5 / y 87.5~217.5，图标在卡片左下。
ICON_BOX = (124, 193, 146, 211)      # → 22 x 18

#: ★★ 匹配时搜索框要比模板大这么多像素（**必需，不是保险**）。
#:
#: ## 实测（2026-10-02，18 格逐格验证）
#:
#: ======================  ==========  ==========
#: 配置                     漏检格数    未强化最低分
#: ======================  ==========  ==========
#: 放大模板(33x27) + pad0   **7 格**     0.321
#: 原尺寸(22x18)  + pad0    **7 格**     0.321
#: 原尺寸(22x18)  + **pad6**  **0 格**   **0.887**
#: ======================  ==========  ==========
#:
#: **元凶是 pad**：每张卡的图标位置有 **1~2 像素**偏差，
#: 而 ``cv2.matchTemplate`` 在"搜索图尺寸 == 模板尺寸"时**只产出一个值**，
#: 没有滑动余地 → 偏一点就崩（0.36 vs 1.00）。
#:
#: ok-ww 的 ``find_one(box=...)`` 正是"在 box 里滑动找模板"，
#: 所以 box **必须留出滑动余量**。
#:
#: ⚠ 这是动手写代码前**验证模板时抓到的**。任何人改这个模板都要重跑
#: ``_verify_stack.py``（两张截图 × 18 格）。
SEARCH_PAD = 6

#: 分类名（ok-ww 的 find_one 用这个名字找模板）
LABEL = "echo_stack_icon"


def build() -> int:
    if not SHOT.exists():
        print(f"✗ 找不到截图 {SHOT}")
        return 1

    shot = Image.open(SHOT).convert("RGB")
    print(f"来源截图 {shot.size}")
    if shot.size != SHOT_RES:
        print(f"⚠ 截图尺寸 {shot.size} 和预期的 {SHOT_RES} 不一致 —— "
              f"网格坐标是按 {SHOT_RES} 量的，模板可能对不上")

    icon = shot.crop(ICON_BOX)
    print(f"裁出图标 {icon.size}（**原尺寸存，不放大**）")

    # 底图 = 截图分辨率，图标贴左上角
    # （⚠ 必须是**屏幕尺寸**，否则 ok-script 会缩放模板 —— 见「心」的教训）
    canvas = Image.new("RGB", SHOT_RES, (0, 0, 0))
    canvas.paste(icon, (0, 0))

    IMAGE_OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(IMAGE_OUT)
    print(f"底图 -> {IMAGE_OUT}  {canvas.size}")

    coco = {
        # ⚠ description 必须纯 ASCII —— ok-script 的 load_json 用
        #   open(path,'r')（没指定 encoding），中文会 UnicodeDecodeError
        "info": {"description": "MyTools: echo stack icon (unenhanced marker)"},
        "images": [{"id": 1, "file_name": "images/echo_stack.png",
                    "width": SHOT_RES[0], "height": SHOT_RES[1]}],
        "categories": [{"id": 1, "name": LABEL, "supercategory": "echo"}],
        "annotations": [{
            "id": 1, "image_id": 1, "category_id": 1,
            "bbox": [0, 0, icon.width, icon.height],
            "area": icon.width * icon.height, "iscrowd": 0,
        }],
    }
    COCO_OUT.write_text(json.dumps(coco, ensure_ascii=True, indent=2) + "\n",
                        encoding="utf-8")
    print(f"标注 -> {COCO_OUT}")
    print(f"   {LABEL}  bbox=[0, 0, {icon.width}, {icon.height}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
