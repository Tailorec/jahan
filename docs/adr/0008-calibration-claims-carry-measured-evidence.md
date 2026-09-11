# Calibration claims carry measured evidence above fixed floors

A trust level above uncalibrated requires a calibration reference that pins the benchmark report and the human study by content hash and records the measured distribution similarity and rank attainment. Both must reach 0.80 — the same bar the engine's ordinal distribution gate and reference-set rank-stability checks hold themselves to. A prospective validation must also record that its prediction was registered before its outcome was observed.

Before this, a reference was two identifiers and a timestamp, so claiming calibration cost two arbitrary strings. Fabrication is still possible — but it now means inventing hashes that can be checked against artifacts and measurements that must clear the floors, rather than attaching a label.

## Consequences

The floors are fixed constants rather than carried with each reference, so a claim cannot lower its own bar. Nothing in the repository constructs a reference, and a test scans the package to keep it that way.
