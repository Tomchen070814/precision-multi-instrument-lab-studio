# Precision Multi-Instrument Lab Studio

[简体中文](README.md) | **English**

A bilingual, multi-device precision acquisition and analysis platform for Windows.
Channels A and B are enabled by default, while Channel C is an optional third
instrument channel. Each channel can independently select from 14 instruments by
10 manufacturers and has its own VISA session, acquisition thread, measurement
function, unit, timeline, and crash-resistant autosave file. Every supported
instrument also includes a digital-twin demo mode for use without physical
hardware.

The UI language can be switched instantly from the top-right corner. The selected
language, window geometry, panel widths, and Channel C state are remembered
automatically.

> The 3458A uses its native HP-IB command set, and the 8508A uses its native
> IEEE-488 command set. Neither is treated as a generic SCPI instrument. The
> other 12 models use model-specific SCPI profiles. Every real-device connection
> queries and strictly verifies instrument identity, and the three protocol
> families are isolated from one another.

Current release: **v0.5.2**. This release builds on the 14-model architecture in
v0.5.1 with connection self-tests, layered driver/GPIB diagnostics, mandatory
data-source identification, real-time memory monitoring, and long-session
performance improvements.

## Implemented Features

- Channels A and B are enabled by default; Channel C can be enabled at any time.
- A/B/C can independently select any of 14 models from 10 manufacturers, using
  either a digital twin or a real VISA resource.
- Before starting a real-device channel, the application automatically checks
  VISA, the GPIB controller, bus, address, and model identity.
- Driver, GPIB, address, timeout, resource-busy, and model-mismatch failures are
  reported separately instead of appearing as a generic connection error.
- Each channel has an independent **Connection Self-Test** button, and error
  dialogs link directly to official driver download pages.
- The model catalog includes Keysight, Fluke, Keithley, Rohde & Schwarz, Rigol,
  Siglent, GW Instek, Hioki, Yokogawa, and Picotest.
- SCPI models can use USB, LAN, serial, or GPIB resources recognized by VISA.
  The 3458A and 8508A are restricted to GPIB.
- Each instrument has independent settings for address, function, range, NPLC,
  digits, Autozero, and sample interval.
- Instruments can be started or stopped individually, or synchronized in any
  A+B, A+C, B+C, or A+B+C combination.
- Switch between 中文 and English instantly without restarting or losing
  acquisition settings.
- Language, window size, panel widths, and Channel C state are saved
  automatically.
- Precision mode supports continuous acquisition or a fixed sample count, such
  as 20,000 readings, with automatic stop at the target.
- Synchronized start applies only to selected channels: each instrument is
  connected and configured first, then all selected acquisition threads are
  released together.
- Multi-channel live readings, independent status indicators, and a real
  date-time X axis.
- The top bar updates system RAM utilization and application working-set memory
  once per second.
- Every metric card identifies its source channel; the metric area always shows
  channel, model, function, resource address, and unit.
- Different physical quantities such as V, Ω, and A receive independent Y axes;
  channels with the same unit share an axis automatically.
- Hover readouts and pinned markers for A/B/C show the correct channel, value,
  unit, and millisecond timestamp.
- Drag-select a time range to zoom while independently scaling each visible
  physical-quantity axis.
- X-axis zoom and Y-axis zoom are independently controllable; Y zoom can target
  all axes or only V, Ω, A, Hz, or s.
- After time-axis zoom, the visible segment is rebuilt from the complete session
  data so short windows recover point-level detail.
- Minimum and maximum values are visible directly in the main monitoring area.
- FFT/ASD, statistical distributions, Allan stability, and drift/temperature
  analysis can show all enabled channels.
- Channel colors are fixed for consistent identification: A cyan, B purple, and
  C green. Single-channel views are also available.
- Multi-channel FFT/ASD uses each channel's own sample rate. Histograms use shared
  bins with transparent overlays.
- A/B/C each display their own statistical summary, Allan curve, drift fit, and
  temperature coefficient.
- Analysis pages continuously display the actual VISA address, sample count, and
  unit for every enabled instrument.
- Mixed-unit trend plots are supported. FFT/ASD/Allan analysis follows the
  selected channel to prevent invalid unit mixing.
