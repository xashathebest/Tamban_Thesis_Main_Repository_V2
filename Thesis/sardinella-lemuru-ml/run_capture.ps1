[CmdletBinding()]
param([switch]$IsolatedDevice)

$ErrorActionPreference = 'Stop'
$captureProject = $PSScriptRoot
$capturePython = Join-Path $captureProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $capturePython -PathType Leaf)) {
    throw 'Create the project Python environment and install the existing requirements first.'
}
if ($IsolatedDevice) {
    # This is a deployment declaration, not a shared camera lock. Use only on
    # a capture station/device inaccessible to the unchanged inspection app.
    $env:FISH_CAPTURE_ISOLATED_DEVICE = '1'
}
Push-Location $captureProject
try {
    & $capturePython -B -m src.api.capture_app
    if ($LASTEXITCODE -ne 0) { throw "Camera Capture exited with code $LASTEXITCODE." }
}
finally { Pop-Location }
