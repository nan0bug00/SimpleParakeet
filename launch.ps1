# SimpleParakeet v2 launcher (in-process Sherpa ONNX backend).

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

function Set-ConfigValue($cfg, [string]$Name, $Value) {
    if ($null -eq $cfg.PSObject.Properties[$Name]) {
        $cfg | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    } else {
        $cfg.$Name = $Value
    }
}

function Ensure-FirstRun($cfg, [bool]$Force) {
    if ((Test-Path -LiteralPath $SetupFlag) -and -not $Force) {
        return $cfg
    }

    Write-Host ""
    Write-Host "SimpleParakeet setup"
    Write-Host "Press Enter to keep the value in [brackets]."
    Write-Host ""

    $currentChoice = [string]$cfg.model_choice
    $hasExplicitModel = [string]::IsNullOrWhiteSpace($currentChoice) -and
        -not [string]::IsNullOrWhiteSpace([string]$cfg.model_dir
        )
    if (-not $hasExplicitModel) {
        if ($currentChoice -ne "multilingual-600m") { $currentChoice = "english-110m" }
        Write-Host "Choose the speech model before download:"
        Write-Host "  1. English - Fast (110M), recommended"
        Write-Host "  2. Multilingual (0.6B), slower"
        $defaultNumber = if ($currentChoice -eq "multilingual-600m") { "2" } else { "1" }
        while ($true) {
            $modelIn = Read-Host ("Model [{0}]" -f $defaultNumber)
            if ([string]::IsNullOrWhiteSpace($modelIn)) { $modelIn = $defaultNumber }
            if ($modelIn.Trim() -eq "1") { $currentChoice = "english-110m"; break }
            if ($modelIn.Trim() -eq "2") { $currentChoice = "multilingual-600m"; break }
            Write-Host "Enter 1 or 2."
        }
    }

    $hostBind = [string]$cfg.host
    if ([string]::IsNullOrWhiteSpace($hostBind)) { $hostBind = "127.0.0.1" }
    $hostIn = Read-Host ("Listen address [{0}]" -f $hostBind)
    if (-not [string]::IsNullOrWhiteSpace($hostIn)) { $hostBind = $hostIn.Trim() }

    $apiPort = Read-PortPrompt "Whisper API port" ([int]$cfg.api_port)
    while (Test-PortListen $apiPort) {
        Write-Host ("Port {0} is already in use." -f $apiPort)
        $apiPort = Read-PortPrompt "Whisper API port" $apiPort
    }

    $cfg.host = $hostBind
    $cfg.api_port = $apiPort
    if (-not $hasExplicitModel) {
        Set-ConfigValue $cfg "model_choice" $currentChoice
    }
    Save-Config $cfg
    Set-Content -LiteralPath $SetupFlag -Value (Get-Date -Format o) -Encoding ASCII

    Write-Host ""
    Write-Host "Saved settings to config.json"
    Write-Host ""
    return $cfg
}

function Assert-BundleFiles {
    $apiExe = Join-Path $BinDir "SimpleParakeet\SimpleParakeet.exe"
    $apiDir = Join-Path $BinDir "SimpleParakeet"
    $apiPy = Join-Path $Root "src\server.py"
    $ffmpeg = Join-Path $BinDir "ffmpeg.exe"

    if (-not (Test-Path -LiteralPath $apiExe) -and -not (Test-Path -LiteralPath $apiPy)) {
        throw "Missing bin\SimpleParakeet\SimpleParakeet.exe"
    }
    return @{
        ApiExe = $apiExe
        ApiDir = $apiDir
        HasExe = (Test-Path -LiteralPath $apiExe)
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
    # Stop the API and any worker process it spawned.
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

    $hostBind = [string]$cfg.host
    $apiPort = [int]$cfg.api_port
    $onnxThreads = [int]$cfg.onnx_threads
    if ($onnxThreads -lt 1) { $onnxThreads = [Math]::Min(4, [Math]::Max(1, [Environment]::ProcessorCount / 2)) }

    if (Test-PortListen $apiPort) {
        throw "Port $apiPort is already in use. Close whatever is using it, or run: pwsh -File launch.ps1 -Setup"
    }

    if (-not $files.HasFfmpeg) {
        Write-Host "Note: bin\ffmpeg.exe not found. WAV and PCM still work."
    }

    $env:PARAKEET_ROOT = $Root
    $modelChoice = [string]$cfg.model_choice
    $configuredModelDir = [string]$cfg.model_dir
    if (-not [string]::IsNullOrWhiteSpace($modelChoice)) {
        $env:PARAKEET_MODEL_CHOICE = $modelChoice
        Remove-Item Env:PARAKEET_MODEL_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:PARAKEET_MODEL_TYPE -ErrorAction SilentlyContinue
    } elseif (-not [string]::IsNullOrWhiteSpace($configuredModelDir)) {
        Remove-Item Env:PARAKEET_MODEL_CHOICE -ErrorAction SilentlyContinue
        $env:PARAKEET_MODEL_DIR = $configuredModelDir
        $env:PARAKEET_MODEL_TYPE = if ([string]::IsNullOrWhiteSpace([string]$cfg.model_type)) { "nemo_transducer" } else { [string]$cfg.model_type }
    } else {
        Remove-Item Env:PARAKEET_MODEL_CHOICE -ErrorAction SilentlyContinue
        Remove-Item Env:PARAKEET_MODEL_DIR -ErrorAction SilentlyContinue
        Remove-Item Env:PARAKEET_MODEL_TYPE -ErrorAction SilentlyContinue
    }
    $env:PARAKEET_ONNX_THREADS = "$onnxThreads"
    $env:PARAKEET_LEXICON_ENABLED = if ($cfg.lexicon_enabled -eq $false) { "false" } else { "true" }
    if ($env:PARAKEET_LEXICON_ENABLED -eq "true") {
        $lexiconFile = [string]$cfg.lexicon_file
        if ([string]::IsNullOrWhiteSpace($lexiconFile)) { $lexiconFile = "lexicon.json" }
        $env:PARAKEET_LEXICON_FILE = Join-Path $Root $lexiconFile
    }
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
        $py = Join-Path $Root "venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $py)) {
            $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
            if ($pythonCommand) { $py = $pythonCommand.Source }
        }
        if (-not $py -or -not (Test-Path -LiteralPath $py)) {
            throw "Missing bin\SimpleParakeet\SimpleParakeet.exe and no local Python was found."
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
    $env:PARAKEET_FFMPEG = $oldFfmpeg
    $env:PATH = $oldPath
}
