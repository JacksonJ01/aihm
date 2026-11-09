param(
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+$')]
    [string]$Version = "0.1.1",
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
$bundleDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $bundleDir
$python = if ($PythonExe) { $PythonExe } else { Join-Path $projectRoot ".venv\Scripts\python.exe" }
$spec = Join-Path $bundleDir "AIHuMoDataStudio.spec"
$work = Join-Path $bundleDir "build\v$Version"
$dist = Join-Path $bundleDir "dist\v$Version"
$release = Join-Path $bundleDir "release"
$app = Join-Path $dist "AIHuMo Data Studio"
$zip = Join-Path $release "AIHuMo-Data-Studio-Windows-v$Version.zip"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment not found: $python"
}
if ((Test-Path -LiteralPath $app) -or (Test-Path -LiteralPath $zip)) {
    throw "Build v$Version already exists. Choose a new version or use a clean checkout."
}

New-Item -ItemType Directory -Force -Path $work, $dist, $release | Out-Null
& $python -m PyInstaller --noconfirm --clean --workpath $work --distpath $dist $spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Force -Path (Join-Path $app "data\processed") | Out-Null
Copy-Item -LiteralPath (Join-Path $bundleDir "PORTABLE_README.txt") -Destination (Join-Path $app "README.txt") -Force

$buildInfo = @("Version: $Version")
if (Get-Command git -ErrorAction SilentlyContinue) {
    $sourceCommit = git -C $projectRoot rev-parse HEAD 2>$null
    if ($LASTEXITCODE -eq 0) {
        $buildInfo += "Source commit: $sourceCommit"
    }
}
Set-Content -LiteralPath (Join-Path $app "BUILD-INFO.txt") -Value $buildInfo -Encoding ascii

$temporaryZip = Join-Path $release "AIHuMo-Data-Studio-Windows-v$Version.partial.zip"
try {
    Compress-Archive -LiteralPath $app -DestinationPath $temporaryZip -CompressionLevel Optimal -Force
    Move-Item -LiteralPath $temporaryZip -Destination $zip
} finally {
    if (Test-Path -LiteralPath $temporaryZip) {
        Remove-Item -LiteralPath $temporaryZip
    }
}
$sha256 = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$zip.sha256" -Value "$sha256  $(Split-Path -Leaf $zip)" -Encoding ascii
Write-Host "Created $zip"
