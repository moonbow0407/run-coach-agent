<#
.SYNOPSIS
    Run Coach Agent 本地开发环境一键启动脚本。

.DESCRIPTION
    按固定顺序完成启动前的准备工作，然后为 API / Worker / 前端各自打开一个独立的
    PowerShell 窗口：

        1. 校验目录结构与 uv / npm 命令
        2. 准备 backend/.env（缺失时从仓库根目录 .env.example 复制）
        3. 检查 PostgreSQL / Redis 可达性，检查目标端口未被占用
        4. 同步后端依赖并按需安装前端依赖
        5. 执行 alembic upgrade head
        6. 启动服务并探测就绪状态

.PARAMETER Mode
    启动范围：all（默认，API + Worker + 前端）、backend（API + Worker）、
    api、worker、frontend。

.PARAMETER ApiHost
    uvicorn 监听地址，默认 127.0.0.1。同时作为前端 BACKEND_ORIGIN 的 host。

.PARAMETER ApiPort
    uvicorn 监听端口，默认 8000。同时作为前端 BACKEND_ORIGIN 的端口。

.PARAMETER WebPort
    Next.js dev server 端口，默认 3000。

.PARAMETER NoDeps
    跳过依赖同步（uv sync / npm ci）。

.PARAMETER NoMigrate
    跳过 alembic upgrade head。

.PARAMETER NoChecks
    跳过环境检查（PostgreSQL / Redis / 端口占用），直接进入依赖与启动阶段。

.PARAMETER Seed
    服务就绪后在当前窗口执行 scripts/seed_demo.py，写入演示数据并打印 user_id。

.EXAMPLE
    .\scripts\start.ps1
    启动 API、Worker 与前端。

.EXAMPLE
    .\scripts\start.ps1 -Mode backend -NoDeps -NoMigrate
    仅启动 API 与 Worker，跳过依赖同步与迁移。

.EXAMPLE
    .\scripts\start.ps1 -Seed
    全栈启动后写入演示数据。
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'backend', 'api', 'worker', 'frontend')]
    [string] $Mode = 'all',

    [string] $ApiHost = '127.0.0.1',
    [int] $ApiPort = 8000,
    [int] $WebPort = 3000,
    [int] $PostgresPort = 5432,
    [int] $RedisPort = 6379,

    [switch] $NoDeps,
    [switch] $NoMigrate,
    [switch] $NoChecks,
    [switch] $Seed
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 路径与常量

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$BackendDir  = Join-Path $RepoRoot 'backend'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$EnvFile     = Join-Path $BackendDir '.env'
$EnvTemplate = Join-Path $RepoRoot '.env.example'
$BackendOrigin = "http://${ApiHost}:${ApiPort}"

$StartApi      = $Mode -in @('all', 'backend', 'api')
$StartWorker   = $Mode -in @('all', 'backend', 'worker')
$StartFrontend = $Mode -in @('all', 'frontend')
$NeedBackend   = $StartApi -or $StartWorker

# ------------------------------------------------------------------ 输出辅助

function Write-Step {
    param([string] $Message)
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string] $Message)
    Write-Host "    [OK]   $Message" -ForegroundColor Green
}

function Write-WarnMsg {
    param([string] $Message)
    Write-Host "    [WARN] $Message" -ForegroundColor Yellow
}

