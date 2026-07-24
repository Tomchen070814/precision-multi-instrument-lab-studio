# Precision Multi-Instrument Lab Studio v0.5.2

## Connection self-check

- A channel now runs a VISA/GPIB preflight before opening a physical instrument.
- The UI distinguishes a missing VISA runtime, failed VISA discovery, missing
  GPIB controller, missing GPIB address, no listener, controller-in-charge
  failure, timeout, busy resource, lost connection, and model mismatch.
- Every channel has a non-blocking **Self-check** button beside Scan.
- VISA resource discovery also runs in a background thread.
- Connection failures open a bilingual diagnostic dialog with concrete actions,
  detected backend/resources, the original VISA error, and official download
  links.
- Connection diagnoses are retained in the persistent log and diagnostic ZIP.

## Data identity

- The metric area now names the selected channel, model, function, resource, and
  unit.
- Every metric card is prefixed with its source channel.
- Trend legends, hover readouts, fixed marks, analysis banners, per-channel
  readouts, autosave rows, and diagnostic snapshots retain channel identity.
- FFT, ASD, histogram, Allan and drift legends include channel, model and
  resource instead of generic `Channel A/B/C` labels.

## Performance and memory

- Live trend refresh is capped at 10 FPS and analysis refresh at roughly 1 FPS.
- Refreshes run only when new samples arrive.
- Trend payloads are bounded to 20,000 display points per channel while complete
  samples remain available to analysis and durable autosave.
- After X-axis or rectangle zoom, the visible wall-clock window is selected
  again from the complete timestamp series, restoring every local sample when
  that window contains no more than 20,000 points.
- Multi-channel axes and legends are rebuilt once per refresh batch.
- Wall-clock timestamps use compact 64-bit epoch storage.
- The header displays live whole-system RAM usage and application working-set
  memory once per second.
- The memory snapshot is included in exported diagnostic reports.

## Independent trend-axis zoom

- Dedicated X zoom-in/out controls change only the wall-clock range.
- Dedicated Y zoom-in/out controls can target all Y axes or one physical unit.
- Mixed V/Ω/A/Hz/s axes retain independent scales.
- Mouse-wheel navigation, rectangle zoom and Reset view remain available.

## Verification

- Ruff static checks: zero findings.
- Automated tests: 69 passed.
- One full Qt rendering group is skipped in the Linux packaging container
  because `libEGL.so.1` is unavailable; the Windows installer reruns it before
  building the executable.

## Driver downloads

See `DRIVER_INSTALL_GUIDE.md`. All links point to NI, Keysight, Rohde & Schwarz,
or Tektronix official pages.
