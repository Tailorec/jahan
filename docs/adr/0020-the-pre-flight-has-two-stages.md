# The pre-flight has two stages: what the corpus holds, then what the draw achieved

An ontology could declare a conditioning set no row populates, and nothing said so until a study ran. `assess()` would raise "no row in the source carries every attribute the category's conditioning set requires" — correct, and far too late and too quiet to tell an author that `spend_band` is populated on 1.3% of `stackoverflow` rows and 0.0% of `gss` rows. The gap that hid a whole category of mismatch is that the engine could answer *whether this draw is sound* but never *what is in here to draw from*.

`preview()` answers the second question from an index alone. Per-value counts across 1,290 fields, sixteen values and seven sources are about a megabyte; conjunctions come from the posting bitmaps the dataset already ships. Neither needs the 4.17 GB of shards, so audience exploration costs nothing and can be repeated freely before anything is downloaded. A χ² statistic cannot be computed from counts, so the statistical verdict stays where it was.

## Considered options

Adding counts and coverage to `CoresetSource` was rejected: the port promises three questions answered from rows, and these two are answered from an index with a different cost profile and a different failure mode. Typing `preview()` to a separate `CoresetCatalog` is what prevents it from quietly growing a row read — with a `CoresetSource` in hand it eventually would. Making the coverage check an authoring-time command of its own was rejected as a second thing to remember; the preview a user already runs is the right place for it.

## Consequences

`preview()` reports, per source, how many rows match and how many carry the attributes at all, which of them are `MEASURED`, `EXTRACTED` or absent, how many fields would be synthesized, which constraints the relaxation ladder would drop, and the resulting evidence grade. It always states denominators, because `0 / 0 / 63,532` — nobody was asked — and `0 / 12,400 / 63,532` — 12,400 were asked and none are like that — look identical as "no matches" and mean opposite things. The first says look elsewhere; the second is an empirical finding.

The natural-language step is bounded by the same index: the model proposing filters is given only the coverage table for the admissible sources as its vocabulary, and a proposed filter naming a field with no fill anywhere is refused rather than passed through to fail later. The interpretation is shown back for confirmation, as ADR 0014 requires of anything drafted from the corpus.

`admissible_sources` becomes a study parameter recorded on the manifest. A union across sources is permitted, never silent: the preview shows the resulting source mix, and ADR 0017's weakest-tier rule grades the population by the weakest source in it.
