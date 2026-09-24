"""应用层常量 —— **名字与版本的唯一真源**。

改这里的东西不需要动工具代码；新增分类走 :mod:`src.core.categories`。

⚠ 名字/版本只在这里定义一次，别处一律 ``import``：曾经版本号各写一份，出过
「安装包 0.3.0 / 界面 v0.1.0」对不上的事（2026-09-23）。用户数据目录名也认
:data:`APP_NAME`（:mod:`src.core.paths` 直接从这里导入，不再自己抄一份）。

* :data:`APP_NAME` —— 英文标识：exe 名 / 安装包名 / 安装目录名 / 用户数据目录名；
* :data:`APP_DISPLAY_NAME` —— 中文显示名：窗口标题、主页大标题。
"""

APP_NAME = "WutheringWavesTools"
APP_DISPLAY_NAME = "鸣潮工具箱"
APP_VERSION = "0.5.3"
APP_AUTHOR = "yys"

WINDOW_MIN_WIDTH = 960
WINDOW_MIN_HEIGHT = 640
WINDOW_DEFAULT_WIDTH = 1150
WINDOW_DEFAULT_HEIGHT = 760

# 侧栏（导航）宽度：设成"展开"宽度，再藏掉展开按钮，之后可以左右拖拽调整
NAV_EXPAND_WIDTH = 185
MIN_NAV_WIDTH = 150

# 主页：块状工具卡片（图标在上、名称在下，说明走悬浮提示）
CARD_GRID_COLUMNS = 5
CARD_GRID_SPACING = 12
CARD_WIDTH = 158
CARD_HEIGHT = 128
CARD_ICON_SIZE = 46

# 工具页：顶部下拉框选工具
TOOL_COMBO_WIDTH = 280
