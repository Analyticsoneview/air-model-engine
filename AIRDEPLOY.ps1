[CmdletBinding()]
param(
    [ValidateSet("onprem-single", "aws-private-single", "aws-saas-multi")]
    [string]$DeploymentProfile = "onprem-single",
    [ValidateSet("validate", "doctor", "install", "upgrade", "status", "diagnose", "package")]
    [string]$Action = "",
    [string]$Version = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Get-Command python -ErrorAction SilentlyContinue
$pythonArgs = @()
if (!$python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { $pythonArgs += "-3.12" }
}
if (!$python) { throw "Python 3.12 is required for AIR Deployment Manager. Install Python and retry." }

if (!$Action) {
    if ($DeploymentProfile -eq "onprem-single") { $Action = "install" }
    else { $Action = "validate" }
}

$pythonArgs += (Join-Path $Root "scripts/air_manager.py")
$pythonArgs += @("--profile", $DeploymentProfile)
if ($Version) { $pythonArgs += @("--version", $Version) }
if ($OutputDirectory) { $pythonArgs += @("--output-dir", $OutputDirectory) }
$pythonArgs += $Action

& $python.Source @pythonArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
