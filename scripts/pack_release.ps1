# Assembles a shareable SimpleParakeet folder (does not zip by default).
# Expects/copies the GGUF into models\. Does NOT start servers.

param(
    [switch]$SkipBuild,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $Root "bin"
$Scripts = Join-Path $Root "scripts"
$LocalPk = Join-Path $Root "..\parakeet\parakeet-server.exe"
$LocalModel = Join-Path $Root "..\parakeet\tdt_ctc-110m-f16.gguf"
$DestModel = Join-Path $Root "models\tdt_ctc-110m-f16.gguf"

New-Item -ItemType Directory -Force -Path $Bin, (Split-Path $DestModel) | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $Bin "parakeet-server.exe"))) {
    if (-not (Test-Path -LiteralPath $LocalPk)) {
        throw "Need bin\parakeet-server.exe (copy from a parakeet.cpp Windows release)"
    }
    Copy-Item $LocalPk (Join-Path $Bin "parakeet-server.exe") -Force
    Write-Host "Copied parakeet-server.exe"
}

if (-not (Test-Path -LiteralPath $DestModel)) {
    if (-not (Test-Path -LiteralPath $LocalModel)) {
        throw "Need models\tdt_ctc-110m-f16.gguf (copy from your parakeet install)"
    }
    Copy-Item $LocalModel $DestModel -Force
    Write-Host "Copied GGUF model into models\"
}

$apiSrc = Join-Path $Root "..\parakeet-api"
if (Test-Path -LiteralPath (Join-Path $apiSrc "server.py")) {
    Copy-Item (Join-Path $apiSrc "server.py") (Join-Path $Root "src\server.py") -Force
    Copy-Item (Join-Path $apiSrc "audio.py") (Join-Path $Root "src\audio.py") -Force
    Copy-Item (Join-Path $apiSrc "requirements.txt") (Join-Path $Root "src\requirements.txt") -Force
    Write-Host "Synced src from parakeet-api"
}

if (-not $SkipBuild -and -not (Test-Path -LiteralPath (Join-Path $Bin "SimpleParakeet.exe"))) {
    Write-Host "Building SimpleParakeet.exe (PyInstaller)..."
    & (Join-Path $Scripts "build_exe.ps1")
}

if (-not $SkipFfmpeg -and -not (Test-Path -LiteralPath (Join-Path $Bin "ffmpeg.exe"))) {
    Write-Host "Fetching portable ffmpeg..."
    & (Join-Path $Scripts "fetch_ffmpeg.ps1")
}

Write-Host ""
Write-Host "Bundle staging ready at:" -ForegroundColor Green
Write-Host "  $Root"
Write-Host "Zip that folder (exclude build\, .setup-complete, venv, logs) for release."
Write-Host "End users double-click RUN-ME.bat"
