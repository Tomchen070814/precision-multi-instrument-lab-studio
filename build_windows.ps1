param(
    [switch]$CreateShortcuts,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$InstallLogRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "Precision Multi-Instrument Lab Studio\install_logs"
} else {
    Join-Path $ProjectRoot "install_logs"
}
New-Item -ItemType Directory -Path $InstallLogRoot -Force | Out-Null
$BuildLog = Join-Path $InstallLogRoot (
    "install_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss")
)
$TranscriptStarted = $false
try {
    Start-Transcript -Path $BuildLog -Force | Out-Null
    $TranscriptStarted = $true
} catch {
    Write-Warning "The installation transcript could not be started: $_"
}

try {
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the local Python environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv ".venv"
        if ($LASTEXITCODE -ne 0) {
            throw "Creating the Python environment with py.exe failed (exit $LASTEXITCODE)."
        }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv ".venv"
        if ($LASTEXITCODE -ne 0) {
            throw "Creating the Python environment with python.exe failed (exit $LASTEXITCODE)."
        }
    } else {
        throw "Python 3.10+ was not found. Install Python 3.11 x64 and enable Add Python to PATH."
    }
}

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PythonVersion = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) {
    throw "The local Python environment could not be started (exit $LASTEXITCODE)."
}
if ([version]$PythonVersion -lt [version]"3.10") {
    throw "Python 3.10+ is required. Found Python $PythonVersion."
}

Write-Host "Installing/updating dependencies..."
& $PythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Updating pip failed (exit $LASTEXITCODE)."
}
& $PythonExe -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Installing project dependencies failed (exit $LASTEXITCODE)."
}

Write-Host "Running static quality checks..."
& $PythonExe -m ruff check "src" "tests"
if ($LASTEXITCODE -ne 0) {
    throw "Static quality checks failed (exit $LASTEXITCODE)."
}

Write-Host "Running the complete test suite..."
& $PythonExe -m pytest
if ($LASTEXITCODE -ne 0) {
    throw "Automated tests failed (exit $LASTEXITCODE)."
}

if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}

Write-Host "Building the standalone Windows application..."
& $PythonExe -m PyInstaller --noconfirm --clean "3458A_Lab_Studio.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)."
}

$ExePath = Join-Path $ProjectRoot "dist\Precision-Multi-Instrument-Lab-Studio.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build finished without producing $ExePath"
}

$InstallRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "Programs\Precision Multi-Instrument Lab Studio"
} else {
    Join-Path $ProjectRoot "installed"
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
$InstalledExe = Join-Path $InstallRoot "Precision-Multi-Instrument-Lab-Studio.exe"
Copy-Item -Path $ExePath -Destination $InstalledExe -Force
if (-not (Test-Path $InstalledExe)) {
    throw "The application was built but could not be installed to $InstalledExe"
}

if ($CreateShortcuts) {
    $Shell = New-Object -ComObject WScript.Shell
    $ShortcutTargets = @(
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "Precision Multi-Instrument Lab Studio.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Programs")) "Precision Multi-Instrument Lab Studio.lnk")
    )
    foreach ($ShortcutPath in $ShortcutTargets) {
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $InstalledExe
        $Shortcut.WorkingDirectory = $InstallRoot
        $Shortcut.IconLocation = "$InstalledExe,0"
        $Shortcut.Description = "Precision multi-instrument acquisition and analysis"
        $Shortcut.Save()
    }
    Write-Host "Desktop and Start Menu shortcuts created." -ForegroundColor Green
}

Write-Host ""
Write-Host "Installation complete:" -ForegroundColor Green
Write-Host $InstalledExe -ForegroundColor Cyan
Write-Host "Installation log:" -ForegroundColor Green
Write-Host $BuildLog -ForegroundColor Cyan

if ($Launch) {
    Start-Process -FilePath $InstalledExe -WorkingDirectory $InstallRoot
}
} catch {
    Write-Host ""
    Write-Host "BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Installation log:" -ForegroundColor Yellow
    Write-Host $BuildLog -ForegroundColor Cyan
    throw
} finally {
    if ($TranscriptStarted) {
        try {
            Stop-Transcript | Out-Null
        } catch {
            # Preserve the original build result if transcript shutdown fails.
        }
    }
}
