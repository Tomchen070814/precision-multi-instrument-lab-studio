# Precision Multi-Instrument Lab Studio — Driver and GPIB Guide

## What the application actually requires

The application sends SCPI or native HP-IB commands through PyVISA. It normally
does **not** require a separate IVI driver for every multimeter.

For a physical instrument, install:

1. One working 64-bit VISA runtime.
2. The hardware driver that matches the USB-GPIB controller, when GPIB is used.

Do not configure several vendor VISA implementations as the primary VISA at the
same time. If more than one is installed, follow the vendors' side-by-side VISA
installation instructions.

## Official downloads

| Interface or situation | Required software | Official download |
| --- | --- | --- |
| NI GPIB-USB-HS / HS+ | NI-VISA and NI-488.2 | [NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) · [NI-488.2](https://www.ni.com/en/support/downloads/drivers/download.ni-488-2.html) |
| Keysight 82357A / 82357B | Keysight IO Libraries Suite | [Keysight IO Libraries Suite](https://www.keysight.com/us/en/lib/software-detail/computer-software/io-libraries-suite-downloads-2175637.html) |
| R&S USB/LAN instruments | R&S VISA, or another compatible primary VISA | [R&S VISA](https://www.rohde-schwarz.com/us/driver-pages/remote-control/3-visa-and-tools_231388.html) |
| Tektronix / Keithley USB/LAN instruments | TekVISA, or another compatible primary VISA | [TekVISA](https://www.tek.com/en/support/software/driver/tekvisa-connectivity-software-v5111) |
| Generic LAN/LXI instrument | One VISA runtime; no USB-GPIB driver | Use NI-VISA, Keysight IO Libraries, R&S VISA, or TekVISA |

## Self-check result meanings

| Popup category | Meaning | First action |
| --- | --- | --- |
| Driver problem | The VISA runtime cannot be loaded or discovery failed | Repair/install one 64-bit VISA runtime and restart Windows |
| GPIB controller not detected | VISA works, but no GPIB interface is visible | Check USB cable/power and install NI-488.2 or Keysight IO Libraries |
| GPIB address not found | The controller is visible, but the selected instrument address is absent | Match the front-panel GPIB address and rescan |
| No listener | The controller addressed the bus, but no device responded | Check address, power, cable locking, and duplicate addresses |
| Not controller-in-charge | Another controller owns the bus or System Controller is disabled | Close other apps/controllers and enable System Controller |
| Timeout | The resource opened but the identity query did not complete | Close interactive test panels and check interface/termination settings |
| Model mismatch | Communication works, but the returned identity is a different model | Select the correct model or VISA address |

## Recommended verification

1. Confirm the interface in NI MAX or Keysight Connection Expert.
2. Confirm the instrument resource, such as `GPIB0::22::INSTR`.
3. Query `ID?` for a Keysight 3458A, or `*IDN?` for SCPI instruments.
4. Close the vendor interactive test panel before starting acquisition.
5. Run **Self-check** beside the resource field in the application.
