# The engine is a research instrument, and its default persona corpus is research-only

Jahan is built to test a research question — whether a grounded synthetic population can reproduce how people respond to a product — not to sell concept tests. Its default corpus, MatrAIx Persona 1M, is released under `matraix-research-only`: non-commercial research use, with subsets inheriting the terms, the MIT licence covering only the MatrAIx code, and several upstream sources carrying their own restrictions (Wikipedia CC BY-SA 4.0, Stack Overflow ODbL, PRISM CC BY-NC, Amazon Reviews research use, NORC terms for GSS). The engine is positioned accordingly: Persona 1M is the research corpus reached through `CoresetSource` at runtime, and any other use brings its own corpus through the same port.

## Considered options

Positioning the engine for commercial concept testing was rejected: a brand running a study is commercial use, which the corpus does not permit and whose upstream rights its authors say are not theirs to grant. A synthetic-only corpus would sidestep the terms but abandon the claim the research exists to test — that grounding in real records matters. Negotiating a commercial licence is unnecessary for a research instrument and remains open to anyone who later needs it.

## Consequences

No row of the corpus enters this repository, including the Dataset Viewer's `sample/sample.parquet`: a subset inherits the terms, so fixtures stay synthetic or hand-written. The corpus is downloaded by whoever runs the engine, who accepts its terms directly, and the engine never bundles it.

The dataset card expects downstream users to delete records removed in later revisions, for example when a survey participant withdraws consent. A persisted population therefore records the corpus revision and each persona's `source_record_id`, so removed records can be found and purged — and replaying a study after such a removal is not guaranteed, which qualifies ADR 0015's promise to carry a population unchanged.

The corpus is calibrated to the 2024 global population, children included, and only its real-survey minors were removed; roughly half the synthetic personas with an age are under eighteen. Consumer studies need an adult eligibility rule rather than trusting the corpus to exclude minors. The responsible-use terms — no impersonation, no re-identification, no targeting of individuals or protected groups — bind every study run on it.
