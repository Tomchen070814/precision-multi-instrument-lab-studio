# Migration status

| Capability | Phase-one status | Next acceptance gate |
|---|---|---|
| .NET 10 / WPF / MVVM | Implemented | Windows render smoke test |
| Independent acquisition process | Implemented | Kill/reconnect test |
| A/B/C digital twins | Implemented | 24-hour soak test |
| Durable raw-data boundary | JSONL checkpoint | SQLite WAL recovery test |
| 14-model catalog | Implemented | Per-model capability matrix |
| 3458A HP-IB | Interface only | Command transcript + real instrument |
| 8508A IEEE-488 | Interface only | Command transcript + real instrument |
| 12 SCPI profiles | Catalog only | Per-model transcript tests |
| Trend display | Basic ScottPlot adapter | multi-unit axes and windowed requery |
| FFT/ASD/Allan/statistics | Not migrated | Python/C# golden vectors |
| CSV and diagnostic report | Not migrated | round-trip fixtures |
| Chinese/English UI | Not migrated | resource completeness test |
| Windows installer | Not migrated | clean-VM install test |

Python v0.5.2 remains the functional reference and is not deleted or replaced.
