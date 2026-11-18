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

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-WindowsHostPrerequisites {
    # Installing WSL2 and Docker Desktop requires elevation. Relaunch this same
    # installer once with UAC; never silently reboot the customer's PC.
    if (-not (Test-IsAdministrator)) {
        $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$ScriptPath`"")
        if ($InstallCommand) { $arguments += "-InstallCommand" }
        Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -Verb RunAs
        exit 0
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Windows Package Manager (winget) is required to provision AIR prerequisites automatically. Install/update 'App Installer' from Microsoft Store, then rerun AIRSTART."
    }

    # Python is used by the AIR Deployment Manager and local secret generator.
    $python = Get-Command python -ErrorAction SilentlyContinue
    $pythonOk = $false
    if ($python) {
        $versionText = & $python.Source --version 2>&1
        $pythonOk = ($versionText -match "Python 3\.(1[0-9]|[2-9][0-9])")
    }
    if (-not $pythonOk) {
        Write-Host "Installing Python 3.12 prerequisite..." -ForegroundColor Cyan
        & winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Automatic Python 3.12 installation failed. Install Python 3.10+ and rerun AIRSTART." }
        $env:Path = "$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts;$env:Path"
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { throw "Python was installed but is not yet available in PATH. Open a new PowerShell window and rerun AIRSTART." }
    }

    # WSL2 is the supported Linux container backend for Docker Desktop on Windows.
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    $wslReady = $false
    if ($wsl) {
        & wsl.exe --status *> $null
        $wslReady = ($LASTEXITCODE -eq 0)
    }
    if (-not $wslReady) {
        Write-Host "Installing WSL2 prerequisites (no Linux distribution is required)..." -ForegroundColor Cyan
        & wsl.exe --install --no-distribution
        if ($LASTEXITCODE -ne 0) {
            throw "WSL2 installation could not complete. Check Windows optional features and hardware virtualization, reboot if requested, then rerun AIRSTART."
        }
        throw "WSL2 components have been installed. Restart Windows to finish enabling WSL2, then run AIRSTART again. AIR will resume automatically."
    }

    # Docker Desktop includes Docker Engine, CLI and Compose v2. RabbitMQ,
    # PostgreSQL and Redis are provisioned later as AIR Compose services.
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        Write-Host "Installing Docker Desktop..." -ForegroundColor Cyan
        & winget install --id Docker.DockerDesktop --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { throw "Automatic Docker Desktop installation failed. Install Docker Desktop and rerun AIRSTART." }
        $candidatePaths = @(
            "$env:ProgramFiles\Docker\Docker\resources\bin",
            "$env:ProgramFiles\Docker\Docker\resources"
        )
        foreach ($candidate in $candidatePaths) {
            if (Test-Path $candidate) { $env:Path = "$candidate;$env:Path" }
        }
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if (-not $docker) {
            throw "Docker Desktop installed, but its CLI is not yet available. Restart PowerShell (or Windows if requested) and rerun AIRSTART."
        }
    }

    docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is unavailable after Docker Desktop provisioning. Update Docker Desktop and rerun AIRSTART." }

    # Start Docker Desktop if its Linux engine is not already running.
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        $desktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path $desktop) { Start-Process -FilePath $desktop }
        $deadline = (Get-Date).AddMinutes(5)
        do {
            Start-Sleep -Seconds 5
            docker info *> $null
            if ($LASTEXITCODE -eq 0) { break }
        } while ((Get-Date) -lt $deadline)
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is installed but its Linux engine is not ready. Complete Docker Desktop first-run setup, enable the WSL2 engine, accept its service prompt if shown, then rerun AIRSTART."
    }
}

Ensure-WindowsHostPrerequisites

Push-Location $Root
try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $pythonArgs = @()
    if ($python) {
        $versionText = & $python.Source --version 2>&1
        if ($versionText -notmatch "Python 3\.(1[0-9]|[2-9][0-9])") { $python = $null }
    }
    if (!$python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
        if ($python) {
            $pythonArgs += "-3"
            $versionText = & $python.Source -3 --version 2>&1
            if ($LASTEXITCODE -ne 0 -or $versionText -notmatch "Python 3\.(1[0-9]|[2-9][0-9])") {
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
                $api = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/health" -TimeoutSec 5
                $application = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/ready" -TimeoutSec 10
                $pwa = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/health" -TimeoutSec 3
                if ($api.StatusCode -eq 200 -and $application.StatusCode -eq 200 -and $pwa.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            } catch { }
        }
        if (((Get-Date) - $lastProgressAt).TotalSeconds -ge 60) {
            Write-Host "AIR services are starting; waiting for API /ready, market-data bootstrap and RabbitMQ worker heartbeat..." -ForegroundColor Yellow
            $lastProgressAt = Get-Date
        }
        Start-Sleep -Seconds 15
    }
    if (!$ready) {
        docker compose -f compose.local.yml ps
        docker compose -f compose.local.yml logs --tail 100
        throw "AIR full application readiness (/ready) did not pass within $timeoutMinutes minutes. Check service logs, market-data bootstrap and RabbitMQ worker heartbeat."
    }
    Write-Host "AIR full readiness passed: API dependencies, market-data bootstrap and RabbitMQ-connected workflow heartbeat are healthy." -ForegroundColor Green
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
