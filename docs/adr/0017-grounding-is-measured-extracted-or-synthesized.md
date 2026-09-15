# A grounded field says whether it was measured or extracted

`FieldOrigin` recorded three origins — `GROUNDED`, `SYNTHESIZED`, `CALIBRATED` — and `GROUNDED` covered two claims that are not the same claim. Reading the real shards showed how far apart they are: a `gss` row's `age_bracket` is a survey answer, carrying `assignment_type: direct` with *empty* evidence because the instrument is the source; an `amazon` row's `cuis_vegan` is also `direct`, at confidence 0.8, and its evidence is the review sentence `"Not vegan but still good"`. One is a person answering a question. The other is a model reading a sentence. `FieldOrigin` gains a fourth value so it can say which: `MEASURED`, `EXTRACTED`, `SYNTHESIZED`, `CALIBRATED`.

The tier cannot be a property of the source. `gss` and `amazon` both report `direct`, so `assignment_type` alone does not separate them; and within a single source it varies — `wiki` grounding is 49% `unsupported` with a median confidence of 1.00, `amazon` is 52% `summary_inference`. A source-level label would be false for exactly the two sources where the distinction matters most. The adapter derives the tier per field from the source and the assignment type together, which is the adapter's knowledge in the same way the packed encoding is.

## Considered options

A parallel `evidence` map beside `origins` was rejected: two maps per persona must be kept in sync, and the invariants that protect the engine — `Population` already enforces that gates run only on attributes it declares grounded — become statements about two fields at once, which is where they get written wrongly. Leaving `GROUNDED` undivided was rejected because every claim the engine makes rests on the distinction; without it, a distribution gate cannot say whether it compared measured values or a model's readings. `SCHEMA_VERSION` is `1.0.0` and unreleased, so widening the enum costs a mechanical sweep now and a migration later.

## Consequences

The tier grades a claim; it does not gate one. Requiring gates to run on `MEASURED` attributes would refuse every study built on `SyntheticCoresetSource`, which the quickstart and the whole suite run on and which `FINAL_ARCH.md` §4 keeps deliberately. Instead the `GateReport` carries the weakest tier among its gated attributes, following the rule `GateReport.reference` already sets: a pass is never read as a stronger claim than its weakest gate supports.

One refusal is kept. A gate may not claim `GateReference.CATEGORY_TARGETS` — "this population matches the measured category" — on attributes that are not `MEASURED`. The strong claim requires the strong evidence; the weak claim is permitted and labelled.

Audience filters are graded the same way rather than restricted, so one rule covers gates, audiences and sources instead of a rule with exceptions. `KNOWN_PERSONA_SOURCES` gains the tier mapping, and a study mixing sources takes the weakest tier present.
