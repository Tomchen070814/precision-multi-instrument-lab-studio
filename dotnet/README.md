# PrecisionLab .NET 10 migration

This directory is the first executable checkpoint of the migration from the
Python v0.5.2 application. It is intentionally isolated from the production
Python entry point.

## Implemented in phase 1

- .NET 10 solution split into Domain, Contracts, Driver, Acquisition, Service,
  and WPF projects
- independent `PrecisionLab.Service.exe` process
- versioned, length-prefixed control pipe plus fixed-length binary measurement
  frames
- A/B/C channel state machines with a shared release gate
- bounded, backpressured durable-data pipeline
- per-point write-through disk flush before display publication
- drop-oldest display subscribers that cannot block persistence
- recoverable JSON Lines session checkpoint
- all 14 v0.5.2 instrument identities and explicit protocol boundaries
- digital-twin drivers for every catalog model
- non-simulated resources fail closed instead of receiving generic commands
- WPF/MVVM client using CommunityToolkit.Mvvm
- top-bar system RAM, UI working set and acquisition-service working set
- ScottPlot adapter refreshing at 10 FPS and retaining at most 20,000 display
  points per channel
- Windows CI, core protocol/acquisition tests and a downloadable checkpoint
  artifact

## Deliberately not claimed yet

- live VISA.NET, 3458A HP-IB, 8508A IEEE-488, 8588A specialized SCPI or profile
  SCPI communication
- SQLite WAL session format and crash-recovery UI
- full v0.5.2 statistics, FFT/ASD, Allan deviation, marks, CSV, diagnostics,
  localization and installer
- hardware synchronization or Windows instrument validation

Those items remain on the migration checklist. A non-`SIM::` resource fails
closed until the relevant live driver passes transcript and hardware tests.

## Run the checkpoint on Windows

Install the .NET 10 SDK, then run:

```powershell
cd dotnet
.\RUN_PHASE1_WINDOWS.ps1
```

The script restores, builds and tests the complete solution, starts the
acquisition service, and then starts the WPF client. Raw phase-one checkpoints
are written under:

```text
%LOCALAPPDATA%\PrecisionLab\Sessions
```

Closing WPF does not stop the independent service. Stop acquisition in the UI
before closing; process packaging and service lifecycle controls are phase-two
work.

See [ARCHITECTURE.md](ARCHITECTURE.md),
[MIGRATION_STATUS.md](MIGRATION_STATUS.md), and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
