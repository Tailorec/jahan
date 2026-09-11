# Worlds resume by replaying their trace, and the runner is the partition's only writer

A world step takes the previous tick's turns and returns a delta built from existing trace payload types — stimuli published, interventions applied, exposures dropped — plus one presentation (impression and view) per activated persona. The runner is the only writer of a partition: it numbers the delta's events, runs the turns, and records costs in one gapless sequence, so the world never sees event ids or sequence numbers.

Because the trace records everything a world was given and everything it produced, no world state crosses the boundary. A crashed world resumes by resetting and replaying its recorded turns through the step up to the last closed tick; replay must reproduce the recorded events exactly, which doubles as a determinism check. A `tick_closed` event marks each fully recorded tick, and anything after the last one is discarded on resume. Checkpoints become an internal speed-up, not part of the contract.

Replay only works if everything that shapes a step is in the trace, so budget degradation — freezing optional reflections, subsampling activation, pausing — is recorded in every live world's partition at the tick a rung applies, and rungs only escalate. That also keeps a degraded world from being compared silently with one that ran in full.

## Considered options

Persisting an opaque checkpoint per tick was rejected as a second, uninspectable copy of state that could disagree with the trace; a structured world-state schema was rejected as a near-duplicate of the partition. A world-specific delta vocabulary was rejected because its translation into trace events is exactly where the trace and the world would drift apart.
