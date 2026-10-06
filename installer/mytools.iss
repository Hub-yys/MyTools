; WutheringWavesTools（鸣潮工具箱）—— Inno Setup 脚本
;   由 package.ps1 调用：
;   ISCC.exe /Qp /DMyVersion=0.1.0 /DMyStage=<PyInstaller 输出目录> /DMyOutDir=<输出目录> installer\mytools.iss
;
; 说明：程序装到 %LOCALAPPDATA%\Programs\WutheringWavesTools（免 UAC、可写）；
;       用户的配置**不在**安装目录里 —— 它在 %LOCALAPPDATA%\WutheringWavesTools（见 src/core/paths.py），
;       所以卸载不会连带删掉用户的配置和任务流程，重装 / 升级也不会覆盖。

#ifndef MyVersion
  #define MyVersion "0.1.0"
#endif
#ifndef MyStage
  ; PyInstaller 的 onedir 产物 —— 中间目录（build\ 整棵不进库），
  ; 不是对外产物。dist\ 里只应该有安装包。
  #define MyStage "..\build\stage\WutheringWavesTools"
#endif
#ifndef MyOutDir
  #define MyOutDir "..\dist"
#endif

[Setup]
AppName=鸣潮工具箱
AppVersion={#MyVersion}
AppVerName=鸣潮工具箱 {#MyVersion}
AppPublisher=yys
DefaultDirName={localappdata}\Programs\WutheringWavesTools
DefaultGroupName=鸣潮工具箱
DisableProgramGroupPage=yes
OutputDir={#MyOutDir}
OutputBaseFilename=WutheringWavesToolsSetup-{#MyVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\WutheringWavesTools.exe
ArchitecturesInstallIn64BitMode=x64compatible
; 打包产物有上千个文件（Qt / onnxruntime / OCR 模型），关了"显示文件"页省得刷屏
DisableFinishedPage=no

; ── 自动更新相关（2026-10-05）─────────────────────────────────────────
;
; CloseApplications：检测到旧版还在跑时，**问用户**要不要自动关掉它、
;   装完再重启。
;
;   ⚠ 它的**默认值就是 yes** —— 这里显式写出来是为了"别改它"这件事
;     有据可查（我一度以为没写就会报"文件正在使用"，查了官方文档才发现
;     默认就开着：https://jrsoftware.org/is6help/topic_setup_closeapplications.htm）。
;
;   ⚠ 用 **yes 不要 force**：force 会**强杀**进程，
;     而本程序退出时要收尾（停引擎任务、清理托盘），强杀会让
;     ok-ww 引擎留在半死不活的状态。
;
; RestartApplications：装完把刚才关掉的程序**自动拉起来**。
;   配合下面 [Run] 的 postinstall 一起用 —— 用户装完就能看到新版界面。
CloseApplications=yes
RestartApplications=yes

[Languages]
; Inno 自带语言里没有简体中文，装了中文语言文件就自动用，否则退回英文界面
#if FileExists(AddBackslash(CompilerPath) + "Languages\ChineseSimplified.isl")
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#else
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
; PyInstaller 的 onedir 产物（WutheringWavesTools.exe + _internal\）整个装进去
Source: "{#MyStage}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; AGPL-3.0 合规：内置 ok-ww（vendor/okww）的许可文本与义务说明必须随安装包分发
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs ignoreversion
Source: "..\README.md"; DestDir: "{app}\licenses"; DestName: "README.md"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\鸣潮工具箱"; Filename: "{app}\WutheringWavesTools.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\鸣潮工具箱"; Filename: "{app}\WutheringWavesTools.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\WutheringWavesTools.exe"; Description: "现在启动 鸣潮工具箱"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent
