# PrecisionLab .NET 10 migration

This directory contains the isolated C# rewrite of the Python v0.5.2
application:

- .NET 10 LTS, WPF and CommunityToolkit MVVM;
- an independent acquisition service connected through versioned Named Pipes;
- A/B/C acquisition, deterministic twins and 14 live-driver profiles;
- native 3458A HP-IB/burst and Fluke 8508A IEEE-488 implementations;
- vendor-neutral VISA.NET discovery and identity verification;
- bounded backpressure and SQLite WAL commit-before-display persistence;
- recovery and historical-window queries;
- statistics, drift, FFT amplitude, Welch ASD and Allan deviation;
- CSV import/export, diagnostic ZIP and Chinese/English resources;
- ScottPlot live trend, memory metrics and a per-user Windows installer script.

## Build

```powershell
dotnet restore PrecisionLab.slnx
dotnet build PrecisionLab.slnx -c Release
dotnet test PrecisionLab.slnx -c Release --no-build
```

The GitHub Windows workflow additionally publishes both executables and runs an
isolated two-process detach/reconnect/forced-kill recovery test before creating
the ZIP.

## Run

```powershell
dotnet run --project src/PrecisionLab.Service -- --data-dir "$env:LOCALAPPDATA\PrecisionLab"
dotnet run --project src/PrecisionLab.Desktop.Wpf
```

Physical resources need a compatible vendor VISA 7.4+ runtime. Digital twins
use `SIM::` resources and do not need VISA.

See [ARCHITECTURE.md](ARCHITECTURE.md),
[MIGRATION_STATUS.md](MIGRATION_STATUS.md), and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
