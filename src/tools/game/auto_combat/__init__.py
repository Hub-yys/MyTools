"""4C 自动战斗工具 —— ok-ww 引擎宿主。

「4C」= 4-Cost（Boss）声骸。战斗本体**整体来自 ok-ww**（``vendor/okww``，
AGPL-3.0，详见 README「开源许可」一节）：

    okww_boot.py   宿主：无 GUI 启动 ok-script 运行时 + 启停任务 + 日志收集
    tool.py        注册入口 + 宿主控制面板（启动 / 停止 + 状态）

**引擎随程序启动就在后台加载**（``okww_boot.autostart_engine``，由 main.py
延迟调用）；工具页点「启动」只是开跑 FarmEchoTask，引擎没起来时会兜底再
boot 一次。MyTools 不实现任何战斗逻辑；模板匹配、OCR、后台按键
（PostMessage）全部走 ok-ww / ok-script 自己的体系。
"""
