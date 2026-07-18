# Builds bin\SimpleParakeet.exe with PyInstaller.
# Does NOT start servers. Does NOT download the GGUF.

param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Src = Join-Path $Root "src"
$Bin = Join-Path $Root "bin"
$Work = Join-Path $Root "build"

if (-not $Python) {
    $candidates = @(
        (Join-Path $Root "..\parakeet-api\venv\Scripts\python.exe")
        (Join-Path $Root "venv\Scripts\python.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { $Python = $c; break }
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "Python not found. Create parakeet-api\venv or pass -Python path."
}

Write-Host "Using $Python"
& $Python -m pip install -r (Join-Path $Src "requirements.txt")
& $Python -m pip install pyinstaller

New-Item -ItemType Directory -Force -Path $Bin, $Work | Out-Null

$entry = Join-Path $Src "server.py"
Push-Location $Src
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --name SimpleParakeet `
        --distpath $Bin `
        --workpath $Work `
        --specpath $Work `
        --hidden-import uvicorn.logging `
        --hidden-import uvicorn.loops `
        --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.protocols `
        --hidden-import uvicorn.protocols.http `
        --hidden-import uvicorn.protocols.http.auto `
        --hidden-import uvicorn.protocols.websockets.auto `
        --hidden-import uvicorn.lifespan.on `
        --collect-all uvicorn `
        --collect-all fastapi `
        --collect-all starlette `
        --collect-all httpx `
        $entry
} finally {
    Pop-Location
}

$out = Join-Path $Bin "SimpleParakeet.exe"
if (-not (Test-Path -LiteralPath $out)) {
    throw "Build finished but $out missing"
}
Write-Host "Built $out" -ForegroundColor Green