- Export a single-channel CSV or a combined A+B/A+B+C CSV that preserves each
  channel's independent time axis.
- Persistent rotating logs survive shutdowns and crashes. Each file is limited
  to 5 MB, with up to four generations retained.
- In precision mode, every received sample is immediately appended to CSV and
  committed with `flush + fsync`.
- If VISA/GPIB disconnects, Windows crashes, or the process terminates
  unexpectedly, committed samples remain available in a directly readable
  recovery file.
- Incomplete recovery files are detected at startup, and the autosave directory
  can be opened directly from the right-side panel.
- One-click ZIP diagnostic report containing an HTML summary, JSON state, current
  events, and historical error logs.
- Diagnostic reports exclude measurement samples to avoid unintentionally
  copying large or sensitive test data.
- Neutral dark UI with restrained decoration and stronger visual hierarchy for
  channels, states, and primary actions.
- Prevents multiple threads from accidentally connecting to the same VISA
  resource.
- VISA operations on a shared GPIB controller use common bus arbitration to
  avoid thread contention.
- In mixed NI/Keysight VISA environments, a failed `viClear` does not end the
  connection attempt; communication is verified with `ID?`.
- VISA scanning is filtered by model: the 3458A and 8508A show only GPIB
  resources, while SCPI models show VISA-recognized USB/LAN/serial/GPIB
  instrument resources.
- Multi-instrument scans remove stale selections, assign resources clearly to
  A/B/C, and record both scan results and actual addresses in the event log.
- Trend charts refresh at up to 10 FPS and display at most 20,000 points per
  channel; complete data remains available for analysis and storage.
- FFT/ASD/statistics/Allan views refresh about once per second only when new data
  arrives, avoiding redundant full-session computation.
- Timestamps use compact 64-bit storage to reduce memory use during long
  multi-channel sessions.
- `ID?`, `REV?`, `OPT?`, and `LINE?` identity information for the 3458A.
- DCV, ACV, AC+DCV, 2-wire/4-wire resistance, DCI, ACI, AC+DCI, frequency, and
  period functions according to model capabilities.
- 3.5–8.5 digits, NPLC 0–1000, and Autozero where supported.
- `TRIG SGL` precision continuous acquisition for the 3458A.
- DSDC/DSAC high-speed burst acquisition using the 3458A timer and reading
  memory.
- Periodic internal-temperature acquisition with `TEMP?`.
- Crosshair cursor, wheel zoom, and click-to-pin exact value labels.
- Mean, standard deviation, peak-to-peak, RMS, coefficient of variation in ppm,
  and linear drift.
- FFT, amplitude spectrum, and ASD in `unit/√Hz`.
- Histogram, MAD outlier filtering, and overlapping Allan deviation.
- Automatic X/Y column detection when importing CSV files.

## Windows Multi-Instrument Connections

### Keysight 3458A

Requirements:

1. Two or three 3458A instruments.
2. One to three GPIB interfaces capable of acting as System Controller.
3. Instruments may share one GPIB bus or use separate GPIB-USB controllers, for
   example `GPIB0::21::INSTR`, `GPIB1::22::INSTR`, and
   `GPIB2::23::INSTR`.
4. Windows 10/11 x64.
5. A matching 64-bit VISA/GPIB driver for the controller.

Instruments sharing one GPIB bus must use different Primary Addresses. The
software defaults match the current hardware arrangement:

```text
3458A A = GPIB0::21::INSTR
3458A B = GPIB1::22::INSTR
3458A C = GPIB2::23::INSTR  (reserved; disabled by default)
```

Set the address from the 3458A front panel. The real addresses do not have to be
22 and 23, but they must never be identical on the same bus.

### SCPI Models

After selecting a SCPI model in any channel, precision acquisition can use a USB,
LAN/LXI, serial, or GPIB resource recognized by NI MAX, Keysight Connection
Expert, or the manufacturer's VISA implementation. The application first sends
`*IDN?` and verifies that the returned identity matches the selected model. It
then generates commands from that model's profile. A typical command structure
is:

```text
*IDN?
CONF:<function>
SENS:<function>:RANG:AUTO ON       (when auto range is selected)
SENS:<function>:NPLC <value>       (for functions supporting NPLC)
SENS:<function>:ZERO:AUTO <mode>   (for functions supporting Autozero)
TRIG:SOUR IMM
SAMP:COUN 1
READ?
```

