$ErrorActionPreference = "Stop"

$solutionRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $solutionRoot
try {
    dotnet restore .\PrecisionLab.slnx
    dotnet build .\PrecisionLab.slnx --configuration Debug --no-restore
    dotnet test .\PrecisionLab.slnx --configuration Debug --no-build

    $service = Join-Path $solutionRoot "src\PrecisionLab.Service\bin\Debug\net10.0-windows\PrecisionLab.Service.exe"
    $desktop = Join-Path $solutionRoot "src\PrecisionLab.Desktop.Wpf\bin\Debug\net10.0-windows\PrecisionLab.Desktop.Wpf.exe"
    Start-Process -FilePath $service
    Start-Sleep -Milliseconds 700
    Start-Process -FilePath $desktop
}
finally {
    Pop-Location
}
