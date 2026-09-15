# Calibrate against measured marginals rather than fusing one person from several

The corpus measures demographics and consumption on different people. `gss` carries around fifteen populated attributes, almost all of them demographic, and none of `topic_coffee`, `att_brand_loyalty` or `topic_fitness`. `amazon` carries consumer attitudes read from review text and almost no demographics. The obvious repair — build one persona by joining a `gss` row's demographics to an `amazon` row's attitudes — is statistical matching, and it rests on the conditional independence assumption: that given the shared variables, the two blocks are independent. That assumption is untestable from data that never observed the blocks together, and it is precisely the correlation an FMCG study exists to measure.

It is also not available here. Matching needs shared variables, and `amazon` rows do not carry them: `age_bracket` 6.3%, `gender_identity` 7.0%, `region` 11.1%, `socioeconomic_band` 0.23%, `highest_education` 3.4%, `demo_employment_status` 7.9%. Of 21,353 `amazon` rows measured, 77.9% carry none of the six and exactly one carries all six. A chain through `stackoverflow` — which shares 56 fields at 5% fill or better with `amazon`, and has near-complete demographics — is structurally possible and rejected: it stacks two conditional independence assumptions and routes the correlation structure of the general population through a developer panel.

The engine therefore does not fuse persons. A population takes its spine from one source, projects what the spine does not carry, and is judged against measured marginals from wherever they were measured.

## Considered options

Per-person donor fusion, copying whole blocks rather than single fields, was the strongest rejected option: it preserves the within-block joint from a real person, which field-wise synthesis destroys, and it fails here only because the bridge variables are absent. It stays the right technique for a corpus that has them. Conditioning on the synthetic rows instead — they carry all 1,290 fields — was rejected because it would let the current ontology run unchanged while making "human-grounded population" false.

## Consequences

Marginal calibration assumes nothing about the joint, so `amazon`-derived distributions of `att_brand_loyalty`, `lstyle_frugality` and `topic_coffee` can serve as `CategoryTargets` for gating projected values even though no `amazon` row can be linked to a spine row. This is what `CategoryTargets` and `GateReference.CATEGORY_TARGETS` were built for, and ADR 0017 bounds the claim: targets may only be claimed against `MEASURED` attributes, so an `amazon`-derived target grades as `EXTRACTED`.

No `DONATED` origin is added and no donor provenance is recorded; both were designed for the fusion this decision rejects. `FieldOrigin`'s four values stay sufficient.

Projection carries far more weight than the original design assumed. It no longer fills a few sparse fields — it produces every category attitude, for every persona. What `inference` must support is shaped by that, and how much of an attitude demographics can actually explain is a measurement this decision does not make.
