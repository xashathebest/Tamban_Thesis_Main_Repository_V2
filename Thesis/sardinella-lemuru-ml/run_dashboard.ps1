[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at '$python'. Create it and install requirements.txt before starting the dashboard."
}

Push-Location $projectRoot
try {
    if (-not $env:FISH_STRICT_MODEL_INTEGRITY) {
        $env:FISH_STRICT_MODEL_INTEGRITY = '1'
    }
    & $python -m src.api
    if ($LASTEXITCODE -ne 0) {
        throw "The dashboard exited with code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
