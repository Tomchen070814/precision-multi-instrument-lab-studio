# Migration status

| Capability | Migrated status | Acceptance evidence |
|---|---|---|
| .NET 10 / WPF / MVVM | Implemented | Windows Release build + headless WPF load |
| Independent acquisition process | Implemented | client detach/reconnect smoke |
| A/B/C synchronized release | Implemented | three-channel process smoke |
| SQLite WAL recovery | Implemented | per-point invariant + forced-kill restart |
| 14-model catalog | Implemented | catalog and capability tests |
| 3458A HP-IB + burst | Implemented | transcript tests; real instrument still required |
| 8508A IEEE-488 | Implemented | transcript tests; real instrument still required |
| 8588A and 11 other SCPI profiles | Implemented | per-model transcript tests |
| Trend display | Implemented | ScottPlot 10 FPS adapter, zoom/pan and bounded display |
| FFT/ASD/Allan/statistics | Implemented | deterministic golden-vector tests |
| CSV import/export | Implemented | SQLite → CSV → importer round trip |
| Diagnostic ZIP | Implemented | archive/content test; samples excluded |
| Chinese/English UI | Implemented | paired `.resx` resources and runtime switch |
| Portable/per-user package | Implemented | CI ZIP plus install/uninstall scripts |

## Automated isolation gate

The Windows CI job performs the following against published executables:

- starts `PrecisionLab.Service.exe` with a unique pipe namespace and temporary
  data directory;
- starts A/B/C digital twins and confirms durable display data;
- terminates the first client while acquisition is running;
- loads the published WPF executable in headless smoke mode;
- reconnects with a fresh client and verifies 60 committed points per channel;
- requeries all 180 stored samples and exports CSV and diagnostic ZIP;
- starts a continuous session, force-kills the service, reopens the same
  database, and verifies an `Interrupted` session with committed data.

## Hardware acceptance still required

Automated transcripts prove command selection, identity rejection and protocol
separation, but cannot prove behavior of an instrument that is not physically
connected. Before calling a specific unit “hardware verified,” perform:

- discovery and identity match through the installed vendor VISA;
- configuration/read for every intended function and range;
- cancellation during a blocked read;
- cable removal and reconnection;
- shared-controller test with at least two GPIB instruments;
- 3458A burst count, timing and memory cleanup;
- comparison against the Python v0.5.2 transcript and a known reference signal.

Python v0.5.2 remains unchanged on `main`. The exact source state is also
preserved on `backup/python-v0.5.2`; the previously saved v0.5.2 Windows ZIP is
the binary rollback copy.
