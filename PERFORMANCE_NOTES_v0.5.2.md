# v0.5.2 Performance Notes

These measurements are development-container microbenchmarks, not guaranteed
Windows hardware performance.

## One-million-point trend payload

The old refresh path converted and passed the complete list every refresh. The
new path selects at most 20,000 display samples while retaining the first and
last sample.

| Operation | Measured time |
| --- | ---: |
| Convert all 1,000,000 Python values to NumPy | 27.620 ms |
| Build bounded 20,000-point display payload | 2.179 ms |
| Plot payload reduction | 50.0× |

The display selection is independent of analysis and durable storage. FFT,
statistics and the crash-recovery CSV continue to use received samples.
When the operator zooms the X axis, the visible timestamp interval is located
with binary search and resampled from the complete session. A local interval of
20,000 samples or fewer is therefore rendered point-for-point.

## Timestamp storage

For 100,000 timestamps:

| Representation | Approximate memory |
| --- | ---: |
| Python `datetime` object list | 5,600,984 bytes |
| 64-bit epoch array | 816,640 bytes |
| Reduction | 6.9× |

## Refresh scheduling

- Trend: maximum 10 refreshes per second.
- Analysis: approximately 1.1 refreshes per second.
- No refresh is scheduled when no new sample has arrived.
- System/process memory monitoring: once per second.
- VISA scans and explicit connection self-checks run outside the Qt UI thread.
