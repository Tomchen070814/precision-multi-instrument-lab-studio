$ErrorActionPreference = "Stop"
$sourceDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$installDirectory = Join-Path $env:LOCALAPPDATA "Programs\PrecisionLab"

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem $sourceDirectory |
    Where-Object { $_.Name -notin @("INSTALL_WINDOWS.ps1", "UNINSTALL_WINDOWS.ps1") } |
    Copy-Item -Destination $installDirectory -Recurse -Force
Copy-Item (Join-Path $sourceDirectory "UNINSTALL_WINDOWS.ps1") $installDirectory -Force

$shell = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath("Programs")
$shortcut = $shell.CreateShortcut((Join-Path $programs "PrecisionLab.lnk"))
$shortcut.TargetPath = Join-Path $installDirectory "PrecisionLab.Desktop.Wpf.exe"
$shortcut.WorkingDirectory = $installDirectory
$shortcut.Save()

Write-Host "PrecisionLab installed for the current user: $installDirectory"
