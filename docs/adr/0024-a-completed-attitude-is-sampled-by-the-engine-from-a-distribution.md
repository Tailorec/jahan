# A completed attitude is sampled by the engine from a distribution the model gives

ADR 0018 made projection responsible for every category attitude, and ADR 0019 named what that risks: if an attitude is a deterministic function of the conditioning set, and ties are built on the conditioning set, attitude similarity and tie probability are correlated by construction and opinion clustering is inflated. Projection asked for completions at temperature zero, so every attitude was exactly that deterministic function. The model now returns a probability distribution over the attribute's vocabulary for each persona, and the engine samples the value from it with the population's own seeded stream, at a `completion_temperature` it applies to that distribution and records.

## Considered options

Raising the provider's sampling temperature was rejected: its randomness is unrecorded, differs between providers and quantizations, and cannot be reproduced, so the variance a study depends on would be a property of whoever served it. Keeping temperature zero was rejected because it is the circularity ADR 0019 describes. Asking the model for one value and adding engine-side noise was rejected because the noise would carry no information about which alternatives the model found plausible.

## Consequences

The variance is explicit, recorded, tunable and reproducible under the engine's seed whatever the provider does, and a population records the distribution it sampled from beside the value it drew. A distribution is also what makes projection measurable: the Stack Overflow holdout can score calibration — whether values the model gives 30% occur about 30% of the time — and not only accuracy against the measured attitudes demographics can explain. A distribution that does not cover the vocabulary, or does not sum to one within tolerance, is refused like an off-list value, and the field is left uncompleted. This changes module 3's projection, which ADR 0019 assigned to inference.
