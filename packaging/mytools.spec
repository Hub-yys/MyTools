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

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

#: SPECPATH 由 PyInstaller 注入 = 本文件所在目录（packaging/），上一级才是项目根
ROOT = Path(SPECPATH).resolve().parent

# ----------------------------------------------------------------- 数据文件
#
# ⚠⚠ 2026-11-04：assets/ **不能整目录收**，要按子目录收、并挡住 splash/。
#
# 整目录收过一次，结果安装包从 215 MB 涨到 **1.1 GB** —— 因为 ``assets/game/splash/``
# 里躺着一个 2026-10-30 录的 ``aemis_wallpaper.mp4``（806 MB）+ 两张 1080p 抽卡图，
# 而它**没有任何运行期读者**：
#
#   * 启动动画 ``src/gui/startup_splash.py`` 已于 2026-11-04 删掉（3429 行死代码那批），
#   * 视频版抽卡动画 ``gacha_video.has_video()`` 要 ``skin["video"]`` 字段，
#     而 ``src/core/skins.py`` 现在只剩一款 ``glass`` 主题、根本没有该字段，
#     所以这条路**永远走不到**（``SKINS`` 实测 video/splash/avatar 全是 None），
#   * Web 外壳的素材白名单 ``web_shell.GAME_ASSET_SUBDIRS`` 也只有
#     ``avatars / echo_sets / echoes / weapons``，明确不挂 splash（见那里的注释）。
#
# 下面改成「遍历 assets 的直接子目录 + assets/game 的直接子目录」，
# 只挡 ``game/splash``。这样以后**新加的子目录会自动进包**（不会静默漏），
# 想再挡谁就往 _ASSET_SKIP 里加一行。
_ASSET_ROOT = ROOT / "assets"

#: 相对 ``assets/`` 的路径，**不**进安装包（省体积，且确认没有运行期读者）
_ASSET_SKIP = {
    "game/splash",     # 773 MB：aemis_wallpaper.mp4 806 MB —— 启动动画已删，无人读
}


def _asset_pairs() -> list:
    """把 ``assets/`` 拆成一条条 datas 条目，跳过 ``_ASSET_SKIP``。"""
    pairs = []
    for top in sorted(_ASSET_ROOT.iterdir()):
        if top.is_dir():
            if top.name != "game":
                pairs.append((str(top), f"assets/{top.name}"))
                continue
            for sub in sorted(top.iterdir()):
                rel = f"game/{sub.name}"
                if sub.is_dir() and rel not in _ASSET_SKIP:
                    pairs.append((str(sub), f"assets/{rel}"))
        else:
            pairs.append((str(top), "assets"))
    return pairs


datas = _asset_pairs() + [
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
    # ⚠ 整个 assets 目录收 —— 也包括我们**自己加的**模板图：
    #   ``images/pickup_locked_full.png``（2026-10-28 加入）
    #   它是「拾取声骸时提示框上的锁定角标」，从用户录屏裁的 28x30 图标
    #   贴在 1920x1080 画布上，coco 里登记为特征 ``pickup_locked``。
    #   战斗报告的「锁定声骸」计数就靠它（见 ``okww_farm.read_pickup_state``）。
    #   漏了它 → 锁定声骸永远是 0，但不报错（很难发现）。
    (str(OKWW / "assets"), "vendor/okww/assets"),
    (str(OKWW / "i18n"), "vendor/okww/i18n"),
    (str(OKWW / "config.py"), "vendor/okww"),
]
# ⚠⚠ ``ok_tasks/`` 必须一起收 —— 漏了它 = **自动战斗全部认不出角色**（2026-10-09 实机翻车）
#
# 它是上游 ok-ww 的**官方扩展点**（不是我们的代码）：``FeatureSet.read_from_json``
# 会按**相对路径** ``os.path.join('ok_tasks','assets','coco_annotations.json')``
# 去找这个文件，把里面的模板**合并**进特征表。我们的「心」识别模板
# （``tools/make_xin_templates.py`` 生成）就放在这里。
#
# 漏掉的后果**极其隐蔽**：界面正常、日志只有一行 ``Merged ...`` 不见了，
# 但 ``char_names`` 里有 ``char_xin`` → ``FeatureSet.find_one_feature`` 直接
# ``raise ValueError: Labels.char_xin not found in featureDict``。
# 而 ``get_char_by_pos`` 是拿**整张角色表**（61 个）一次性匹配的 ——
# **一个模板缺失就让所有队伍都认不出人**（用户看到的是"清宵/达妮娅/莫宁
# 这队不能自动战斗"，实际跟队伍里是谁毫无关系）。
datas += [
    (str(OKWW / "ok_tasks"), "vendor/okww/ok_tasks"),
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

# ⚠ Web 界面（``src/gui/web/``）必须**当数据打进去**（2026-11-04，用户「直接1 2 3 4 全做」第 3 项）
#
# 之前这个目录一条都没有 → 打出来的包 ``src/gui/web_shell.py`` 里
# ``WEB_DIR = Path(__file__).resolve().parent / "web"`` 指向不存在的目录，
# ``web_base_url()`` 校验不到 ``index.html`` 直接抛异常，``create_shell()``
# 捕获后**静默退回旧 Qt 界面** —— 用户装的正式版一直在跑老界面，看不出任何报错。
#
# frozen 布局：``__file__`` 在 ``_internal/src/gui/web_shell.py``，所以目标目录必须
# 正好是 ``src/gui/web``（与源码树同构），不能写成 ``web`` 或 ``gui/web``。
#
# **``dev/`` 子目录不打**：那是 js_sanity / pages_verify 等验证脚本，792 KB，
# 正式版用不到。
_WEB_DIR = ROOT / "src" / "gui" / "web"
datas.append((str(_WEB_DIR / "index.html"), "src/gui/web"))
for _sub in ("assets", "css", "js"):
    datas.append((str(_WEB_DIR / _sub), f"src/gui/web/{_sub}"))

# ----------------------------------------------------------------- 隐藏导入
# onnxocr 内部按字符串拼模块名导入预测器（predict_det/rec/cls/system…），
# 静态分析看不全，这里整包收一遍，避免运行到 OCR 才报 ModuleNotFoundError。
hiddenimports = collect_submodules("onnxocr")

# Web 界面的四个 Qt 模块是在**函数体里延迟 import** 的
# （``src/gui/web_shell.py:469-471`` 的 ``from PySide6.QtWebChannel import QWebChannel`` 等，
# 失败就 ``loadFailed.emit`` 退回旧界面）—— PyInstaller 的静态分析抓不到函数内 import，
# 不显式登记的话打包版会走「QtWebEngine 不可用」分支，又是静默退回老界面。
hiddenimports += [
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
]


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
    # ⚠ 2026-11-04：QtWebEngineCore / QtWebEngineWidgets / QtWebChannel 原来排在这里，
    # 结果是**打包版跑不了 Web 界面**（import 失败 → 静默退回旧 Qt 界面）。
    # 用户「直接1 2 3 4 全做」第 3 项要求带上，所以从排除表里拿掉了。
    # QtWebEngineQuick 保留排除 —— 本项目只用 Widgets 版，Quick 版还会连带 QtQml/QtQuick。
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtUiTools",
    "PySide6.QtSql", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtWebSockets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtLocation",
    "PySide6.QtNetworkAuth", "PySide6.QtHttpServer",
    # ok-script 的 web 后端（ok.ui.web / okww.web）宿主用不到，fastapi 全家桶别进包
    "fastapi", "uvicorn", "pywebview",
    "ok.ui.web", "okww.web",
]

