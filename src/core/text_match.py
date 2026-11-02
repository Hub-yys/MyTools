"""★ 搜索匹配规则（中文子串 + 拼音）—— **全项目共用一份**。

## 为什么放在 ``core``（2026-11-02 从 ``gui/pickers.py`` 搬过来）

这些函数原来是 ``gui/pickers.py`` 的模块级函数。但 Web 桥接层
（``core/web_bridge.py``）也要用它 —— 而 **core 不该 import gui**
（依赖方向反了：core 是底层，gui 是上层）。

搬到这里之后：

* ``gui/pickers.py`` 从这儿 import 再 **re-export** —— 老调用方
  （``config_interface.py`` / ``task_editor_dialog.py`` / ``pickers`` 自己）
  **一行都不用改**；
* ``core/web_bridge.py`` 直接从 ``core.text_match`` 拿，依赖方向正确。

## 规则（用户 2026-09-30 定，别改）

.. code:: text

    "加上搜索，和前面下拉列表搜索一样的"

所以下框框和配置页搜索框**必须是同一套规则** —— 这就是「只此一份」的理由。

匹配顺序：

1. 空关键词（含纯空白）→ 全命中
2. **中文走子串** —— ``"绯" in "绯雪"``
3. **纯字母 additionally 走拼音** —— 全拼 ``feixue`` 或首字母 ``fx`` 都行

⚠ 只在纯字母输入时试拼音：打中文时子串匹配已经够用，而且中文 key
和拼音串不可能互相包含 —— 加进去只会白算。
"""

from __future__ import annotations

try:  # 拼音搜索是可选增强：没装 pypinyin 就退化成只有中文子串匹配
    from pypinyin import Style as _PinyinStyle
    from pypinyin import lazy_pinyin as _lazy_pinyin
except ImportError:  # pragma: no cover
    _lazy_pinyin = None
    _PinyinStyle = None


def pinyin_keys(text: str) -> tuple[str, str]:
    """算出搜索用的拼音索引 → ``(全拼, 首字母)``，都小写、只留字母数字。

    ``"穗穗"`` → ``("suisui", "ss")``；
    ``"漂泊者·衍射"`` → ``("piaobozheyanshe", "pbzys")`` —— 中间的 ``·`` 被滤掉，
    所以敲 ``pbz`` 也能搜到。

    没装 pypinyin 时返回空串：拼音搜索失效，中文子串搜索照常。
    """
    if _lazy_pinyin is None:
        return "", ""

    def keep_alnum(value: str) -> str:
        return "".join(ch for ch in value if ch.isalnum())

    full = "".join(_lazy_pinyin(text)).lower()
    initial = "".join(_lazy_pinyin(text, style=_PinyinStyle.FIRST_LETTER)).lower()
    return keep_alnum(full), keep_alnum(initial)


def matches_keyword(keys: tuple[str, str], text: str, keyword: str) -> bool:
    """``text`` 是否命中 ``keyword`` —— **全项目共用的搜索匹配规则**。

    * 空关键词（含**纯空白**）= 全命中；
    * 中文走**子串**；
    * **纯字母** additionally 走拼音（全拼或首字母都行）。

    ``keys`` 是 :func:`pinyin_keys` 的返回值 ``(全拼, 首字母)``。

    ⚠ **自己 ``strip()``**：调用方忘了去空格时，"   " 会被当成关键词，
    结果一条都搜不到（看起来像"搜索坏了"）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return True
    if keyword in text:
        return True
    if not (keyword.isascii() and keyword.isalpha()):
        return False
    lowered = keyword.lower()
    full, initial = keys
    return lowered in full or lowered in initial


def search_keys(text: str) -> dict:
    """给前端用的搜索索引：``{text, full, initial}``。

    Web 页面拿这个自己拼判断（和 :func:`matches_keyword` 同一套规则）——
    拼音依赖 ``pypinyin``（Python 包），**JS 侧算不出来**，所以必须后端给。
    """
    full, initial = pinyin_keys(text)
    return {
        "text": str(text or ""),
        "full": full,
        "initial": initial,
    }


__all__ = ["matches_keyword", "pinyin_keys", "search_keys"]
