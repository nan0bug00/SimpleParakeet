# Prepares the local Sherpa ONNX runtime files used by the release workflow.
# ASR models are downloaded and checksum-verified on first launch.

param(
    [switch]$SkipBuild,
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $Root "bin"
$Scripts = Join-Path $Root "scripts"
$ApiExe = Join-Path $Bin "SimpleParakeet\SimpleParakeet.exe"
$Ffmpeg = Join-Path $Bin "ffmpeg.exe"

if (-not $SkipBuild) {
    & (Join-Path $Scripts "build_exe.ps1")
}
if (-not (Test-Path -LiteralPath $ApiExe)) {
    throw "Missing $ApiExe"
}

if (-not $SkipFfmpeg -and -not (Test-Path -LiteralPath $Ffmpeg)) {
    & (Join-Path $Scripts "fetch_ffmpeg.ps1")
}
if (-not (Test-Path -LiteralPath $Ffmpeg)) {
    throw "Missing $Ffmpeg"
}

foreach ($required in @("lexicon.json", "lexicon.example.json", "config.example.json")) {
    $path = Join-Path $Root $required
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing release file: $path"
    }
}

Write-Host "Local Sherpa ONNX release inputs are ready." -ForegroundColor Green
Write-Host "Use the GitHub Actions release workflow to produce the platform archives."
