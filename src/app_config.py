"""MyTools 应用层常量。

改这里的东西不需要动工具代码；新增分类走 :mod:`src.core.categories`。
"""

APP_NAME = "MyTools"
APP_VERSION = "0.4.1"
APP_AUTHOR = "MyTools"

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

CONFIG_DIR_NAME = "MyTools"
