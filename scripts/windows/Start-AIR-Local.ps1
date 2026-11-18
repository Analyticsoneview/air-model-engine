[CmdletBinding()]
param(
    [switch]$SkipAdminBootstrap,
    [switch]$DoNotOpenBrowser
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
Push-Location $Root

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments, [string]$Failure = "Docker command failed.")
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Failure (exit code $LASTEXITCODE)." }
}

function Get-ServiceContainerId {
    param([string]$Service)
    $id = & docker compose -f .\compose.local.yml ps -q $Service
    if ($LASTEXITCODE -ne 0) { throw "Could not locate Compose service '$Service'." }
    $value = [string]($id | Select-Object -First 1)
    return $value.Trim()
}

function Get-ContainerHealth {
    param([string]$ContainerId)
    if ([string]::IsNullOrWhiteSpace($ContainerId)) { return "MISSING" }
    $raw = & docker inspect $ContainerId
    if ($LASTEXITCODE -ne 0) { return "MISSING" }
    $item = ($raw | ConvertFrom-Json | Select-Object -First 1)
    if ($item.State.Health) { return [string]$item.State.Health.Status }
    return [string]$item.State.Status
}

function Wait-ServiceHealthy {
    param([string]$Service, [int]$TimeoutSeconds = 300)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $id = Get-ServiceContainerId -Service $Service
        $health = Get-ContainerHealth -ContainerId $id
        if ($health -eq "healthy") {
            Write-Host "PASS $Service is healthy." -ForegroundColor Green
            return
        }
        if ($health -eq "unhealthy" -or $health -eq "exited" -or $health -eq "dead") {
            & docker compose -f .\compose.local.yml logs --tail 80 $Service
            throw "Service '$Service' entered state '$health'."
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    & docker compose -f .\compose.local.yml ps
    & docker compose -f .\compose.local.yml logs --tail 100 $Service
    throw "Timed out waiting for '$Service' to become healthy."
}

try {
    Write-Host ""
    Write-Host "AIR LOCAL START - Windows / Docker Desktop / Compose only" -ForegroundColor Cyan
    Write-Host "Project: $Root"

    if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is missing. Start Docker Desktop and retry."
    }
    Invoke-Docker -Arguments @("info") -Failure "Docker Desktop Linux engine is not available."
    Invoke-Docker -Arguments @("compose", "version") -Failure "Docker Compose v2 is unavailable."

    foreach ($file in @(
        ".air-secrets\postgres_password",
        ".air-secrets\redis_password",
        ".air-secrets\database_url",
        ".air-secrets\redis_url",
        ".air-secrets\jwt_secret",
        ".air-secrets\credential_key",
        ".air-secrets\admin_api_key",
        ".air-secrets\admin_mfa_key"
    )) {
        $path = Join-Path $Root $file
        if (!(Test-Path -LiteralPath $path) -or (Get-Item -LiteralPath $path).Length -eq 0) {
            throw "Required existing secret is missing or empty: $file. Restore the original local secret; do not generate a replacement for a running database."
        }
    }

    $pgId = Get-ServiceContainerId -Service "postgres"
    $redisId = Get-ServiceContainerId -Service "redis"
    if (!$pgId -or !$redisId) {
        throw "Existing PostgreSQL and Redis containers were not found in this Compose project. No containers were changed."
    }
    if ((Get-ContainerHealth $pgId) -ne "healthy") {
        throw "Existing PostgreSQL is not healthy. No containers were changed."
    }
    if ((Get-ContainerHealth $redisId) -ne "healthy") {
        throw "Existing Redis is not healthy. No containers were changed."
    }

    # Back up and validate PostgreSQL before the API container applies migrations.
    $backupDirectory = Join-Path $env:USERPROFILE "AIR-backups"
    New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $containerDump = "/tmp/air-before-local-runtime-$stamp.dump"
    $backupFile = Join-Path $backupDirectory "air-postgres-before-local-runtime-$stamp.dump"

    Write-Host ""
    Write-Host "Creating and verifying PostgreSQL backup..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("exec", $pgId, "pg_dump", "-U", "air", "-d", "air", "-Fc", "-f", $containerDump) -Failure "PostgreSQL backup creation failed."
    & docker exec $pgId pg_restore --list $containerDump | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup validation failed." }
    $sourceDump = $pgId + ":" + $containerDump
    Invoke-Docker -Arguments @("cp", $sourceDump, $backupFile) -Failure "Could not copy PostgreSQL backup to Windows."
    $backup = Get-Item -LiteralPath $backupFile
    if ($backup.Length -lt 1) { throw "PostgreSQL backup file is empty." }

    # Validate the Windows copy too; a successful container-side dump is not enough
    # if the copy is truncated or corrupted.
    $verificationDump = "/tmp/air-backup-copy-verify-$stamp.dump"
    $verificationTarget = $pgId + ":" + $verificationDump
    Invoke-Docker -Arguments @("cp", $backupFile, $verificationTarget) -Failure "Could not stage the Windows backup for validation."
    & docker exec $pgId pg_restore --list $verificationDump | Out-Null
    $restoreListExitCode = $LASTEXITCODE
    & docker exec $pgId rm -f $verificationDump | Out-Null
    if ($restoreListExitCode -ne 0) { throw "Copied PostgreSQL backup failed pg_restore validation." }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupFile).Hash
    ($hash + "  " + $backup.Name) | Set-Content -LiteralPath ($backupFile + ".sha256") -Encoding ascii
    Write-Host "PASS PostgreSQL backup: $backupFile ($($backup.Length) bytes)" -ForegroundColor Green
    Write-Host "SHA256: $hash"
    & docker exec $pgId rm -f $containerDump | Out-Null

    # Preserve existing database/encryption secrets. Only add the missing RabbitMQ secret
    # and the optional Telegram token file when no old RabbitMQ data volume exists.
    if (!(Test-Path -LiteralPath ".air-secrets\rabbitmq_password")) {
        & docker volume inspect air-model-engine_rabbitmq_data *> $null
        if ($LASTEXITCODE -eq 0) {
            throw "RabbitMQ data volume already exists but its password file is missing. Restore that original password; do not generate a new one."
        }
    }
    if (!(Test-Path -LiteralPath ".air-local.env")) {
        @(
            "AIR_OPERATOR_CUSTOMER_IDS=",
            "AIR_MARKET_DATA_POLL_SECONDS=3",
            "AIR_SMTP_PORT=587"
        ) | Set-Content -LiteralPath ".air-local.env" -Encoding ascii
    }

    if (!(Test-Path -LiteralPath ".air-secrets\rabbitmq_password") -or !(Test-Path -LiteralPath ".air-secrets\telegram_bot_token")) {
        $python = Get-Command python -ErrorAction SilentlyContinue
        $pythonPrefix = @()
        if ($python) {
            $versionText = & $python.Source --version 2>&1
            if ($versionText -notmatch "Python 3\.(1[0-9]|[2-9][0-9])") { $python = $null }
        }
        if (!$python) {
            $python = Get-Command py -ErrorAction SilentlyContinue
            if ($python) { $pythonPrefix = @("-3") }
        }
        if (!$python) { throw "Python 3.10+ or the Python Launcher is required to generate the missing local RabbitMQ secret." }
        & $python.Source @pythonPrefix .\scripts\generate_local_secrets.py .air-secrets
        if ($LASTEXITCODE -ne 0) { throw "Local secret preparation failed." }
    }

    Write-Host ""
    Write-Host "Validating local Compose configuration..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("compose", "-f", ".\compose.local.yml", "config", "--quiet") -Failure "Compose configuration validation failed."
    $services = & docker compose -f .\compose.local.yml config --services
    if ($LASTEXITCODE -ne 0) { throw "Could not enumerate Compose services." }
    foreach ($required in @("postgres", "redis", "rabbitmq", "air-api", "air-workflow-worker", "air-pwa")) {
        if ($services -notcontains $required) { throw "Updated Compose configuration is missing required service '$required'." }
    }

    Write-Host ""
    Write-Host "Starting RabbitMQ only; PostgreSQL and Redis are not targeted..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("compose", "-f", ".\compose.local.yml", "up", "-d", "rabbitmq") -Failure "RabbitMQ startup failed."
    Wait-ServiceHealthy -Service "rabbitmq" -TimeoutSeconds 180

    Write-Host ""
    Write-Host "Building and starting FastAPI from the updated repository..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("compose", "-f", ".\compose.local.yml", "up", "-d", "--build", "--no-deps", "air-api") -Failure "FastAPI build/start failed."
    Wait-ServiceHealthy -Service "air-api" -TimeoutSeconds 600

    Write-Host ""
    Write-Host "Building and starting the workflow worker..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("compose", "-f", ".\compose.local.yml", "up", "-d", "--build", "--no-deps", "air-workflow-worker") -Failure "Workflow worker build/start failed."
    Wait-ServiceHealthy -Service "air-workflow-worker" -TimeoutSeconds 300

    Write-Host ""
    Write-Host "Rebuilding customer and administrator web screens..." -ForegroundColor Cyan
    Invoke-Docker -Arguments @("compose", "-f", ".\compose.local.yml", "up", "-d", "--build", "--no-deps", "air-pwa") -Failure "AIR PWA build/start failed."
    Wait-ServiceHealthy -Service "air-pwa" -TimeoutSeconds 1200

    Write-Host ""
    Write-Host "Checking FastAPI routes and dependencies..." -ForegroundColor Cyan
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 10
    if ($health.status -ne "ok" -or $health.dependencies.postgresql.status -ne "ok" -or $health.dependencies.redis.status -ne "ok") {
        throw "FastAPI health/dependency check did not pass."
    }
    $openapi = Invoke-RestMethod -Uri "http://localhost:8000/openapi.json" -TimeoutSec 20
    $apiPaths = @($openapi.paths.PSObject.Properties.Name)
    foreach ($route in @("/ready", "/api/v1/admin/auth/login", "/api/v1/backtest/strategies")) {
        if ($apiPaths -notcontains $route) { throw "Expected API route is missing: $route" }
    }
    $null = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/health" -TimeoutSec 10
    $adminPage = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/admin/" -TimeoutSec 20
    if ($adminPage.StatusCode -ne 200 -or $adminPage.Content -notmatch '<base href="/admin/">') {
        throw "Administrator web console did not load from /admin/."
    }

    Write-Host ""
    Write-Host "Verifying fresh RabbitMQ-connected worker heartbeat..." -ForegroundColor Cyan
    $heartbeatReady = $false
    for ($attempt = 1; $attempt -le 24; $attempt++) {
        & docker compose -f .\compose.local.yml exec -T air-api python /app/scripts/check_workflow_runtime.py
        if ($LASTEXITCODE -eq 0) { $heartbeatReady = $true; break }
        Start-Sleep -Seconds 5
    }
    if (!$heartbeatReady) {
        & docker compose -f .\compose.local.yml logs --tail 120 air-workflow-worker
        throw "Worker container is running but a fresh RabbitMQ-connected runtime heartbeat was not verified."
    }

    if (!$SkipAdminBootstrap) {
        $adminStatusText = & docker compose -f .\compose.local.yml exec -T air-api python /app/scripts/check_admin_bootstrap.py
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect the administrator bootstrap state." }
        $adminStatus = $adminStatusText | ConvertFrom-Json
        if ($adminStatus.status -eq "MISSING") {
            Write-Host ""
            Write-Host "No Super Admin exists yet. Complete the secure password + authenticator bootstrap." -ForegroundColor Yellow
            & docker compose -f .\compose.local.yml exec air-api python -m scripts.bootstrap_admin
            if ($LASTEXITCODE -ne 0) { throw "Initial Super Admin bootstrap failed." }
        } else {
            Write-Host "PASS Administrator account already exists; no credentials were changed." -ForegroundColor Green
        }
    }

    Write-Host ""
    Write-Host "AIR LOCAL RUNTIME ACCEPTANCE PASSED" -ForegroundColor Green
    Write-Host "Customer app:       http://localhost:8080/"
    Write-Host "Administrator app:  http://localhost:8080/admin/"
    Write-Host "FastAPI docs:       http://localhost:8000/docs"
    Write-Host "API health:         http://localhost:8000/health"
    Write-Host "Full readiness:     http://localhost:8000/ready (can remain 503 while history imports)"
    Write-Host "PostgreSQL backup:  $backupFile"
    Write-Host "PostgreSQL/Redis were not targeted for recreation."
    if (!$DoNotOpenBrowser) {
        Start-Process "http://localhost:8080/admin/"
        Start-Process "http://localhost:8080/"
    }
}
catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host ""
    Write-Host "Diagnostics:" -ForegroundColor Yellow
    Write-Host "docker compose -f .\compose.local.yml ps"
    Write-Host "docker compose -f .\compose.local.yml logs --tail 100 rabbitmq air-api air-workflow-worker air-pwa"
    throw
}
finally {
    Pop-Location
}
