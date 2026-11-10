param(
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')]
    [string]$Version = "0.1.4",
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
$parentScript = Join-Path (Split-Path -Parent $PSScriptRoot) "build_portable.ps1"
if ($PythonExe) {
    & $parentScript -Version $Version -PythonExe $PythonExe
} else {
    & $parentScript -Version $Version
}
exit $LASTEXITCODE
