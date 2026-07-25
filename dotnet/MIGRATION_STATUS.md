# Migration status

| Capability | Phase-one status | Next acceptance gate |
|---|---|---|
| .NET 10 / WPF / MVVM | Implemented | Windows render smoke test |
| Independent acquisition process | Implemented | Kill/reconnect test |
| A/B/C digital twins | Implemented and core-tested | 24-hour soak test |
| Durable raw-data boundary | Per-point flushed JSONL checkpoint | SQLite WAL recovery test |
| 14-model catalog | Implemented and count-tested | Per-model capability review |
| 3458A HP-IB | Interface only | Command transcript + real instrument |
| 8508A IEEE-488 | Interface only | Command transcript + real instrument |
| 8588A specialized SCPI | Interface only | Command transcript + real instrument |
| Other SCPI profiles | Catalog only | Per-model transcript tests |
| Trend display | Basic ScottPlot adapter | multi-unit axes and windowed requery |
| Top memory monitor | System RAM + UI + service working set | long-run leak thresholds |
| FFT/ASD/Allan/statistics | Not migrated | Python/C# golden vectors |
| CSV and diagnostic report | Not migrated | round-trip fixtures |
| Chinese/English UI | Not migrated | `.resx` completeness test |
| Windows installer | Not migrated | clean-VM install test |

## Acceptance checklist

- [x] Independent WPF and acquisition-service processes.
- [x] Versioned, bounded control and data IPC.
- [x] A/B/C shared-release digital twins.
- [x] Lossless bounded raw pipeline with wait backpressure.
- [x] Durable flush before lossy display publication.
- [x] Non-simulated resources fail closed.
- [x] Core protocol, catalog, driver and pipeline tests.
- [x] Windows CI and downloadable checkpoint artifact definition.
- [ ] Windows CI compile and tests confirmed.
- [ ] Windows desktop render inspection.
- [ ] UI-kill/service-continuation and reconnect test.
- [ ] Long-running memory and persistence soak test.
- [ ] 34470A/3458A real-hardware verification.

Python v0.5.2 remains the functional reference on `main` and is not deleted or
replaced. The incomplete pre-reconciliation branch state is preserved at
`backup/dotnet10-incomplete-20260725`.