Differences among manufacturers in `CONF`/`SENS:FUNC`, NPLC, and Autozero syntax
are handled by model-specific profiles. The same command string is never blindly
sent to every instrument. See `SUPPORTED_INSTRUMENTS.md` for model capabilities,
functions, and first-hardware-validation boundaries. Manufacturer-specific
high-speed digitizing modes for SCPI models are intentionally disabled until
verified on real hardware; the 3458A burst implementation is not reused for
unrelated instruments.

### Fluke 8508A

The 8508A accepts only GPIB VISA resources and uses a dedicated IEEE-488 driver.
The application does not send `CONF`, `SENS`, or `READ?`. Instead, it uses the
official `DCV`, `ACV`, `OHMS`, `DCI`, `ACI`, `TRG_SRCE EXT`, and `X?` commands.
The 8508A does not accept NPLC directly; the UI's NPLC setting is mapped to the
nearest supported `RESL/FAST` integration combination, and the Autozero control
is disabled.

### NI GPIB-USB-HS

1. Install NI-488.2 and 64-bit NI-VISA, then restart Windows.
2. In NI MAX, expand `Devices and Interfaces > GPIB0 (GPIB-USB-HS)`.
3. Select **Scan for Instruments** and confirm that every physical instrument
   appears as a GPIB resource.
4. Send `ID?` to each 3458A address. Do not send `*IDN?`.
5. Close the NI MAX communication window before opening this application and
   selecting **Scan**.

When starting a real channel, the application first attempts VISA Device Clear.
If a mixed VISA environment returns `VI_ERROR_NLISTENERS` for `viClear`, this
alone does not mark the instrument offline. The application continues by sending
the native 3458A `ID?` command and reports failure only if normal communication
also receives no response.

### Keysight USB-GPIB

When using an 82357B/82357C, confirm the GPIB interface and instrument resources
in Keysight Connection Expert. If scanning shows only `USB0::...::INSTR`, do not
treat that resource as the 3458A. The application still requires an address in
the form `GPIB0::<address>::INSTR`.

## Independent and Synchronized Start

- A channel's button on its A/B/C tab controls only that instrument.
- Select any A+B, A+C, B+C, or A+B+C combination under **Synchronized Start**.
  The button label reflects the actual combination selected.
- With one channel selected, synchronized start behaves as a normal
  single-channel start. Running channels that are not selected are not started,
  stopped, or cleared.
- In continuous precision mode, set **Acquisition Length** to a fixed sample
  count and enter independent targets for A, B, and C. Live cards display
  collected/target counts.
- During synchronized acquisition, each channel stops independently at its own
  target. One completed instrument does not stop the others.
- While one instrument is running, another can still be started independently
  from its own tab; start times do not need to match.
- If all selected channels are stopped, synchronized start connects and
  configures every selected instrument before releasing acquisition.
- Synchronized start provides near-simultaneous software start from the PC. It is
  affected by Windows scheduling and serial GPIB transfers and is not equivalent
  to microsecond-level simultaneous sampling. Strict phase synchronization
  requires an external trigger or dedicated hardware trigger system.
- Each channel owns an independent VISA session and acquisition state. If
  multiple channels share a GPIB controller, bus transfers are serialized by the
  application, which is normal GPIB behavior.

## Run from Source

Python 3.11 x64 is recommended:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
python run.py
```

To preview the interface without instruments, keep every channel in **Demo
Mode**. No VISA driver is required.

## Install Once on Windows

After extracting a new release, run this file once:

```text
INSTALL_ONCE_WINDOWS.bat
```

It installs project dependencies, runs the complete test suite, builds a
single-file application, and creates:

```text
Desktop shortcut: Precision Multi-Instrument Lab Studio
Start Menu shortcut: Precision Multi-Instrument Lab Studio
Application: %LOCALAPPDATA%\Programs\Precision Multi-Instrument Lab Studio\
             Precision-Multi-Instrument-Lab-Studio.exe
