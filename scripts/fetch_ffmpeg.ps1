# Fetches a portable LGPL ffmpeg build into bin\ (Windows x64 essentials).
# Source: gyan.dev ffmpeg essentials zip (common redistributable practice).
# Review licenses\ after fetch. Do NOT start servers.

param(
    [string]$Url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $Root "bin"
$Tmp = Join-Path $Root "build\ffmpeg-dl"
$Zip = Join-Path $Tmp "ffmpeg.zip"

New-Item -ItemType Directory -Force -Path $Bin, $Tmp | Out-Null

Write-Host "Downloading ffmpeg essentials..."
Write-Host "  $Url"
curl.exe -L --fail --retry 3 -o $Zip $Url
if ($LASTEXITCODE -ne 0) { throw "download failed" }

Expand-Archive -LiteralPath $Zip -DestinationPath $Tmp -Force
$ffmpeg = Get-ChildItem -Path $Tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
if (-not $ffmpeg) { throw "ffmpeg.exe not found inside zip" }

Copy-Item -LiteralPath $ffmpeg.FullName -Destination (Join-Path $Bin "ffmpeg.exe") -Force

# Copy license texts if present next to the binary in the zip tree
$licenseDir = Join-Path $Root "licenses"
New-Item -ItemType Directory -Force -Path $licenseDir | Out-Null
Get-ChildItem -Path $Tmp -Recurse -Include "LICENSE","LICENSE.txt","COPYING*","README.txt" -ErrorAction SilentlyContinue |
    Select-Object -First 8 |
    ForEach-Object {
        Copy-Item $_.FullName (Join-Path $licenseDir ("ffmpeg-" + $_.Name)) -Force
    }

Set-Content -LiteralPath (Join-Path $licenseDir "NOTICE-ffmpeg.txt") -Encoding UTF8 -Value @"
This folder may include a portable FFmpeg binary (ffmpeg.exe) from the
gyan.dev Windows essentials build (or another LGPL build you drop in bin/).

FFmpeg is licensed under the LGPL (and optionally GPL for some builds).
The essentials build is commonly LGPL. Keep FFmpeg as a separate executable
(mere aggregation with the MIT-licensed shim / parakeet.cpp).

Upstream: https://ffmpeg.org/
Windows builds used by the fetch script: https://www.gyan.dev/ffmpeg/builds/
"@

Write-Host ("Installed {0}" -f (Join-Path $Bin "ffmpeg.exe")) -ForegroundColor Green
Write-Host "Remove $Tmp when you like (download cache)."
