#Requires -Version 5.1
<#
Find a Python 3.12+ interpreter for video-mover, installing one when it is missing.

setup.bat calls this only when there is no conda environment, no project .venv
and no conda base interpreter. Exactly one machine-readable line goes to stdout:

    PYTHON=<absolute path to python.exe>

Diagnostics go to stderr so setup.bat can parse stdout with for /f.
Install order: winget (Python.Python.3.13), then the python.org installer.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Keep in sync with README (Python 3.12+) and win_env.py (NEW_ENV_PYTHON).
$MinMinor = 12
$InstallVersion = '3.13'
$FallbackVersion = '3.13.17'

function Write-Diag([string]$Message) {
    [Console]::Error.WriteLine($Message)
}

function Get-PythonVersion([string]$Exe) {
    if ([string]::IsNullOrWhiteSpace($Exe)) { return $null }
    if ($Exe -like '*\WindowsApps\*') { return $null }  # Store alias stub, not a real python
    if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { return $null }
    try {
        $out = & $Exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    }
    catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    $text = (@($out) | Select-Object -Last 1)
    if (-not $text) { return $null }
    if ($text.Trim() -match '^(\d+)\.(\d+)$') {
        return @([int]$Matches[1], [int]$Matches[2])
    }
    return $null
}

function Test-Usable([string]$Exe) {
    $version = Get-PythonVersion $Exe
    if ($null -eq $version) { return $false }
    return ($version[0] -eq 3 -and $version[1] -ge $MinMinor)
}

function Get-Candidates {
    $list = New-Object System.Collections.Generic.List[string]
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $list.Add((Join-Path $repoRoot '.venv\Scripts\python.exe'))

    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $installed = & py -0p 2>$null
        }
        catch {
            $installed = @()
        }
        foreach ($line in @($installed)) {
            # "-V:3.13 *  D:\...\python.exe"
            if ($line -match '([A-Za-z]:\\.*?python\.exe)\s*$') {
                $list.Add($Matches[1])
            }
        }
    }

    try {
        $found = & where.exe python 2>$null
    }
    catch {
        $found = @()
    }
    foreach ($line in @($found)) {
        $candidate = $line.Trim()
        if ($candidate) { $list.Add($candidate) }
    }

    # Default per-user / per-machine install locations, used right after an
    # install because the current process PATH does not see them yet.
    foreach ($root in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $root) { continue }
        foreach ($name in @("Python$($InstallVersion.Replace('.', ''))", 'Python313', 'Python312')) {
            $list.Add((Join-Path $root "Programs\Python\$name\python.exe"))
            $list.Add((Join-Path $root "$name\python.exe"))
        }
    }
    return $list
}

function Find-UsablePython {
    foreach ($candidate in (Get-Candidates)) {
        if (Test-Usable $candidate) { return $candidate }
    }
    return $null
}

function Install-WithWinget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }

    Write-Diag "[bootstrap] Installing Python $InstallVersion with winget ..."
    $log = Join-Path $env:TEMP 'video-mover-winget.log'
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & winget install --id "Python.Python.$InstallVersion" -e --source winget `
            --silent --accept-package-agreements --accept-source-agreements *> $log
        $exitCode = $LASTEXITCODE
    }
    catch {
        Write-Diag "[bootstrap] winget failed: $($_.Exception.Message)"
        $exitCode = 1
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if (Test-Path -LiteralPath $log) {
        foreach ($line in (Get-Content -LiteralPath $log -Tail 20)) {
            Write-Diag "  $line"
        }
    }
    if ($exitCode -ne 0) {
        Write-Diag "[bootstrap] winget exited with code $exitCode"
    }
    return ($null -ne (Find-UsablePython))
}

function Install-FromPythonOrg {
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $arch = 'arm64' } else { $arch = 'amd64' }
    $url = "https://www.python.org/ftp/python/$FallbackVersion/python-$FallbackVersion-$arch.exe"
    $installer = Join-Path $env:TEMP "video-mover-python-$FallbackVersion-$arch.exe"

    Write-Diag "[bootstrap] Downloading $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    }
    catch {
        Write-Diag "[bootstrap] Download failed: $($_.Exception.Message)"
        return $false
    }

    Write-Diag '[bootstrap] Running the installer quietly (per-user, PrependPath) ...'
    $installerArgs = @(
        '/quiet',
        'InstallAllUsers=0',
        'PrependPath=1',
        'Include_launcher=1',
        'Include_test=0',
        'Include_doc=0'
    )
    try {
        $proc = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru
    }
    catch {
        Write-Diag "[bootstrap] Installer failed to start: $($_.Exception.Message)"
        return $false
    }
    if ($proc.ExitCode -ne 0) {
        Write-Diag "[bootstrap] Installer exited with code $($proc.ExitCode)"
    }
    return ($null -ne (Find-UsablePython))
}

$python = Find-UsablePython
if ($python) {
    Write-Output "PYTHON=$python"
    exit 0
}

Write-Diag "[bootstrap] No usable Python 3.12+ found; installing Python $InstallVersion."

if ((Install-WithWinget) -or (Install-FromPythonOrg)) {
    $python = Find-UsablePython
}

if (-not $python) {
    Write-Diag '[bootstrap] ERROR: could not install Python automatically.'
    Write-Diag '[bootstrap] Install Python 3.12+ from https://www.python.org/downloads/'
    Write-Diag '[bootstrap] (tick "Add python.exe to PATH"), then run setup.bat again.'
    exit 1
}

Write-Output "PYTHON=$python"
exit 0
