# Personas react to impressions, not to individual stimuli

A persona reacts once per channel per tick, to the whole set of stimuli it saw (an **impression**), rather than once per stimulus. Seeing two things side by side is not the same as seeing each alone, and social proof — the mechanic that distinguishes the feed from the survey room — only operates through juxtaposition; serving stimuli one at a time reduces the feed to a slower survey room.

The cost difference is not marginal: at 2,000 personas over 30 ticks with an exposure budget of three, per-stimulus reactions mean roughly 180,000 tier-A calls per world against 60,000 for impressions, multiplied again by variants and replicates in a sweep.

## Consequences

`Exposure` keeps its per-stimulus shape so recommender scoring, attention and drop-reasons are unchanged; exposures are grouped before reaching the agent, not flattened. A reaction records both the impression it saw and the `subject_stimulus_id` it is about, since purchase intent is directed at a specific proposition even when several things were on screen. A survey-room impression holds exactly one exposure, so both environments share one code path.