function Write-Info {
    param([string] $Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Stop-Startup {
    param([string] $Message)
    Write-Host "`n[FAIL] $Message" -ForegroundColor Red
    Write-Host '启动中止。' -ForegroundColor DarkGray
    exit 1
}

# ------------------------------------------------------------------- 环境校验

function Assert-Command {
    param(
        [string] $Name,
        [string] $InstallHint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Stop-Startup "未找到命令 '$Name'。$InstallHint"
    }
    Write-Ok "命令可用：$Name"
}

function Test-TcpPort {
    param(
        [string] $TargetHost = '127.0.0.1',
        [int] $Port,
        [int] $TimeoutMs = 800
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.ConnectAsync($TargetHost, $Port)
        if (-not $connect.Wait($TimeoutMs)) { return $false }
        if ($connect.IsFaulted -or -not $client.Connected) { return $false }
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-PortOwner {
    param([int] $Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) { return "$($proc.ProcessName) (PID $($proc.Id))" }
    return "PID $($conn.OwningProcess)"
}

function Assert-PortFree {
    param(
        [int] $Port,
        [string] $ServiceName
    )
    if (Test-TcpPort -Port $Port) {
        $owner = Get-PortOwner -Port $Port
        Stop-Startup "端口 $Port 已被占用，$ServiceName 无法启动（占用者：$owner）。请先关闭已有实例，或用 -ApiPort / -WebPort 指定其他端口。"
    }
    Write-Ok "端口 $Port 空闲（$ServiceName）"
}

# ---------------------------------------------------------------------- .env

function Read-EnvFile {
    param([string] $Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -le 0) { continue }
        $values[$trimmed.Substring(0, $separator).Trim()] = $trimmed.Substring($separator + 1).Trim()
    }
    return $values
}

function Initialize-EnvFile {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        if (-not (Test-Path -LiteralPath $EnvTemplate)) {
            Stop-Startup "缺少 $EnvFile，且未找到模板 $EnvTemplate。"
        }
        Copy-Item -LiteralPath $EnvTemplate -Destination $EnvFile
        Write-WarnMsg "已从 .env.example 生成 $([System.IO.Path]::GetFileName($EnvFile))"
        Stop-Startup "请先编辑 backend\.env：替换 DATABASE_URL 中的 <密码>，并填写至少 32 字符的 JWT_SECRET，然后重新运行本脚本。"
    }

    $env = Read-EnvFile -Path $EnvFile

    # 一次性收集全部配置问题，避免用户逐项试错；只输出问题项名称，不回显任何凭据内容。
    $problems = @()

    $databaseUrl = if ($env.ContainsKey('DATABASE_URL')) { $env['DATABASE_URL'] } else { '' }
    if ([string]::IsNullOrWhiteSpace($databaseUrl)) {
        $problems += 'DATABASE_URL 未配置'
    }
    elseif ($databaseUrl -match '[<>]') {
        $problems += 'DATABASE_URL 仍包含占位符（如 <密码>），需替换为真实连接串'
    }

    $jwtSecret = if ($env.ContainsKey('JWT_SECRET')) { $env['JWT_SECRET'] } else { '' }
    if ($jwtSecret.Length -lt 32) {
        $problems += 'JWT_SECRET 为空或少于 32 个字符（应用不会以弱密钥启动）'
    }

    if ($problems.Count -gt 0) {
        Write-Host '    backend\.env 存在会阻止启动的配置问题：' -ForegroundColor Red
        foreach ($problem in $problems) {
            Write-Host "      - $problem" -ForegroundColor Red
        }
        Write-Info '可参考仓库根目录 .env.example 补齐缺失项。'
        Stop-Startup '请修正 backend\.env 后重新运行本脚本。'
    }
    Write-Ok 'DATABASE_URL 与 JWT_SECRET 校验通过'

    if (-not $env.ContainsKey('REDIS_URL') -or [string]::IsNullOrWhiteSpace($env['REDIS_URL'])) {
        Write-WarnMsg 'REDIS_URL 未配置，Worker 将无法连接队列。'
    }
    if ([string]::IsNullOrWhiteSpace($env['LLM_API_KEY'])) {
        Write-WarnMsg 'LLM_API_KEY 未配置：真实对话与 Memory Projection 不可用（脚本化场景测试不受影响）。'
    }
}

# --------------------------------------------------------------- 依赖与迁移

function Invoke-InDirectory {
    param(
        [string] $Directory,
        [string] $Executable,
        [string[]] $Arguments,
        [string] $Label
    )
    Push-Location -LiteralPath $Directory
    try {
        & $Executable @Arguments
        if ($LASTEXITCODE -ne 0) {
            Stop-Startup "$Label 失败（退出码 $LASTEXITCODE）。"
        }
    }
    finally {
        Pop-Location
    }
    Write-Ok $Label
}

function Initialize-BackendDependencies {
    if ($NoDeps) {
        Write-Info '已跳过后端依赖同步（-NoDeps）'
        return
    }
    Write-Step '同步后端依赖（uv sync --extra dev）'
    Invoke-InDirectory -Directory $BackendDir -Executable 'uv' `
        -Arguments @('sync', '--extra', 'dev') -Label '后端依赖同步'
}

function Initialize-DatabaseSchema {
    if ($NoMigrate) {
        Write-Info '已跳过数据库迁移（-NoMigrate）'
        return
    }
    Write-Step '执行数据库迁移（alembic upgrade head）'
    Push-Location -LiteralPath $BackendDir
    try {
        & uv run alembic upgrade head
        $migrateExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($migrateExit -ne 0) {
        Stop-Startup "数据库迁移失败（退出码 $migrateExit）。请确认 DATABASE_URL 正确、run_coach 数据库已创建且该实例已安装 pgvector 扩展。"
    }
    Write-Ok '数据库迁移完成'
}

function Initialize-FrontendDependencies {
    if (-not $StartFrontend) { return }
    if ($NoDeps) {
        Write-Info '已跳过前端依赖检查（-NoDeps）'
        return
    }
    $nodeModules = Join-Path $FrontendDir 'node_modules'
    if (Test-Path -LiteralPath $nodeModules) {
        Write-Ok '前端依赖已存在，跳过安装'
        return
    }
    Write-Step '安装前端依赖（npm ci）'
    Invoke-InDirectory -Directory $FrontendDir -Executable 'npm' -Arguments @('ci') -Label '前端依赖安装'
}

# --------------------------------------------------------------- 进程与就绪

function Start-ServiceWindow {
    param(
        [string] $Name,
        [string] $WorkDir,
        [string] $Command
    )
    $inner = "`$Host.UI.RawUI.WindowTitle = 'run-coach :: $Name'; Set-Location -LiteralPath '$WorkDir'; $Command"
    $proc = Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $inner) `
        -WorkingDirectory $WorkDir -PassThru
    Write-Ok "$Name 已在新窗口启动（PID $($proc.Id)）"
    return $proc.Id
}

function Wait-ForService {
    param(
        [int] $Port,
        [string] $HealthPath,
        [int] $TimeoutSec,
        [string] $Label
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $nextReportAt = 0
    while ((Get-Date) -lt $deadline) {
        $ready = $false
        if ($HealthPath) {
            try {
                Invoke-RestMethod -Uri "http://127.0.0.1:$Port$HealthPath" -TimeoutSec 3 | Out-Null
                $ready = $true
            }
            catch {
                $ready = $false
            }
        }
        else {
            $ready = Test-TcpPort -Port $Port
        }
        if ($ready) {
            Write-Ok "$Label 已就绪"
            return $true
        }

        $elapsed = [int]((Get-Date) - ($deadline.AddSeconds(-$TimeoutSec))).TotalSeconds
        if ($elapsed -ge $nextReportAt) {
            Write-Info "等待 $Label（已 $elapsed 秒）"
            $nextReportAt = $elapsed + 5
        }
        Start-Sleep -Milliseconds 500
    }
    Write-WarnMsg "$Label 在 $TimeoutSec 秒内未就绪，请检查对应窗口的输出"
    return $false
}

# ================================================================== 主流程

Write-Host ''
Write-Host '  Run Coach Agent — 本地开发环境启动' -ForegroundColor White
Write-Host "  模式: $Mode    后端: ${ApiHost}:${ApiPort}    前端端口: $WebPort" -ForegroundColor DarkGray

Write-Step '校验目录结构'
foreach ($path in @($BackendDir, $FrontendDir)) {
    if (-not (Test-Path -LiteralPath $path)) {
        Stop-Startup "目录不存在：$path（请在仓库根目录运行本脚本）"
    }
}
Write-Ok "仓库根目录：$RepoRoot"

Write-Step '校验命令'
Assert-Command -Name 'uv' -InstallHint '请先安装 uv：https://docs.astral.sh/uv/'
if ($StartFrontend) {
    Assert-Command -Name 'npm' -InstallHint '请先安装 Node.js 20+（前端需要 npm）。'
}

if ($NeedBackend) {
    Write-Step '准备后端配置'
    Initialize-EnvFile

    if (-not $NoChecks) {
        Write-Step '检查基础设施与端口'
        if (Test-TcpPort -Port $PostgresPort) {
            Write-Ok "PostgreSQL 可达（端口 $PostgresPort）"
        }
        else {
            Stop-Startup "无法连接 PostgreSQL（端口 $PostgresPort）。请确认本地 PostgreSQL 已启动，或用 -PostgresPort 指定端口。"
        }

        if (Test-TcpPort -Port $RedisPort) {
            Write-Ok "Redis 可达（端口 $RedisPort）"
        }
        else {
            Write-WarnMsg "无法连接 Redis（端口 $RedisPort）。API 仍可提交 canonical state，但 Worker 无法消费任务，请尽快启动 Redis。"
        }
    }
}

if ($StartApi) { Assert-PortFree -Port $ApiPort -ServiceName 'API' }
if ($StartFrontend) { Assert-PortFree -Port $WebPort -ServiceName '前端' }

if ($NeedBackend) {
    Initialize-BackendDependencies
    Initialize-DatabaseSchema
}
Initialize-FrontendDependencies

Write-Step '启动服务'
$pids = @{}

if ($StartApi) {
    $pids['API'] = Start-ServiceWindow -Name 'API' -WorkDir $BackendDir `
        -Command "uv run uvicorn app.main:app --reload --host $ApiHost --port $ApiPort"
    $apiReady = Wait-ForService -Port $ApiPort -HealthPath '/health' -TimeoutSec 60 -Label 'API'
    if ($apiReady) {
        Write-Info "健康检查：http://${ApiHost}:${ApiPort}/health"
    }
}

if ($StartWorker) {
    $pids['Worker'] = Start-ServiceWindow -Name 'Worker' -WorkDir $BackendDir `
        -Command 'uv run arq app.workers.arq_worker.WorkerSettings'
}

if ($StartFrontend) {
    $devCommand = if ($WebPort -eq 3000) {
        "`$env:BACKEND_ORIGIN = '$BackendOrigin'; npm run dev"
    }
    else {
        "`$env:BACKEND_ORIGIN = '$BackendOrigin'; npm run dev -- --port $WebPort"
    }
    $pids['Frontend'] = Start-ServiceWindow -Name 'Frontend' -WorkDir $FrontendDir -Command $devCommand
    Wait-ForService -Port $WebPort -TimeoutSec 90 -Label '前端' | Out-Null
}

