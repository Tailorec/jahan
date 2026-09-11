# The trace records whole turns in self-verifying partitions

A turn event carries the whole turn — the impression as shown, with its grouped exposures, and the reaction to it — instead of separate exposure, reaction and elicitation events. Separate events could not say which exposures a persona saw side by side, which is the reason ADR 0003 exists, and each duplicated fact was a second source of truth that could contradict the first. Every event kind is now the only record of what it describes.

A partition is validated as a whole. Its header carries the brief pack, the scenario, the replicate seed and the population hash, so the world id is derived rather than stated and every event can be checked against the world it belongs to: sequence numbers gapless from zero, ticks never going back or past the horizon, stimuli published before they are shown, dropped or replied to, claims that the brief makes, impressions within the scenario's exposure budget, and only scheduled interventions. Storage may sort events by persona and tick; sequence order is recovered, not assumed.

Reading is version-aware. A partition from a newer contract is refused; an older one is brought forward by applying, in order, every registered migration newer than the contract it was written under; the result is always a strict partition, so nothing legacy is written back.

## Consequences

Each partition repeats its brief pack and scenario — a few kilobytes against partitions of hundreds of megabytes. Full validation measured about 67 µs per event, so a 60,000-turn world validates in a few seconds; the hot write path still uses unvalidated construction, which refuses raw mappings so a mistake fails loudly.
