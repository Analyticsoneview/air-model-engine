[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Repo = "Analyticsoneview/air-model-engine"
$Branch = "feat/air-telegram-alerts"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
function Stop-AirSetup([string]$Message) { throw "AIR-SETUP: $Message" }
function Invoke-Gh([string[]]$Arguments) {
    & gh @Arguments
    if ($LASTEXITCODE -ne 0) { Stop-AirSetup "GitHub CLI command failed: gh $($Arguments -join ' ')" }
}
$CurrentBranch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $CurrentBranch -ne $Branch) { Stop-AirSetup "Check out branch $Branch first." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Stop-AirSetup "GitHub CLI is required. Install it from https://cli.github.com/ and rerun AIR-SETUP." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-AirSetup "Git is required." }
& gh auth status -h github.com *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Opening GitHub browser authentication. Sign in and grant repository access."
    Invoke-Gh @("auth","login","--web","-h","github.com","-p","https","-s","repo,workflow")
}
$Arch = if ([Environment]::Is64BitOperatingSystem) { "x64" } else { Stop-AirSetup "Only 64-bit Windows is supported." }
$Labels = '["self-hosted","windows","x64","air"]'
$RunnerName = "$env:COMPUTERNAME-air"
$RunnerRoot = Join-Path $env:ProgramData "AIR\GitHubRunner"
Write-Host "Requesting a short-lived runner token directly from GitHub (it will not be displayed)..."
$Token = (& gh api --method POST "repos/$Repo/actions/runners/registration-token" --jq .token)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Token)) { Stop-AirSetup "Could not create runner token. Your GitHub login needs repository administration permission." }
try {
    if (-not (Test-Path (Join-Path $RunnerRoot ".runner"))) {
        $env:AIR_RUNNER_TOKEN = $Token.Trim()
        try { & "$Root\deploy\install-github-runner.ps1" } finally { Remove-Item Env:AIR_RUNNER_TOKEN -ErrorAction SilentlyContinue }
        if ($LASTEXITCODE -ne 0) { Stop-AirSetup "Runner installation failed." }
    } else { Write-Host "Runner already configured; skipping installation." }
}
finally { $Token = $null }
Invoke-Gh @("variable","set","AIR_CI_RUNNER_LABELS","--repo",$Repo,"--body",$Labels)
Write-Host "Waiting for runner '$RunnerName' to report Online..."
$Online = $false
for ($i=0; $i -lt 60; $i++) {
    $Status = (& gh api "repos/$Repo/actions/runners" --jq ".runners[] | select(.name == `"$RunnerName`") | .status" 2>$null | Select-Object -Last 1)
    if ($Status -eq "online") { $Online = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $Online) { Stop-AirSetup "Runner did not become Online within five minutes. Check GitHub Actions Runners settings and the local runner service." }
function Start-And-WatchWorkflow([string]$Workflow) {
    $Previous = (& gh run list --repo $Repo --workflow $Workflow --branch $Branch --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>$null)
    Invoke-Gh @("workflow","run",$Workflow,"--repo",$Repo,"--ref",$Branch)
    $RunId = ""
    for ($i=0; $i -lt 60; $i++) {
        $Candidate = (& gh run list --repo $Repo --workflow $Workflow --branch $Branch --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>$null)
        if ($Candidate -and $Candidate -ne $Previous) { $RunId = $Candidate.Trim(); break }
        Start-Sleep -Seconds 5
    }
    if (-not $RunId) { Stop-AirSetup "Could not locate the dispatched run for $Workflow." }
    Invoke-Gh @("run","watch",$RunId,"--repo",$Repo,"--exit-status")
}
Start-And-WatchWorkflow "backend-tests.yml"
Start-And-WatchWorkflow "android-lab.yml"
Write-Host "AIR-SETUP completed: runner online; backend and Android workflows passed." -ForegroundColor Green
Write-Host "Review the Android APK artifact and PR checks at https://github.com/$Repo/pull/7"
