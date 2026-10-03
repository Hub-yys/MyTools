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

卡片底部有两种形态：

* **层叠图标 + 数字** → 数字是**持有数量**（未强化）
* **只有 `+N`** → 是**强化等级**（已强化）

实测（两张截图 × 18 格）：

========================  ==========================
未强化（有图标）           已强化（无图标）
========================  ==========================
**0.887 ~ 1.000**         **0.047 ~ 0.085**
========================  ==========================

完全不重叠 —— 比 OCR 判 `+N` 可靠得多。

## ⚠⚠ 两个踩过的坑

**① 模板不能放大。** 第一版把 22x18 放大到 33x27 再存，
匹配得分掉到 **0.34~0.38**。模板要**按裁剪时的分辨率存**（1280x720）。

**② 搜索框必须大于模板（`SEARCH_PAD=6`，必需）。**
    放大模板 + pad0 → 漏检 7 格（最低 0.321）
    原尺寸   + pad6 → 漏检 0 格（最低 0.887）
``cv2.matchTemplate`` 在"搜索图 == 模板"时只产出一个值、没有滑动余地。

**③ ★ 文件名必须叫 `coco_annotations.json`。**
ok-script **写死**只读这一个名字；我第一版写成 `echo_stack.json`，
实机**一次都没生效**（日志里一条"堆叠修正"都没有，
只有一行无声的 `Merged 0 features`）。
所以现在走 :mod:`tools.ok_tasks_assets` **合并**进去。

产出（合并进上游的扩展目录）：
    vendor/okww/ok_tasks/assets/images/echo_stack.png
    vendor/okww/ok_tasks/assets/coco_annotations.json  ← 追加一个类别
"""

from __future__ import annotations

import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ok_tasks_assets import merge  # noqa: E402

#: 用户给的截图是 **1280x720**。
#:
#: ## ⚠⚠ 实测教训：**不要放大模板**
#:
#: 第一版我把 22x18 的图标放大到 1920 尺度（33x27）再存，
#: 结果在验证脚本里缩回 1280 匹配时得分只有 **0.34~0.38**（阈值 0.7）
#: —— 放大再缩小 = 细节全丢。
#:
#: **模板要匹配"裁剪时"的分辨率**，而不是"游戏设置里的分辨率"。
SHOT_RES = (1280, 720)

#: 第一张参考截图（3 排 × 6 列的完整列表）
SHOT = pathlib.Path(
    r"C:\Users\86176\AppData\Roaming\dsh-desktop\harness\attachments\v1"
    r"\objects\49"
    r"\497c0d6d1e949c008c5cb850ccbbb6007e1fb3945b98fa6ee69cd169b748c2e1")

#: 层叠图标在**第一排第一张卡**里的位置（1280x720 坐标）。
#: 量法：卡片 x 115~217.5 / y 87.5~217.5，图标在卡片左下。
ICON_BOX = (124, 193, 146, 211)      # → 22 x 18

#: 匹配时搜索框要比模板大这么多像素（**必需，不是保险**）。
#: 完整实测表见模块说明。
SEARCH_PAD = 6

#: 分类名（ok-ww 的 find_one 用这个名字找模板）
LABEL = "echo_stack_icon"

#: 这个来源的标签（合并时用来识别并替换上一次的条目）
SOURCE = "echo_stack"

#: 底图文件名（不含扩展名）
IMAGE_NAME = "echo_stack"


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

    merge(SOURCE, IMAGE_NAME, canvas,
          [(LABEL, (0, 0, icon.width, icon.height))])
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
