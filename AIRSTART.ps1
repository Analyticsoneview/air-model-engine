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
try { docker compose version | Out-Null; docker info | Out-Null }
catch { throw "Docker Desktop is not running or Docker Compose v2 is unavailable. Start Docker Desktop and retry." }

Push-Location $Root
try {
    $secretDir = Join-Path $Root ".air-secrets"
    New-Item -ItemType Directory -Force -Path $secretDir | Out-Null
    Write-Host "Checking and generating all required local-only AIR secrets..." -ForegroundColor Cyan
    docker run --rm --mount "type=bind,source=$secretDir,target=/secrets" --mount "type=bind,source=$Root/scripts,target=/scripts,readonly" python:3.12-slim python /scripts/generate_local_secrets.py
    if ($LASTEXITCODE -ne 0) { throw "AIR local secret generation failed." }

    $envFile = Join-Path $Root ".air-local.env"
    if (!(Test-Path $envFile)) {
        @"
AIR_OPERATOR_CUSTOMER_IDS=
AIR_MARKET_DATA_POLL_SECONDS=3
AIR_SMTP_PORT=587
"@ | Set-Content -Path $envFile -Encoding ascii
    }

    Write-Host "Building and starting AIR API + PWA..." -ForegroundColor Cyan
    docker compose -f compose.local.yml up -d --build
    if ($LASTEXITCODE -ne 0) { docker compose -f compose.local.yml logs --tail 100; throw "AIR startup failed. Review the logs above." }

    $services = @("postgres", "redis", "air-api", "air-pwa")
    $ready = $false
    for ($i=0; $i -lt 36; $i++) {
        $allHealthy = $true
        foreach ($service in $services) {
            $containerId = docker compose -f compose.local.yml ps -q $service
            if ($LASTEXITCODE -ne 0 -or !$containerId) { $allHealthy = $false; break }
            $health = docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" $containerId
            if ($LASTEXITCODE -ne 0 -or $health.Trim() -ne "healthy") { $allHealthy = $false; break }
        }
        if ($allHealthy) {
            try {
                $api = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 3
                $pwa = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 3
                if ($api.StatusCode -eq 200 -and $pwa.StatusCode -eq 200) { $ready = $true; break }
            } catch { }
        }
        Start-Sleep -Seconds 5
    }
    if (!$ready) {
        docker compose -f compose.local.yml ps
        docker compose -f compose.local.yml logs --tail 100
        throw "PostgreSQL, Redis, AIR API and PWA did not all become healthy. Do not use the app until the reported issue is fixed."
    }
    Write-Host "PostgreSQL, Redis, FastAPI and PWA are healthy." -ForegroundColor Green
    docker compose -f compose.local.yml ps
    Start-Process "http://localhost:8080"

    if (!$env:AIR_START_PROFILE_INSTALLED) { Install-AirCommand }
    Write-Host "Next time, open PowerShell in this repository and type: AIRSTART" -ForegroundColor Green
}
finally { Pop-Location }
