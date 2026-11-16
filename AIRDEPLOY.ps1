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
$launcher = @()
if (!$python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $launcher = @("-3.12"); $python = $py }
}
if (!$python) { throw "Python 3.12 is required for AIR Deployment Manager. Install Python and retry." }

if (!$Action) {
    if ($DeploymentProfile -eq "onprem-single") { $Action = "install" }
    else { $Action = "validate" }
}

$args = @((Join-Path $Root "scripts/air_manager.py"), "--profile", $DeploymentProfile, $Action)
if ($Version) { $args += @("--version", $Version) }
if ($OutputDirectory) { $args += @("--output-dir", $OutputDirectory) }
& $python.Source @launcher @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