# ------------------------------------------------------------------ OpenVINO 插件
# ★ 2026-11-04：打包版**OCR 全废**的根因在这里，别再删。
#
# 现象（`%LOCALAPPDATA%\WutheringWavesTools\wutheringwavestools.log`）::
#
#     WARNING ok | NPU OCR test failed, falling back to CPU: ...
#       Unable to read the model: "...\_internal\onnxocr\models\ppocrv5\det\det.onnx"
#       Please check that model format: ".onnx" is supported and the model is correct.
#       Available frontends: jax pytorch
#     ERROR   ok | init default ocr error
#
# 关键那句 **`Available frontends: jax pytorch`** —— OpenVINO 说它**不认识 .onnx**。
#
# 原因：``src/tools/game/auto_combat/okww_boot.py:151`` 配了
# ``"params": {"use_openvino": True, "use_npu": True}``（2026-10-27 为跟 ok-ww 对齐），
# 于是 ``onnxocr/predict_base.py:48`` 走 ``import openvino as ov`` + ``core.read_model(...)``。
# 但 OpenVINO 的前端/设备插件是**运行时由 Core() 动态 dlopen 的**，PyInstaller 的静态
# 分析一个都看不到；而 PyInstaller（含 _pyinstaller_hooks_contrib 6.x）**没有 openvino 的
# hook**（只有 ``hook-onnxruntime.py``）。结果打包产物 ``_internal/openvino/libs/`` 里
# **只有 4 个 dll**（openvino.dll / jax_frontend / pytorch_frontend / tbb12）——
# 恰好就是「被 import 过的那几个」，ONNX 前端和 CPU 插件全丢。
#
# 后果：``okww_task.py:929/1886``、``echo_enhance/reader.py:122``、``same_echo.py:293``、
# ``nest_sweep/okww_task.py:425/465`` 全部依赖 ``self.ocr(...)`` → 打包版里**所有 OCR
# 驱动的任务都跑不了**，而且只在日志里留一条 ERROR，界面上看不出来。
#
# 修法：``collect_dynamic_libs("openvino")`` 实测能收全 22 个 dll，这里按名字过滤掉
# **本机证明用不到**的两组（各附实测体积），其余全收：
_OV_LIBS = collect_dynamic_libs("openvino")
_OV_SKIP = (
    # NPU 编译器栈（78.6 + 6.9 + 0.5 + 0.4 = 86.4 MB）：
    # 本机 ``Core().get_property("NPU", "AVAILABLE_DEVICES") == []``，onnxocr 每次
    # 都会先报 ``openvino npu unavailable`` 再回退 CPU，插件永远不会被加载。
    "openvino_intel_npu_compiler",
    "openvino_intel_npu_compiler_loader",
    "openvino_intel_npu_plugin",
    "openvino_intel_npu_vm_runtime",
    # GPU 插件（32.4 MB）：onnxocr 里写死禁用 GPU 探测
    # （日志 ``openvino device candidates [...]; gpu discovery disabled``）。
    "openvino_intel_gpu_plugin",
)
binaries = [
    (src, dst) for (src, dst) in _OV_LIBS
    if not any(Path(src).stem == name for name in _OV_SKIP)
]
# openvino.frontend.onnx / .paddle 这两个包里有 .pyd（py_onnx_frontend / py_paddle_frontend），
# 静态分析同样抓不到 —— 不登记的话哪怕 dll 齐了，Python 侧 still 找不到前端模块。
hiddenimports += ["openvino.frontend.onnx", "openvino.frontend.paddle"]

a = Analysis(  # noqa: F821 - PyInstaller 注入
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(OKWW)],   # OKWW：让分析器能解析 okww.* 导入
    binaries=binaries,
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
