$ErrorActionPreference = "Stop"
$installDirectory = Join-Path $env:LOCALAPPDATA "Programs\PrecisionLab"
$programs = [Environment]::GetFolderPath("Programs")
$shortcut = Join-Path $programs "PrecisionLab.lnk"

Get-Process "PrecisionLab.Desktop.Wpf", "PrecisionLab.Service" -ErrorAction SilentlyContinue |
    Stop-Process -Force
if (Test-Path $shortcut) {
    Remove-Item $shortcut -Force
}
if (Test-Path $installDirectory) {
    Remove-Item $installDirectory -Recurse -Force
}

Write-Host "PrecisionLab was removed. Measurement data under LocalAppData\PrecisionLab was preserved."
