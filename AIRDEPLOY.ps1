[CmdletBinding()]
param(
    [ValidateSet("onprem-single", "aws-private-single", "aws-saas-multi")]
    [string]$Profile = "onprem-single"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProfilePath = Join-Path $Root "backend/config/deployment_profiles/$Profile.json"
if (!(Test-Path $ProfilePath)) { throw "AIR deployment profile not found: $ProfilePath" }
if (!(Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker is required for AIR deployment." }
try { docker info | Out-Null } catch { throw "Docker daemon is not running." }

Write-Host "Validating AIR deployment profile: $Profile" -ForegroundColor Cyan
docker run --rm --mount "type=bind,source=$(Join-Path $Root 'backend'),target=/app" -w /app python:3.12-slim python -m app.deployment_profiles --profile $Profile --require-cloud-env
if ($LASTEXITCODE -ne 0) { throw "AIR deployment profile validation failed." }

$profile = Get-Content $ProfilePath -Raw | ConvertFrom-Json
$env:AIR_DEPLOYMENT_PROFILE = $Profile
$env:AIR_DEPLOYMENT_MODE = $profile.deployment.provider
$env:AIR_TENANCY_MODE = $profile.deployment.tenancy

switch ($Profile) {
    "onprem-single" {
        Write-Host "Starting AIR on-premises single-tenant installation..." -ForegroundColor Cyan
        & (Join-Path $Root "AIRSTART.ps1")
        if ($LASTEXITCODE -ne 0) { throw "AIR on-premises startup failed." }
    }
    default {
        $awsScript = Join-Path $Root "deploy/aws/AIRDEPLOY.ps1"
        if (!(Test-Path $awsScript)) {
            throw "The profile is valid, but its AWS provisioning adapter is delivered in the subsequent AWS deployment gate. No AWS resources were created."
        }
        & $awsScript -Profile $Profile
        if ($LASTEXITCODE -ne 0) { throw "AIR AWS deployment failed." }
    }
}
