<#
    dist 里的「一键打包成 .exe 安装包」脚本。

    为什么放在 dist：产出物就在这个目录，双击入口贴着产出放，找起来顺手。

    ⚠ 它**必须在项目里运行**（要用 .venv、src\、packaging\、installer\）——
      单独把 dist 拷到别的机器是跑不起来的。要给别人，请给整个项目目录。

    用法（双击 一键打包安装包.bat 会问你要哪种）：
        .\build_installer.ps1                  # 交互式选单
        .\build_installer.ps1 -Mode full       # 完整：源码 → 绿色版 → 安装包（约 2 分钟）
        .\build_installer.ps1 -Mode installer  # 只重出安装包（复用现有绿色版，约 1 分钟）
        .\build_installer.ps1 -Mode installer -Force   # 跳过「绿色版比源码旧」的确认

    两种模式的差别：
        full      交给根目录的 package.ps1：PyInstaller 重新出绿色版，再让 Inno 打包。
                  改了 main.py / src\ 下的代码 → 用这个。
        installer 只跑 Inno Setup，把 dist 里**现有的**绿色版打成安装包。
                  只改了 installer\*.iss（应用名、快捷方式、安装目录…）→ 用这个，快得多。
                  ★ 会先检查「绿色版是不是比源码旧」，旧的会拦下来问你 ——
                    否则容易打出一个不含最新代码的安装包（2026-09-23 真踩过）。
#>
param(
    [string]$Mode = '',
    [switch]$Force
)

# ⚠ 必须是 Continue：python / PyInstaller / ISCC 把 INFO 日志写到 stderr，
#   PowerShell 会判成 NativeCommandError，'Stop' 会让脚本当场中止（看着像程序崩了）。
$ErrorActionPreference = 'Continue'

$DistDir  = $PSScriptRoot
$Root     = Split-Path -Parent $DistDir
$Stage    = Join-Path $DistDir 'WutheringWavesTools'
$StageExe = Join-Path $Stage 'WutheringWavesTools.exe'
$Iss      = Join-Path $Root 'installer\mytools.iss'
$Config   = Join-Path $Root 'src\app_config.py'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "!! $text" -ForegroundColor Red; exit 1 }

Write-Host "鸣潮工具箱（WutheringWavesTools）— 安装包制作" -ForegroundColor Green
Write-Host "  项目根  : $Root"
Write-Host "  产物目录: $DistDir"

# ---------------------------------------------------------------- 0. 前置
if (-not (Test-Path $Config)) {
    Fail "这不像是在项目里跑（找不到 $Config）。`n   本脚本要跟源码放在一起才有意义，单独拷 dist 目录没用。"
}
if (-not (Test-Path $Iss)) { Fail "找不到 Inno 脚本：$Iss" }

# ------------------------------------------------- 1. 版本号（唯一真源）
$m = Select-String -Path $Config -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $m) { Fail 'src\app_config.py 里没读到 APP_VERSION' }
$Version = $m.Matches[0].Groups[1].Value
# 含版本号的路径要在版本号确定之后才算（否则会拼出 AppSetup-.exe，2026-09-23 踩过）
$Setup = Join-Path $DistDir "WutheringWavesToolsSetup-$Version.exe"
Write-Host "  版本号  : $Version（取自 src\app_config.py）" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 2. 选模式
$Mode = $Mode.Trim().ToLower()
if ($Mode -and ($Mode -ne 'full') -and ($Mode -ne 'installer')) {
    Fail "-Mode 只能是 full 或 installer（收到 '$Mode'）"
}

