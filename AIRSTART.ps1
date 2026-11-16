[CmdletBinding()]
param([switch]$InstallCommand)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $Root "AIRSTART.ps1"
$ProfilePath = $PROFILE

function Install-AirCommand {
    $profileDir = Split-Path -Parent $ProfilePath
    if (!(Test-Path $profileDir)) { New-Item -ItemType Directory -Force -Path $profileDir | Out-Null }
    if (!(Test-Path $ProfilePath)) { New-Item -ItemType File -Force -Path $ProfilePath | Out-Null }
    $escaped = $ScriptPath.Replace("'", "''")
    $marker = "function AIRSTART { & '$escaped' }"
    $profileText = Get-Content $ProfilePath -Raw
    if ($profileText -notmatch "function\s+AIRSTART") {
        Add-Content -Path $ProfilePath -Value "`n# AIR one-command local startup`n$marker`n"
    }
    Invoke-Expression $marker
    Write-Host "AIRSTART command installed in this PowerShell profile." -ForegroundColor Green
}

if ($InstallCommand) { Install-AirCommand; exit 0 }

if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is missing. Install Docker Desktop, start it, then run AIRSTART again."
}
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is unavailable. Install or update Docker Desktop and retry." }
docker info | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop/Engine is not running. Start Docker and retry." }

Push-Location $Root
try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $pythonArgs = @()
    if ($python) {
        $versionText = & $python.Source --version 2>&1
        if ($versionText -notmatch "Python 3\\.(1[0-9]|[2-9][0-9])") { $python = $null }
    }
    if (!$python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
        if ($python) {
            $pythonArgs += "-3"
            $versionText = & $python.Source -3 --version 2>&1
            if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "Python 3\\.(1[0-9]|[2-9][0-9])") {
                throw "Python 3.10 or newer is required for AIR installation."
            }
        }
    }
    if (!$python) { throw "Python 3.10 or newer is required for AIR installation." }

    $profileId = $env:AIR_DEPLOYMENT_PROFILE
    if (!$profileId) { $profileId = "onprem-single" }
    if ($profileId -ne "onprem-single") {
        throw "AIRSTART is the on-premises installer. Use AIRDEPLOY to validate AWS profiles; live AWS deployment is deferred."
    }
    $env:AIR_DEPLOYMENT_PROFILE = $profileId
    $env:PYTHONPATH = Join-Path $Root "backend"
    & $python.Source @pythonArgs -m app.deployment_profiles --profile $profileId
    if ($LASTEXITCODE -ne 0) { throw "AIR deployment profile validation failed." }

    $secretDir = Join-Path $Root ".air-secrets"
    New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
    Write-Host "Checking and generating all required local-only AIR secrets..." -ForegroundColor Cyan
    & $python.Source @pythonArgs (Join-Path $Root "scripts/generate_local_secrets.py") $secretDir
    if ($LASTEXITCODE -ne 0) { throw "AIR local secret generation failed." }

    $envFile = Join-Path $Root ".air-local.env"
    if (!(Test-Path $envFile)) {
        @"
AIR_OPERATOR_CUSTOMER_IDS=
AIR_MARKET_DATA_POLL_SECONDS=3
AIR_SMTP_PORT=587
"@ | Set-Content -Path $envFile -Encoding ascii
    }

    Write-Host "Validating the rendered AIR Compose configuration..." -ForegroundColor Cyan
    docker compose -f compose.local.yml config --quiet
    if ($LASTEXITCODE -ne 0) { throw "AIR Compose configuration validation failed." }

    if ($env:AIR_START_PULL_BASE_IMAGES -eq "true") {
        Write-Host "Refreshing PostgreSQL, Redis, RabbitMQ and application build bases before upgrade..." -ForegroundColor Cyan
        docker compose -f compose.local.yml pull postgres redis rabbitmq
        if ($LASTEXITCODE -ne 0) { throw "Failed to refresh AIR base images." }
        docker compose -f compose.local.yml build --pull air-api air-workflow-worker air-pwa
        if ($LASTEXITCODE -ne 0) { throw "Failed to rebuild AIR application images from refreshed bases." }
    }

    Write-Host "Building and starting AIR API + PWA..." -ForegroundColor Cyan
    docker compose -f compose.local.yml up -d --build
    if ($LASTEXITCODE -ne 0) { docker compose -f compose.local.yml logs --tail 100; throw "AIR startup failed. Review the logs above." }

    $services = @("postgres", "redis", "rabbitmq", "air-api", "air-workflow-worker", "air-pwa")
    $timeoutMinutes = 720
    if ($env:AIR_INSTALL_READINESS_TIMEOUT_MINUTES) {
        $parsedTimeout = 0
        if ([int]::TryParse($env:AIR_INSTALL_READINESS_TIMEOUT_MINUTES, [ref]$parsedTimeout) -and $parsedTimeout -gt 0) {
            $timeoutMinutes = $parsedTimeout
        }
    }
    $deadline = (Get-Date).AddMinutes($timeoutMinutes)
    $lastProgressAt = Get-Date
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        $allHealthy = $true
        foreach ($service in $services) {
            $containerId = docker compose -f compose.local.yml ps -q $service
            if ($LASTEXITCODE -ne 0 -or !$containerId) { $allHealthy = $false; break }
            $health = docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerId
            if ($LASTEXITCODE -ne 0 -or $health.Trim() -ne "healthy") { $allHealthy = $false; break }
        }
        if ($allHealthy) {
            try {
                $api = Invoke-WebRequest -Uri "http://localhost:8000/ready" -TimeoutSec 5
                $pwa = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 3
                if ($api.StatusCode -eq 200 -and $pwa.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }
        if (((Get-Date) - $lastProgressAt).TotalSeconds -ge 60) {
            Write-Host "AIR is waiting for the complete 12-month NSE history and research readiness gate..." -ForegroundColor Yellow
            $lastProgressAt = Get-Date
        }
        Start-Sleep -Seconds 15
    }
    if (!$ready) {
        docker compose -f compose.local.yml ps
        docker compose -f compose.local.yml logs --tail 100
        throw "AIR did not reach full readiness within $timeoutMinutes minutes. Check service logs and NSE bootstrap status; do not use the app until the readiness gate passes."
    }
    Write-Host "PostgreSQL, Redis, RabbitMQ, FastAPI, workflow worker, PWA and initial market-data readiness are verified." -ForegroundColor Green
    docker compose -f compose.local.yml ps
    if ($env:AIR_START_SKIP_OPEN -ne "true") { Start-Process "http://localhost:8080" }

    if ($env:AIR_START_SKIP_PROFILE -ne "true" -and !$env:AIR_START_PROFILE_INSTALLED) {
        Install-AirCommand
    }
    if ($env:AIR_START_SKIP_PROFILE -ne "true") {
        Write-Host "Next time, open PowerShell in this repository and type: AIRSTART" -ForegroundColor Green
    }
}
finally { Pop-Location }
