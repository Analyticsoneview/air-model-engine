[CmdletBinding()]
param(
    [string]$RunnerRoot = "$env:ProgramData\AIR\GitHubRunner"
)

$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Open PowerShell as Administrator and run this installer again."
    }
}

function Get-LatestRunnerAsset {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/actions/runner/releases/latest" -Headers @{ "User-Agent" = "AIR-runner-installer" }
    $asset = $release.assets | Where-Object { $_.name -match '^actions-runner-win-x64-.*\.zip$' } | Select-Object -First 1
    if (-not $asset) { throw "Could not find the official Windows x64 runner package in the latest GitHub release." }
    return @{ Url = $asset.browser_download_url; Digest = $asset.digest; Name = $asset.name }
}

Assert-Administrator
$repoUrl = "https://github.com/Analyticsoneview/air-model-engine"
if (Test-Path (Join-Path $RunnerRoot ".runner")) {
    throw "A runner is already configured at $RunnerRoot. Remove it from GitHub and run the runner's config.cmd remove flow before reinstalling."
}
New-Item -ItemType Directory -Force -Path $RunnerRoot | Out-Null

Write-Host "Fetching the official GitHub Actions Windows x64 runner release..."
$asset = Get-LatestRunnerAsset
$archive = Join-Path $RunnerRoot $asset.Name
Invoke-WebRequest -Uri $asset.Url -OutFile $archive

if ($asset.Digest -and $asset.Digest.StartsWith("sha256:")) {
    $actual = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = $asset.Digest.Substring(7).ToLowerInvariant()
    if ($actual -ne $expected) { Remove-Item $archive -Force; throw "Runner package SHA-256 verification failed." }
} else {
    Write-Warning "GitHub did not publish a SHA-256 digest for this release; verify the official download before production use."
}

Expand-Archive -Path $archive -DestinationPath $RunnerRoot -Force
Remove-Item $archive -Force
$tokenPtr = [IntPtr]::Zero
$tokenSecure = $null
if ($env:AIR_RUNNER_TOKEN) {
    $token = $env:AIR_RUNNER_TOKEN
} else {
    $tokenSecure = Read-Host "Enter the short-lived repository runner registration token" -AsSecureString
    $tokenPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenSecure)
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPtr)
}
try {
    Push-Location $RunnerRoot
    try {
        & .\config.cmd --unattended --url $repoUrl --token $token --name "$env:COMPUTERNAME-air" --labels "air,windows,x64" --work "_work"
        if ($LASTEXITCODE -ne 0) { throw "GitHub runner registration failed with exit code $LASTEXITCODE." }
        & .\svc.cmd install
        if ($LASTEXITCODE -ne 0) { throw "Runner registered, but Windows service installation failed." }
        & .\svc.cmd start
        if ($LASTEXITCODE -ne 0) { throw "Runner registered, but its Windows service did not start. Inspect the runner service before continuing." }
    }
    finally { Pop-Location }
}
finally {
    if ($tokenPtr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPtr) }
    $token = $null
    $tokenSecure = $null
}

Write-Host ""
Write-Host "AIR self-hosted runner registered. Verify it is Online/Idle in repository Settings > Actions > Runners." -ForegroundColor Green
Write-Host 'Then set repository Actions variable AIR_CI_RUNNER_LABELS to ["self-hosted","windows","x64","air"]. Keep AIR_RUNNER_LABELS unset on Windows; the PWA and Docker Buildx workflows require Linux.'
Write-Host "Backend and Android workflows do not require Docker. Docker Desktop is needed only for workflows that build/run containers."
