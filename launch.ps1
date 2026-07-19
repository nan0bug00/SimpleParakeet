# SimpleParakeet launcher
# Defaults: API 8210, engine 8211 (override in config.json or with -Setup)

param(
    [switch]$Setup
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$ConfigPath = Join-Path $Root "config.json"
$ExamplePath = Join-Path $Root "config.example.json"
$BinDir = Join-Path $Root "bin"
$LogDir = Join-Path $Root "logs"
$SetupFlag = Join-Path $Root ".setup-complete"
$script:ChildPids = @()

function Test-PortListen([int]$Port) {
    try {
        return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        return $null -ne (netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING")
    }
}

function Read-PortPrompt([string]$Label, [int]$Default) {
    while ($true) {
        $raw = Read-Host ("{0} [{1}]" -f $Label, $Default)
        if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
        $n = 0
        if (-not [int]::TryParse($raw.Trim(), [ref]$n)) {
            Write-Host "Enter a number between 1 and 65535."
            continue
        }
        if ($n -lt 1 -or $n -gt 65535) {
            Write-Host "Enter a number between 1 and 65535."
            continue
        }
        return $n
    }
}

function Get-Config {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        if (-not (Test-Path -LiteralPath $ExamplePath)) {
            throw "Missing config.example.json"
        }
        Copy-Item -LiteralPath $ExamplePath -Destination $ConfigPath
    }
    return Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
}

function Save-Config($cfg) {
    $cfg | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
}

function Ensure-FirstRun($cfg, [bool]$Force) {
    if ((Test-Path -LiteralPath $SetupFlag) -and -not $Force) {
        return $cfg
    }

    Write-Host ""
    Write-Host "SimpleParakeet setup"
    Write-Host "Press Enter to keep the value in [brackets]."
    Write-Host ""

    $hostBind = [string]$cfg.host
    if ([string]::IsNullOrWhiteSpace($hostBind)) { $hostBind = "127.0.0.1" }
    $hostIn = Read-Host ("Listen address [{0}]" -f $hostBind)
    if (-not [string]::IsNullOrWhiteSpace($hostIn)) { $hostBind = $hostIn.Trim() }

    $apiPort = Read-PortPrompt "Whisper API port" ([int]$cfg.api_port)
    while (Test-PortListen $apiPort) {
        Write-Host ("Port {0} is already in use." -f $apiPort)
        $apiPort = Read-PortPrompt "Whisper API port" $apiPort
    }

    $pkPort = Read-PortPrompt "Internal engine port" ([int]$cfg.parakeet_port)
    while ($pkPort -eq $apiPort -or (Test-PortListen $pkPort)) {
        if ($pkPort -eq $apiPort) {
            Write-Host "Internal engine port must be different from the API port."
        } else {
            Write-Host ("Port {0} is already in use." -f $pkPort)
        }
        $pkPort = Read-PortPrompt "Internal engine port" $pkPort
    }

    $cfg.host = $hostBind
    $cfg.api_port = $apiPort
    $cfg.parakeet_port = $pkPort
    Save-Config $cfg
    Set-Content -LiteralPath $SetupFlag -Value (Get-Date -Format o) -Encoding ASCII

    Write-Host ""
    Write-Host "Saved settings to config.json"
    Write-Host ""
    return $cfg
}

function Resolve-ModelPath($cfg) {
    $modelRel = [string]$cfg.model
    if ([string]::IsNullOrWhiteSpace($modelRel)) {
        $modelRel = "models/tdt_ctc-110m-f16.gguf"
    }
    $modelPath = if ([System.IO.Path]::IsPathRooted($modelRel)) {
        $modelRel
    } else {
        Join-Path $Root ($modelRel -replace "/", [IO.Path]::DirectorySeparatorChar)
    }
    if (-not (Test-Path -LiteralPath $modelPath)) {
        throw "Missing model file: $modelPath"
    }
    return $modelPath
}

function Assert-BundleFiles {
    $apiExe = Join-Path $BinDir "SimpleParakeet\SimpleParakeet.exe"
    $apiDir = Join-Path $BinDir "SimpleParakeet"
    $apiPy = Join-Path $Root "src\server.py"
    $pkExe = Join-Path $BinDir "parakeet-server.exe"
    $ffmpeg = Join-Path $BinDir "ffmpeg.exe"

    if (-not (Test-Path -LiteralPath $pkExe)) {
        throw "Missing bin\parakeet-server.exe"
    }
    if (-not (Test-Path -LiteralPath $apiExe) -and -not (Test-Path -LiteralPath $apiPy)) {
        throw "Missing bin\SimpleParakeet\SimpleParakeet.exe"
    }
    return @{
        ApiExe = $apiExe
        ApiDir = $apiDir
        HasExe = (Test-Path -LiteralPath $apiExe)
        PkExe  = $pkExe
        Ffmpeg = $ffmpeg
        HasFfmpeg = (Test-Path -LiteralPath $ffmpeg)
    }
}

function Start-Hidden {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$OutLog,
        [Parameter(Mandatory = $true)][string]$ErrLog
    )
    # Start-Process -ArgumentList <array> does NOT quote args with spaces, so
    # paths like C:\Skyrim MGO\... break (--model gets "C:\Skyrim", rest is junk).
    # ProcessStartInfo.ArgumentList quotes each arg correctly (.NET).
    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $FilePath
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    # Avoid redirect complexity; append a one-shot note to the log path for debugging.
    foreach ($a in $ArgumentList) {
        [void]$psi.ArgumentList.Add([string]$a)
    }

    try {
        "Starting: $FilePath $($ArgumentList -join ' ')" | Set-Content -LiteralPath $OutLog -Encoding utf8
        "" | Set-Content -LiteralPath $ErrLog -Encoding utf8
    } catch { }

    $p = [System.Diagnostics.Process]::Start($psi)
    if (-not $p) { throw "Failed to start: $FilePath" }
    $script:ChildPids += $p.Id
    return $p
}