```

After installation, launch from the desktop shortcut, Start Menu, or EXE. Do not
run the BAT file again. Installed shortcuts do not depend on the extracted ZIP
directory, so that folder can be moved or deleted after a successful upgrade.
For compatibility with older workflows, `START_HERE_WINDOWS.bat` launches the
installed EXE directly when it is present.

The installer preserves a complete log at:

```text
%LOCALAPPDATA%\Precision Multi-Instrument Lab Studio\install_logs
```

If dependency installation, tests, or packaging fails before the EXE is created,
send the newest `install_*.log` together with a screenshot. The in-application
diagnostic report is not required for installer failures.

The EXE includes Python and UI dependencies. Real GPIB communication still
requires NI-VISA/NI-488.2 or Keysight IO Libraries to be installed on the
computer. Drivers are installed only once. Official download links and failure
categories are listed in `DRIVER_INSTALL_GUIDE.md`.

## Logs and Diagnostic Reports

After startup, the application continuously writes the following information to
rotating logs in the local application-data directory:

- Startup, shutdown, language changes, and user actions.
- Model, actual VISA address, connection identity, and acquisition settings for
  every instrument.
- VISA `clear` warnings and connection/configuration/acquisition failures.
- Complete exception traces from acquisition threads.
- CSV import/export errors and uncaught application exceptions.

Each log file is limited to 5 MB. Three backups are retained, for a maximum of
four generations including the current file, so long sessions cannot grow disk
usage without limit. After an issue—even after restarting the application—select
**Export Diagnostic Report** in the right-side Events area. The generated ZIP
contains:

```text
diagnostic.html        Human-readable summary
diagnostic.json        Structured system, application, and channel state
events.txt             Events currently shown in the window
logs/application.log*  Current and historical rotating logs
README.txt             Report contents and privacy notes
```

The report records A/B/C enablement, synchronized-start selection, instrument
addresses, function, range, NPLC, sample counts, the latest connection
diagnostic, system RAM, and application memory. It does not package CSV/Excel
files or measurement samples held in memory.

## 3458A Acquisition Strategy

### Precision Continuous Mode

Each channel independently executes:

```text
PRESET NORM
END ALWAYS
OFORMAT ASCII
DCV <range>
NPLC <value>
NDIG <3..8>
AZERO <ON|OFF|ONCE>
TRIG SGL
```

If the requested sample interval is shorter than `NPLC / line_frequency`, the
actual rate is limited by the instrument's integration time.

### High-Speed Burst Mode

The application uses `APER`, `NRDGS ... TIMER`, `TIMER`, `MEM FIFO`, and `RMEM`
to acquire timed readings inside the 3458A and then transfer the block to the PC.
The GUI limits a burst to 148,000 readings, a minimum 10 µs interval, and a
minimum 500 ns aperture.

Recommended first real-device test:

- 1,000 readings
- 1 ms interval
- 100 µs APER
- 10 V range

High-speed mode must be validated on the specific 3458A, firmware, and GPIB
controller combination before production use.

## CSV Format

Single-channel export:

```text
timestamp_iso,elapsed_s,reading (V),internal_temperature_c
```

Multi-channel export does not assume perfectly aligned samples and preserves a
separate timeline for each channel:

```text
timestamp_A,elapsed_A_s,reading_A (...),temperature_A_c,
timestamp_B,elapsed_B_s,reading_B (...),temperature_B_c
timestamp_C,elapsed_C_s,reading_C (...),temperature_C_c
```

Import automatically detects common time and reading columns. If a file contains
only one numeric column, sample index is used as the X axis.

## Tests

```powershell
pip install -e .[dev]
ruff check src tests
pytest
```

## Project Structure

```text
src/hp3458a_studio/
  drivers.py          3458A VISA driver and digital twin
  channel_groups.py   A/B/C start-combination parsing
  i18n.py             Chinese/English UI text and function names
  instrument_panel.py Independent A/B/C instrument settings
  workers.py          Background acquisition and synchronized-start gating
  analysis.py         FFT, ASD, Allan deviation, statistics, and drift
  csv_io.py           Single/multi-channel CSV import and export
  diagnostics.py      Persistent rotating logs and ZIP diagnostic reports
  widgets.py          Interactive multi-channel charts
  main_window.py      Multi-channel UI and session control
```