if ($Seed) {
    Write-Step '写入演示数据（scripts/seed_demo.py）'
    Invoke-InDirectory -Directory $BackendDir -Executable 'uv' `
        -Arguments @('run', 'python', 'scripts/seed_demo.py') -Label '演示数据写入'
}

Write-Host ''
Write-Host '  启动完成' -ForegroundColor Green
Write-Host '  --------------------------------------------------------------' -ForegroundColor DarkGray
if ($StartApi) { Write-Host ("  API       http://{0}:{1}/health        PID {2}" -f $ApiHost, $ApiPort, $pids['API']) }
if ($StartWorker) { Write-Host ("  Worker    ARQ app.workers.arq_worker  PID {0}" -f $pids['Worker']) }
if ($StartFrontend) { Write-Host ("  Frontend  http://localhost:{0}         PID {1}" -f $WebPort, $pids['Frontend']) }
Write-Host '  --------------------------------------------------------------' -ForegroundColor DarkGray
Write-Host ''
Write-Info '每个服务运行在独立窗口中，关闭对应窗口即可停止该服务。'
if ($StartFrontend) {
    Write-Info "打开 http://localhost:$WebPort 后，需要粘贴访问令牌："
    Write-Info "  在 backend/ 执行: uv run python scripts/issue_token.py <user_id>"
    if (-not $Seed) {
        Write-Info '  尚无演示数据时可先执行: uv run python scripts/seed_demo.py（或用 -Seed 参数启动）'
    }
}
Write-Host ''
