# -*- mode: python ; coding: utf-8 -*-
"""WutheringWavesTools（鸣潮工具箱）的 PyInstaller 打包配置（**onedir**）。

为什么用 onedir 而不是 onefile：本项目带 30MB 资源 + 21MB OCR 模型 + Qt，
onefile 每次启动都要把上百 MB 解压到临时目录（启动慢好几秒，也更容易被杀软盯上）。

打包进去的东西分三类：

1. **代码**：``main.py`` + ``src/``（PyInstaller 自己顺着 import 抓）；
2. **只读资源**（``assets/``、``src/core/data/``）：datas 放进解包目录，
   运行时由 ``src/core/paths.py::resource_dir()`` 从 ``sys._MEIPASS`` 里取；
3. **用户数据种子**（``data/*.json``）：首次运行由 ``paths.ensure_user_data()``
   拷到 ``%LOCALAPPDATA%\\WutheringWavesTools``，之后所有读写都在那边 —— **不写程序目录**
   （装到 Program Files 也能正常保存；``data/probe/`` 这类运行产物不打进包里）。

⚠ OCR 模型（``onnxocr/models/ppocrv5`` 里的 det/cls/rec.onnx + 字典，约 21MB）
是**数据文件**不是代码，不显式收就会漏，运行时才发现"认不出字"。

构建：``pyinstaller packaging/mytools.spec --noconfirm``（或用根目录的 package.ps1）
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

#: SPECPATH 由 PyInstaller 注入 = 本文件所在目录（packaging/），上一级才是项目根
ROOT = Path(SPECPATH).resolve().parent

# ----------------------------------------------------------------- 数据文件
datas = [
    # 只读资源：角色头像 / 声骸图 / 工具图标（约 30MB）
    (str(ROOT / "assets"), "assets"),
    # 图鉴 / 掉落池等游戏数据：既当种子，也是"资源库更新"的初值
    (str(ROOT / "src" / "core" / "data"), "src/core/data"),
]
# 用户数据种子：只要 json，data/probe/ 这类运行产物不打包
datas += [(str(path), "data") for path in sorted((ROOT / "data").glob("*.json"))]
# OCR 模型与字典
datas += collect_data_files("onnxocr")

# ----------------------------------------------------------------- ok-ww vendor
# vendored ok-ww（AGPL-3.0，见 README「开源许可」）：模板图 / YOLO 模型 / i18n /
# 根 config.py（宿主用 importlib 从文件路径加载，必须当数据放一份）
OKWW = ROOT / "vendor" / "okww"
datas += [
    (str(OKWW / "assets"), "vendor/okww/assets"),
    (str(OKWW / "i18n"), "vendor/okww/i18n"),
    (str(OKWW / "config.py"), "vendor/okww"),
]
# ok-script 框架（PyPI 包）：模块动态导入多（capture/interaction/ocr 后端按配置选择），
# 整包收模块 + 数据；okww 包的 .py 也当数据放一份（它的 TaskManager 按类路径字符串
# 导入，源码随包更稳，也符合 AGPL「随附源码」的精神）
datas += collect_data_files("ok")
for _py in sorted((OKWW / "okww").rglob("*.py")):
    if "__pycache__" in _py.parts:
        continue
    dest = ("vendor/okww" / _py.relative_to(OKWW)).parent.as_posix()
    datas.append((str(_py), dest))

# ⚠ 工具目录必须**当数据再放一份**（关键，别删）：
#   工具是靠 ``pkgutil.walk_packages`` **扫文件系统**发现的，而打包后代码都在压缩
#   归档里、磁盘上没有 .py —— 实测一个模块都发现不到，界面上表现为
#   「工具（暂无）」「已收录 0 个工具」，而且不报错（只在日志里留一条 warning）。
#   所以：① hiddenimports 把工具模块收进归档（保证 import 得到）；
#        ② 源码再当数据放到 ``_internal/src/tools/``（保证 walk_packages 扫得到）。
for _py in sorted((ROOT / "src" / "tools").rglob("*.py")):
    if "__pycache__" in _py.parts:
        continue
    datas.append((str(_py), str(_py.parent.relative_to(ROOT))))

# ----------------------------------------------------------------- 隐藏导入
# onnxocr 内部按字符串拼模块名导入预测器（predict_det/rec/cls/system…），
# 静态分析看不全，这里整包收一遍，避免运行到 OCR 才报 ModuleNotFoundError。
hiddenimports = collect_submodules("onnxocr")


def local_modules(package_dir: str, root: Path | None = None, top: str | None = None) -> list:
    """把 ``root/package_dir`` 下的模块名收成 ``top.x.y`` 形式（root 缺省=项目根）。

    ⚠ **不要用 ``collect_submodules("src")`` 收本项目自己的代码**：那个函数是在构建进程里
    import 目标包来枚举子模块的，而构建时 ``sys.path`` 里只有 site-packages 和 spec 所在目录
    （``packaging/``）—— 项目根不在里面，于是它**返回空列表、还不报错**。
    实测就是这么翻的车：工具模块没进归档，运行时靠 datas 里的 .py 兜住了，
    但那些模块**自己 import 的东西**（如 ``src.core.wuwa_update``）没被分析，
    于是加载到一半 ModuleNotFoundError。

    改成直接走文件系统，跟 sys.path 无关。
    """
    base = (root or ROOT) / package_dir
    names = []
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).with_suffix("")
        parts = ([] if top is None else [top]) + list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            names.append(".".join(parts))
    return names


hiddenimports += local_modules("src", top="src")

# ok-script 框架：**不能用 collect_submodules** —— ok 的 __init__ 里有运行时导入
# 魔法，它会枚举出一批磁盘上不存在的模块名（ok.gui.debug.* 等），PyInstaller 全报
# "Hidden import not found" 然后构建失败。改按 site-packages 里的真实文件收集。
import ok as _ok  # noqa: E402

OK_PKG_DIR = Path(_ok.__file__).parent
hiddenimports += local_modules("", root=OK_PKG_DIR, top="ok")
# vendored ok-ww：走文件系统收（避开 collect_submodules 的构建期 sys.path 陷阱）
hiddenimports += local_modules("okww", root=OKWW, top="okww")

# ----------------------------------------------------------------- 排除项
# 只排**确定用不到**的大件。宁少勿多：排错了是运行期才炸，比体积大更麻烦。
# 特别注意**不要**排 QtSvg / QtNetwork —— qfluentwidgets 画图标和查更新要用。
excludes = [
    "tkinter", "_tkinter",
    "matplotlib", "scipy", "pandas", "IPython", "jupyter", "notebook",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtUiTools",
    "PySide6.QtSql", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtWebSockets",
    "PySide6.QtWebChannel", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtLocation",
    "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
    # ok-script 的 web 后端（ok.ui.web / okww.web）宿主用不到，fastapi 全家桶别进包
    "fastapi", "uvicorn", "pywebview",
    "ok.ui.web", "okww.web",
]

a = Analysis(  # noqa: F821 - PyInstaller 注入
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(OKWW)],   # OKWW：让分析器能解析 okww.* 导入
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WutheringWavesTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 没装 UPX，也不建议用（杀软误报率高）
    console=False,             # GUI 程序：别弹黑框
    # ★ 以管理员身份运行（清单里写 requireAdministrator）。**必须**：
    #   鸣潮带 ACE 反外挂，游戏跑在 High 完整性级别，Windows 的 UIPI 会拦掉
    #   低权限进程发往高权限窗口的全部输入 —— 表现就是"点了游戏一点反应都没有"，
    #   而且 keybd_event 是静默失败（连报错都没有）。
    #   代价：每次启动会弹一次 UAC 确认（这是 Windows 的规矩，绕不开）。
    uac_admin=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico"),
    version=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="WutheringWavesTools",
)
