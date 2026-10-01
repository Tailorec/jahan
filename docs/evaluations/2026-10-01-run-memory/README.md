# Evaluation: where a study's memory goes, and what the float32 change saved

*2026-10-01 · fake studies (stub models, Titan-width 1,024-dimension embeddings) · all three channels · 6 ticks ·
a wave every 2 ticks · each run alone under `systemd-run … MemoryMax=8G`*

## The question

How much memory does a study need per persona, and does storing live embeddings as packed float32 and sharing
persona state across turn jobs (commits `cabecce`, `c5eb7a1`, `6f14584`) bring 20,000 personas within reach?

## Results stay identical

The same 200-persona study, same run id, before and after the three commits: `trace-summary.json` (trace hash
`f73598eb…`), `report.json` and `digest.json` are byte-for-byte equal. Embedding endpoints answer in float32, so
packing loses nothing; ranking vectors are float32 arrays whose values iterate as the same Python floats.

## Memory by phase, 400 personas

Resident memory sampled every 2 s, maximum per closed tick:

| | tick 1 | tick 2 | tick 3 | tick 4 | after tick 5 (analysis) |
|---|---:|---:|---:|---:|---:|
| before (`bf132f9`) | 270 MB | 377 MB | 590 MB | 655 MB | 1,324 MB |
| after (`6f14584`) | 227 MB | 275 MB | 334 MB | 380 MB | 1,185 MB |

The simulation itself now grows about 50 MB a tick at 400 personas instead of about 130 MB: roughly 40% less
memory by tick 4, and 2.5 times slower growth. The estimate of a 5–10× cut was wrong: live embeddings were never
the bulk. Python objects at the end of the simulation came to about 100 MB for 100 personas, all told.

## The peak is the analysis after the simulation

Measured step by step on the finished 400-persona run (40,086 events):

| Step | Peak memory | Time |
|---|---:|---:|
| read the world's finished record, strictly validated | 691 MB | — |
| cluster objections (similarity between every pair of verbatims) | 1,354 MB | 12 s |
| author findings | 1,354 MB | 28 s |
| trace summary | 1,354 MB | 346 s |

Reading the record holds every event at once (about 1.6 MB a persona); clustering compares every verbatim with
every other, so it grows with the square of the population; the trace summary is slow rather than large.

## What it means for 20,000 personas, all three channels

Extrapolated linearly from 400, so an estimate:

- **The simulation:** about 19 GB after the change (about 33 GB before) — the turn-by-turn part of a 20,000-persona
  study does not fit 16 GB but would fit 32 GB.
- **The analysis does not scale at all:** reading the record alone would need about 35 GB, and clustering grows with
  the square — 50 times the personas is 2,500 times the clustering memory. Today no machine runs the analysis of a
  20,000-persona study.

So the next limit is the analysis: reading the record a slice at a time and clustering a sample, not every pair.