function Stop-Children {
    # PyInstaller onefile spawns a child; kill the whole tree.
    foreach ($childId in @($script:ChildPids)) {
        try {
            & taskkill.exe /F /T /PID $childId 2>$null | Out-Null
        } catch { }
        try {
            Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue
        } catch { }
    }
    $script:ChildPids = @()
}

function Wait-ApiReady([string]$HostBind, [int]$Port, [int]$TimeoutSec = 90) {
    $url = "http://${HostBind}:${Port}/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    Write-Host ("Starting... (waiting for http://{0}:{1})" -f $HostBind, $Port)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
                return $true
            }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }
    return $false
}

function Show-LogTail([string]$Path, [int]$Lines = 20) {
    if (Test-Path -LiteralPath $Path) {
        Write-Host ("--- {0} ---" -f $Path)
        Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    }
}

function Show-Endpoint([string]$HostBind, [int]$Port) {
    $endpoint = "http://${HostBind}:${Port}/v1/audio/transcriptions"
    Write-Host ""
    Write-Host "============================================================"
    Write-Host " Ready. External Whisper endpoint:"
    Write-Host ""
    Write-Host " $endpoint"
    Write-Host ""
    Write-Host " Model: whisper-1"
    Write-Host " API key: any non-empty value"
    Write-Host "============================================================"
    Write-Host ""
    try {
        Set-Clipboard -Value $endpoint
        Write-Host "Copied to clipboard."
    } catch { }
}

$oldDevice = $env:PARAKEET_DEVICE
$oldUpstream = $env:PARAKEET_UPSTREAM
$oldFfmpeg = $env:PARAKEET_FFMPEG
$oldPath = $env:PATH

try {
    Write-Host ""
    Write-Host "SimpleParakeet"
    Write-Host ""

    if ($Setup) {
        Remove-Item -LiteralPath $SetupFlag -ErrorAction SilentlyContinue
    }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    $cfg = Get-Config
    $cfg = Ensure-FirstRun -cfg $cfg -Force:$Setup
    $files = Assert-BundleFiles
    $modelPath = Resolve-ModelPath $cfg

    $hostBind = [string]$cfg.host
    $apiPort = [int]$cfg.api_port
    $pkPort = [int]$cfg.parakeet_port
    $device = [string]$cfg.device
    if ([string]::IsNullOrWhiteSpace($device)) { $device = "cpu" }

    if (Test-PortListen $apiPort) {
        throw "Port $apiPort is already in use. Close whatever is using it, or run: pwsh -File launch.ps1 -Setup"
    }
    if (Test-PortListen $pkPort) {
        throw "Port $pkPort is already in use. Close whatever is using it, or run: pwsh -File launch.ps1 -Setup"
    }

    if (-not $files.HasFfmpeg) {
        Write-Host "Note: bin\ffmpeg.exe not found. WAV and PCM still work."
    }

    $env:PARAKEET_DEVICE = $device
    $null = Start-Hidden `
        -FilePath $files.PkExe `
        -ArgumentList @("--model", $modelPath, "--host", $hostBind, "--port", "$pkPort") `
        -WorkingDirectory $BinDir `
        -OutLog (Join-Path $LogDir "parakeet.out.log") `
        -ErrLog (Join-Path $LogDir "parakeet.err.log")

    $upstream = "http://${hostBind}:${pkPort}/v1/audio/transcriptions"
    $env:PARAKEET_UPSTREAM = $upstream
    $env:PARAKEET_FFMPEG = $files.Ffmpeg
    $env:PATH = $BinDir + ";" + $oldPath

    if ($files.HasExe) {
        $null = Start-Hidden `
            -FilePath $files.ApiExe `
            -ArgumentList @("--host", $hostBind, "--port", "$apiPort") `
            -WorkingDirectory $files.ApiDir `
            -OutLog (Join-Path $LogDir "api.out.log") `
            -ErrLog (Join-Path $LogDir "api.err.log")
    } else {
        $py = Join-Path $Root "..\parakeet-api\venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $py)) {
            throw "Missing bin\SimpleParakeet\SimpleParakeet.exe (API binary not built yet)."
        }
        $srcDir = Join-Path $Root "src"
        $null = Start-Hidden `
            -FilePath $py `
            -ArgumentList @((Join-Path $srcDir "server.py"), "--host", $hostBind, "--port", "$apiPort") `
            -WorkingDirectory $srcDir `
            -OutLog (Join-Path $LogDir "api.out.log") `
            -ErrLog (Join-Path $LogDir "api.err.log")
    }

    if (-not (Wait-ApiReady -HostBind $hostBind -Port $apiPort)) {
        Write-Host ""
        Write-Host "Startup failed. Log tails:"
        Show-LogTail (Join-Path $LogDir "parakeet.err.log")
        Show-LogTail (Join-Path $LogDir "api.err.log")
        throw "API did not become ready."
    }

    Show-Endpoint -HostBind $hostBind -Port $apiPort
    Write-Host "Keep this window open while using speech-to-text."
    Write-Host "Press Enter to stop."
    [void](Read-Host)
}
finally {
    Stop-Children
    $env:PARAKEET_DEVICE = $oldDevice
    $env:PARAKEET_UPSTREAM = $oldUpstream
    $env:PARAKEET_FFMPEG = $oldFfmpeg
    $env:PATH = $oldPath
}