if (-not $Mode) {
    Write-Host ""
    if (Test-Path $StageExe) {
        $ageMin = [math]::Round(((Get-Date) - (Get-Item $StageExe).LastWriteTime).TotalMinutes)
        Write-Host ("  现有绿色版：{0} 分钟前出的" -f $ageMin)
    } else {
        Write-Host "  现有绿色版：没有（dist\WutheringWavesTools 不存在）" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  1 = 完整打包（源码 → 绿色版 → 安装包）    约 2 分钟"
    Write-Host "  2 = 只重出安装包（复用上面的绿色版）      约 1 分钟"
    Write-Host "  回车 = 取消"
    Write-Host ""
    # Read-Host 在非交互环境（CI / 被别的脚本调起）会返回 $null，
    # 直接 $null.Trim() 会抛异常、把整段判断跳过 —— 统一先归一成 ''。
    $choice = Read-Host "你的选择"
    if (-not $choice) { $choice = '' }
    $choice = $choice.Trim()
    if ($choice -eq '1') { $Mode = 'full' }
    elseif ($choice -eq '2') { $Mode = 'installer' }
    else { Write-Host "已取消。"; exit 0 }
}

# ------------------------------------------------------- 3a. 完整打包
if ($Mode -eq 'full') {
    Step '完整打包（交给项目根的 package.ps1）'
    & (Join-Path $Root 'package.ps1') -Version $Version
    if ($LASTEXITCODE -ne 0) { Fail "package.ps1 失败（退出码 $LASTEXITCODE）" }
    if (-not (Test-Path $Setup)) { Fail "没生成 $Setup" }
    Write-Host "`n完成！安装包：$Setup" -ForegroundColor Green
    exit 0
}

# -------------------------------------------------- 3b. 只重出安装包
Step '只重出安装包（复用 dist 里现有的绿色版）'

if (-not (Test-Path $StageExe)) {
    Fail "没有现成的绿色版：$StageExe`n   先做一次完整打包（选 1，或双击项目根的 package.bat）。"
}

# 3b-1 陈旧检查：绿色版比源码旧 → 打出来的安装包不含最新代码
$stageTime = (Get-Item $StageExe).LastWriteTime
$single = @((Join-Path $Root 'main.py'), (Join-Path $Root 'packaging\mytools.spec'))
$dirs = @(
    (Join-Path $Root 'src'),
    (Join-Path $Root 'assets'),
    (Join-Path $Root 'data'),
    (Join-Path $Root 'vendor\okww')
)
$newer = New-Object System.Collections.ArrayList
foreach ($f in $single) {
    if ((Test-Path $f) -and ((Get-Item $f).LastWriteTime -gt $stageTime)) {
        [void]$newer.Add((Get-Item $f))
    }
}
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { continue }
    foreach ($f in (Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue)) {
        if ($f.FullName -like '*__pycache__*') { continue }
        if ($f.LastWriteTime -gt $stageTime) { [void]$newer.Add($f) }
    }
}
if ($newer.Count -gt 0) {
    Write-Host ""
    Write-Host ("!! 绿色版已落后于源码：{0} 个文件比它新" -f $newer.Count) -ForegroundColor Yellow
    foreach ($f in ($newer | Sort-Object LastWriteTime -Descending | Select-Object -First 5)) {
        $rel = $f.FullName.Substring($Root.Length + 1)
        Write-Host ("     {0}  {1}" -f $f.LastWriteTime.ToString('MM-dd HH:mm'), $rel)
    }
    if ($newer.Count -gt 5) { Write-Host ("     …另有 {0} 个" -f ($newer.Count - 5)) }
    Write-Host "   这样打出来的安装包**不含最新代码**；只有改动 installer\*.iss 时才该走这条路。" -ForegroundColor Yellow
    if (-not $Force) {
        $answer = Read-Host "   仍然继续？[y/N]"
        if (-not $answer) { $answer = '' }   # 非交互环境会给 $null；取不到答复就按"否"
        if (@('y', 'yes') -notcontains $answer.Trim().ToLower()) {
            Write-Host "已取消 —— 建议改成完整打包（选 1）。"
            # 退出码 2 = "按规则拒绝了这次操作"，跟 0=成功 / 1=失败 区分开 ——
            # 否则以后被自动化调起时，会把"什么都没产出"当成成功。
            exit 2
        }
    }
} else {
    Write-Host "   陈旧检查通过：绿色版不比源码旧" -ForegroundColor DarkGray
}

# 3b-2 找 Inno Setup
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
    Fail "没找到 Inno Setup（ISCC.exe）。`n   安装：winget install --id JRSoftware.InnoSetup -e"
}
Write-Host "   $Iscc"

# 3b-3 编译
Step '生成安装包'
& $Iscc /Qp "/DMyVersion=$Version" "/DMyStage=$Stage" "/DMyOutDir=$DistDir" $Iss
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup 编译失败（退出码 $LASTEXITCODE）" }
if (-not (Test-Path $Setup)) { Fail "没生成 $Setup" }

Write-Host "`n完成！" -ForegroundColor Green
Write-Host ('   安装包  ：{0}（{1:N1} MB）' -f $Setup, ((Get-Item $Setup).Length / 1MB))
Write-Host ('   用的绿色版：{0}（{1}）' -f $Stage, $stageTime.ToString('MM-dd HH:mm'))
