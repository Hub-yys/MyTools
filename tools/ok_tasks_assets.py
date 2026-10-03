# -*- coding: utf-8 -*-
"""把模板**合并**进 ok-ww 唯一会加载的那个 COCO 文件。

## ⚠⚠ 为什么需要"合并"而不是"各写各的"

ok-script 的 ``FeatureSet.process_data()`` 里**文件名是写死的**::

    ok_tasks_coco = os.path.join('ok_tasks', 'assets', 'coco_annotations.json')

**只读这一个文件。** 其他名字（``echo_stack.json``、``xin.json``…）
**一律不会被加载** —— 实测日志里就是一条无声的::

    Merged 0 features from ok_tasks\\assets\\coco_annotations.json

（我 2026-10-03 先写了 ``echo_stack.json``，实机跑完**一次都没生效**，
日志里连"堆叠修正"都没出现。就是这个原因。）

## 所以

每个生成脚本把自己那份交给我这个模块，我负责:
  1. 底图存进 ``ok_tasks/assets/images/<名字>.png``
  2. 读出 ``coco_annotations.json``
  3. **先删掉同一个 `source` 上一次留下的条目**（幂等重跑，不会越积越多）
  4. 加上这次的新条目（image / category / annotation 的 id 都重新分配）
  5. 写回

这样「心」的模板和声骸层叠图标的模板**互不覆盖**。

## 谁在用

* ``tools/make_xin_templates.py``
* ``tools/make_echo_stack_template.py``
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★ 上游的扩展目录（不是 ``assets/`` —— 那个会被上游更新覆盖）
EXT_DIR = ROOT / "vendor" / "okww" / "ok_tasks" / "assets"
COCO_PATH = EXT_DIR / "coco_annotations.json"
IMAGES_DIR = EXT_DIR / "images"


def _empty() -> dict:
    return {
        # ⚠ description 必须**纯 ASCII** —— ok-script 的 load_json 用
        #   ``open(path, 'r')``（没指定 encoding），中文会 UnicodeDecodeError
        #   把**整个模板加载**搞崩（实测踩过）
        "info": {"description": "MyTools extra templates (merged)"},
        "images": [],
        "categories": [],
        "annotations": [],
    }


def _load() -> dict:
    if not COCO_PATH.exists():
        return _empty()
    try:
        data = json.loads(COCO_PATH.read_text(encoding="utf-8"))
    except Exception as exc:                 # noqa: BLE001 - 坏了就重建，别卡住
        print(f"   ⚠ 读不了 {COCO_PATH.name}（{exc}）—— 重建")
        return _empty()
    for key, default in (("images", []), ("categories", []), ("annotations", [])):
        data.setdefault(key, default)
    data.setdefault("info", {"description": "MyTools extra templates (merged)"})
    return data


def merge(source: str, image_name: str, image: Image.Image,
          entries: list[tuple[str, tuple[int, int, int, int]]]) -> None:
    """把一份模板合并进去。

    :param source: 来源标签（例如 ``"xin"`` / ``"echo_stack"``）——
        用来**识别并移除**上一次同来源的条目，保证幂等
    :param image_name: 底图文件名（不含 ``images/`` 前缀，不含扩展名）
    :param image: 底图（**必须是屏幕尺寸**，见各生成脚本里的说明）
    :param entries: ``[(类别名, bbox), ...]``；bbox 是**底图内的**像素坐标
    """
    # ---- 1) 存底图 ----
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    file_name = f"images/{image_name}.png"
    image.save(IMAGES_DIR / f"{image_name}.png")
    print(f"底图 -> {IMAGES_DIR / (image_name + '.png')}  {image.size}")

    # ---- 2) 读现有的 ----
    data = _load()

    # ★ 先删掉同 source 的旧条目（幂等重跑的关键）
    #   category 的 supercategory 就是我们的 source 标签
    old_cat_ids = {c["id"] for c in data["categories"]
                   if c.get("supercategory") == source}
    if old_cat_ids:
        data["categories"] = [c for c in data["categories"]
                              if c["id"] not in old_cat_ids]
        data["annotations"] = [a for a in data["annotations"]
                               if a["category_id"] not in old_cat_ids]
        print(f"   （清掉上一次 {source} 的 {len(old_cat_ids)} 个类别）")

    old_image_ids = {i["id"] for i in data["images"]
                     if i.get("file_name") == file_name}
    if old_image_ids:
        data["images"] = [i for i in data["images"]
                          if i["id"] not in old_image_ids]

    # ---- 3) 追加新的（id 全局唯一，接着最大的排）----
    next_img = max((i["id"] for i in data["images"]), default=0) + 1
    next_cat = max((c["id"] for c in data["categories"]), default=0) + 1
    next_ann = max((a["id"] for a in data["annotations"]), default=0) + 1

    data["images"].append({
        "id": next_img, "file_name": file_name,
        "width": image.width, "height": image.height,
    })

    for i, (name, bbox) in enumerate(entries):
        x, y, w, h = bbox
        cat_id = next_cat + i
        data["categories"].append({
            "id": cat_id, "name": name, "supercategory": source})
        data["annotations"].append({
            "id": next_ann + i, "image_id": next_img, "category_id": cat_id,
            "bbox": [x, y, w, h], "area": w * h, "iscrowd": 0,
        })

    # ---- 4) 写回（ensure_ascii 保证纯 ASCII）----
    COCO_PATH.write_text(
        json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"合并 -> {COCO_PATH}")
    print(f"   本来源新增 {len(entries)} 条；文件里现在共 "
          f"{len(data['categories'])} 个类别 / {len(data['images'])} 张底图")


def categories_of(source: str) -> list[str]:
    """看某个来源现在有哪些类别（自检用）。"""
    data = _load()
    return [c["name"] for c in data["categories"]
            if c.get("supercategory") == source]
