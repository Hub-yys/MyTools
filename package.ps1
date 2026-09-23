<#
    MyTools 一键打包：PyInstaller 出绿色目录 → Inno Setup 出安装包

        .\package.ps1                  # 版本号自动取 src\app_config.py 的 APP_VERSION
        .\package.ps1 -Version 0.4.0    # 也可以显式指定

    产物：
        dist\MyTools\                    绿色版（整个目录拷走就能跑）
        dist\MyToolsSetup-<版本>.exe     安装包

    用户数据说明：配置文件不在安装目录里，而在 %LOCALAPPDATA%\MyTools
    （见 src/core/paths.py），所以卸载 / 重装都不会动用户的配置与任务流程。
#>
param([string]$Version = '')

# ⚠ 这里**必须是 Continue**，不能用 Stop：
#   python / PyInstaller / ISCC 这些原生命令把 INFO 日志写到 **stderr**，
#   而 PowerShell 会把"原生命令写了 stderr"当成 NativeCommandError ——
#   ErrorActionPreference=Stop 会让脚本**当场中止**（实测第 3 秒就退出，
#   报错长得像 PyInstaller 崩了，其实是 PowerShell 干的）。
#   所有原生调用后面都显式查 $LASTEXITCODE，该失败的照样会失败。
$ErrorActionPreference = 'Continue'
$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python   = Join-Path $Root '.venv\Scripts\python.exe'
$DistDir  = Join-Path $Root 'dist'
$Stage    = Join-Path $DistDir 'MyTools'
$WorkPath = Join-Path $Root 'build\pyinstaller'
$Spec     = Join-Path $Root 'packaging\mytools.spec'
$Icon     = Join-Path $Root 'assets\app.ico'
$Iss      = Join-Path $Root 'installer\mytools.iss'
# ⚠ $Setup 要到下面**版本号确定之后**才算 —— 文件名里有版本号，而这里 $Version
#   可能还是空串（不传 -Version 时是从 src\app_config.py 读的）。
#   曾经在这儿先算过一次，结果最后去检查 "MyToolsSetup-.exe"，
#   明明安装包已经产出却报「没生成安装包」并退出 1（2026-09-23）。

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "!! $text" -ForegroundColor Red; exit 1 }

# 版本号只有一个真源：src\app_config.py 里的 APP_VERSION（程序界面显示的也是它）。
# 以前这里默认写死 '0.1.0'，双击 package.bat 就会打出个名不副实的安装包 ——
# 实测踩到过「安装包 0.3.0 / 界面 v0.1.0」对不上，别再各写一份。
if (-not $Version) {
    $AppConfig = Join-Path $Root 'src\app_config.py'
    if (-not (Test-Path $AppConfig)) { Fail "找不到 $AppConfig，取不到版本号（可显式传 -Version）" }
    $m = Select-String -Path $AppConfig -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $m) { Fail 'src\app_config.py 里没读到 APP_VERSION，请显式传 -Version' }
    $Version = $m.Matches[0].Groups[1].Value
    Write-Host "   版本号取自 src\app_config.py：$Version" -ForegroundColor DarkGray
}

# 版本号定了，产物名才算得出来（见上面 $Setup 那段注释）
$Setup = Join-Path $DistDir "MyToolsSetup-$Version.exe"

Write-Host "`nMyTools 打包   版本 $Version" -ForegroundColor Green

# ---------------------------------------------------------------- 0. 前置
Step '检查环境'
if (-not (Test-Path $Python)) { Fail "找不到虚拟环境里的 python：$Python" }
if (-not (Test-Path $Spec))   { Fail "找不到打包配置：$Spec" }

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '   没装 PyInstaller，正在安装…' -ForegroundColor Yellow
    & $Python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { Fail 'PyInstaller 安装失败' }
}
Write-Host "   python : $Python"
Write-Host "   产物目录: $DistDir"

# ---------------------------------------------------------------- 1. 应用图标
if (-not (Test-Path $Icon)) {
    Step '生成应用图标'
    & $Python (Join-Path $Root 'tools\make_app_icon.py')
    if ($LASTEXITCODE -ne 0) { Fail '图标生成失败' }
}

# ---------------------------------------------------------------- 2. PyInstaller
# 交给 PyInstaller 自己删旧产物（--noconfirm）：它用 Python 删，
# 比在这个脚本里 Remove-Item -Recurse 上千个文件稳（那会触发批量删除确认）
Step 'PyInstaller 打包（onedir，约 1 分钟）'
& $Python -m PyInstaller $Spec --noconfirm --distpath $DistDir --workpath $WorkPath
if ($LASTEXITCODE -ne 0) { Fail 'PyInstaller 打包失败' }
if (-not (Test-Path (Join-Path $Stage 'MyTools.exe'))) { Fail "没生成 $Stage\MyTools.exe" }
Write-Host ('   绿色版：{0}（{1:N1} MB）' -f $Stage,
    ((Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB))

# ---------------------------------------------------------------- 2.5 构建自检
# 直接查产物里"有没有该有的东西"。插件式自动发现（pkgutil.walk_packages）
# 在打包后最容易静默失效 —— 界面能开、不报错，但功能列表是空的，跑到那时才发现太晚。
Step '构建自检（归档模块 + 数据）'
& $Python (Join-Path $Root 'packaging\check_build.py') $Stage
if ($LASTEXITCODE -ne 0) { Fail '构建自检不通过 —— 见上面列出的缺项' }

# ---------------------------------------------------------------- 3. Inno Setup
Step '查找 Inno Setup'
$Iscc = $null
foreach ($p in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'))) {
    if (Test-Path $p) { $Iscc = $p; break }
}
if (-not $Iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $Iscc = $cmd.Source }
}
if (-not $Iscc) {
    Write-Host '   没找到 Inno Setup —— 只出绿色版。' -ForegroundColor Yellow
    Write-Host '   想要安装包：winget install --id JRSoftware.InnoSetup -e' -ForegroundColor Yellow
    Write-Host "`n完成：$Stage" -ForegroundColor Green
    exit 0
}
Write-Host "   $Iscc"

Step '生成安装包'
& $Iscc /Qp "/DMyVersion=$Version" "/DMyStage=$Stage" "/DMyOutDir=$DistDir" $Iss
if ($LASTEXITCODE -ne 0) { Fail 'Inno Setup 编译失败' }
if (-not (Test-Path $Setup)) { Fail "没生成 $Setup" }

Write-Host "`n完成！" -ForegroundColor Green
Write-Host ('   安装包：{0}（{1:N1} MB）' -f $Setup, ((Get-Item $Setup).Length / 1MB))
Write-Host ('   绿色版：{0}' -f $Stage)
Write-Host ('   用户数据在：{0}\MyTools（卸载不会删）' -f $env:LOCALAPPDATA)
