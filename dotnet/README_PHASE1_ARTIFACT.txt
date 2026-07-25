PrecisionLab .NET 10 phase-one checkpoint
==========================================

Requirements
------------
- Windows 10 or Windows 11, x64
- .NET 10 Desktop Runtime

Start order
-----------
1. Run PrecisionLab.Service.exe.
2. Leave the service window running.
3. Run PrecisionLab.Desktop.Wpf.exe.
4. Use the WPF client to start and stop channels A, B and C.

Data
----
Phase-one JSON Lines checkpoints are written to:

%LOCALAPPDATA%\PrecisionLab\Sessions

Important scope
---------------
- This checkpoint uses SIM:: digital-twin resources.
- Live VISA/GPIB resources intentionally fail closed.
- The 3458A, 8508A, 8588A and SCPI live drivers are not yet enabled.
- Closing the WPF client does not stop the independent acquisition service.
- Stop acquisition in the UI, then close the service window when finished.

The production Python v0.5.2 application remains unchanged on the main branch.
