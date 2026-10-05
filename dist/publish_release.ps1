# ============================================================================
#  发布新版本 -- 把打包好的安装包传到 GitHub Releases
#
#  ## 为什么需要它
#
#  「检查更新」是从 **GitHub Releases** 读版本的（见 src/core/updater.py）。
#  光提交代码不会让用户收到更新 -- 必须**发一个 Release**、
#  并把安装包传上去。
#
#  ## 用法
#
#      .\publish_release.ps1                       # 用 app_config 里的版本号
#      .\publish_release.ps1 -Notes "修了 xxx"      # 自定义更新说明
#      .\publish_release.ps1 -SkipBuild             # 复用现有安装包
#
#  ## 一次性准备：GitHub Token
#
#  去 https://github.com/settings/tokens 建一个 **classic** token，
#  勾上 repo 权限，然后：
#
#      setx GITHUB_TOKEN "ghp_xxxxxxxxxxxx"
#
#  （设完要**重开终端**才生效。也可以临时：$env:GITHUB_TOKEN="..."）
#
#  ⚠ token 是**密码级**的东西 -- 本脚本只从环境变量读，不落盘、不回显。
# ============================================================================
param(
    [string]$Version = '',
    [string]$Notes = '',
    [switch]$SkipBuild
)

# ⚠ 必须是 Continue：python / ISCC 把 INFO 日志写到 stderr，
#   设成 Stop 会把正常日志当成致命错误。
$ErrorActionPreference = 'Continue'

$DistDir = $PSScriptRoot
$Root = Split-Path $DistDir -Parent
$Repo = 'Hub-yys/MyTools'

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "`n[x] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- 版本号
Step '确定版本号'
if (-not $Version) {
    # 从 app_config.py 读 -- 唯一真源
    # （别再手写一份：项目踩过「安装包 0.3.0 / 界面 0.1.0 对不上」）
    $cfg = Join-Path $Root 'src\app_config.py'
    if (-not (Test-Path $cfg)) { Fail "找不到 $cfg" }
    $line = Select-String -Path $cfg -Pattern '^APP_VERSION\s*=\s*"([^"]+)"' |
            Select-Object -First 1
    if (-not $line) { Fail '从 app_config.py 里读不到 APP_VERSION' }
    $Version = $line.Matches[0].Groups[1].Value
    Write-Host "   从 app_config.py 读到：$Version"
} else {
    Write-Host "   命令行指定：$Version"
}
$Tag = "v$Version"
# 安装包名要和 installer\mytools.iss 的 OutputBaseFilename 对得上
$Setup = Join-Path $DistDir "WutheringWavesToolsSetup-$Version.exe"

# ---------------------------------------------------------------- token
Step '检查 GitHub Token'
$Token = $env:GITHUB_TOKEN
if (-not $Token) {
    Write-Host '   没有 GITHUB_TOKEN 环境变量。' -ForegroundColor Yellow
    Write-Host '   去 https://github.com/settings/tokens 建一个 classic token（勾 repo），然后：'
    Write-Host '       setx GITHUB_TOKEN "ghp_xxxxxxxxxxxx"'
    Write-Host '   设完**重开终端**再跑本脚本。'
    exit 1
}
Write-Host "   token 长度 $($Token.Length)（不回显内容）"

# ---------------------------------------------------------------- 打包
if (-not $SkipBuild) {
    Step '打包安装包'
    $builder = Join-Path $DistDir 'build_installer.ps1'
    & $builder -Mode full -Force
    if ($LASTEXITCODE -ne 0) { Fail "打包失败（退出码 $LASTEXITCODE）" }
} else {
    Step '跳过打包（复用现有安装包）'
}

if (-not (Test-Path $Setup)) {
    Fail "找不到安装包：$Setup`n   （先跑 .\build_installer.ps1 -Mode full）"
}
$SizeMB = (Get-Item $Setup).Length / 1MB
Write-Host ("   安装包 {0}（{1:N1} MB）" -f (Split-Path $Setup -Leaf), $SizeMB)

# ---------------------------------------------------------------- 发 Release
Step "创建 Release $Tag"

$Headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
    'User-Agent'           = 'MyTools-publisher'
}

if (-not $Notes) {
    $Notes = "鸣潮工具箱 $Version`n`n（自动发布，未填写更新说明）"
}

# ⚠ 用 ConvertTo-Json 别手拼字符串 -- 说明里有引号/换行会拼坏
$body = @{
    tag_name   = $Tag
    name       = "鸣潮工具箱 $Version"
    body       = $Notes
    draft      = $false
    prerelease = $false
} | ConvertTo-Json -Depth 5

try {
    $rel = Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$Repo/releases" `
        -Headers $Headers -Body $body -ContentType 'application/json'
} catch {
    $msg = $_.Exception.Message
    if ($msg -match '422') {
        Fail "Release $Tag 可能已经存在了。`n   要重发就先在 GitHub 上删掉旧的，或换个版本号。"
    }
    Fail "创建 Release 失败：$msg"
}
Write-Host "   已创建：$($rel.html_url)"

# ---------------------------------------------------------------- 传安装包
Step '上传安装包'
$leaf = Split-Path $Setup -Leaf
$uploadUrl = ($rel.upload_url -replace '\{.*\}', '') +
             "?name=$([uri]::EscapeDataString($leaf))"

try {
    # ⚠ 大文件要设长超时（默认 100 秒可能不够传完）
    $up = Invoke-RestMethod -Method Post -Uri $uploadUrl -Headers $Headers `
        -InFile $Setup -ContentType 'application/octet-stream' `
        -TimeoutSec 600
} catch {
    Fail "上传失败：$($_.Exception.Message)"
}
Write-Host ("   已上传：{0}（{1:N1} MB）" -f $up.name, ($up.size / 1MB))

# ---------------------------------------------------------------- 完事
Write-Host "`n[OK] 发布完成！" -ForegroundColor Green
Write-Host "   Release  ：$($rel.html_url)"
Write-Host "   下载地址 ：$($up.browser_download_url)"
Write-Host ''
Write-Host "   用户端「配置 -> 检查更新」现在应该能看到 $Tag 了。" -ForegroundColor DarkGray
Write-Host '   ⚠ 刚发完可能查不到，等 1~2 分钟（GitHub 的 CDN 有缓存）。' -ForegroundColor DarkGray
