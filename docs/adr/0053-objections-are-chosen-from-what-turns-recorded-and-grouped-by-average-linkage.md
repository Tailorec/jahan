# Objections are chosen from what turns recorded, and grouped by average linkage

The report's objection clusters were made from every verbatim a persona wrote, praise included, linked whenever
two sentences were at least 0.75 alike (single linkage). On real runs this produced noise, not themes: one
60-persona run reported 253 "objection clusters", about four per persona, most of them a single sentence, and many
were praise ("This app sounds useful…"). An objection buried among 253 is as good as missing.

**What counts as an objection** is now read from what the turn recorded, never from the words: a refusing action
(reject, complain, downvote); a survey answer whose scored intent leans to not buying (its two bottom boxes
outweigh its two top boxes); or a channel turn that moved the persona's beliefs down on balance. Praise and neutral
comments are not objections.

**How objections group**: average-linkage agglomeration on cosine similarity. Two groups join while their members
are, on average, at least the threshold alike, so one bridging sentence can no longer chain two topics into one
group. With no threshold given, the cut is relative: the similarity this run's own objection pairs reach in their
top quarter (0.645 on the run that prompted this). An embedding model's similarities sit at its own level — the
same sentences scored a median 0.57 under one model — so a fixed number does not carry across models. The
threshold used is recorded on every cluster, as before.

On that run, 59 of 340 verbatims are objections, and they form 13 groups: "skeptical it catches what reviewers
miss without adding noise" (16), "won't buy without proof on subtle bugs" (10), "needs false-positive benchmarks"
(7), "only if it fits the existing PR workflow" (6), and smaller ones.

## Consequences

Reports have fewer, larger objection findings; a study whose personas raised no objection has none. Clustering
stays deterministic: embedded once, linkage without randomness, ties in the medoid broken from a derived seed.
Earlier reports keep the clusters they were written with.
