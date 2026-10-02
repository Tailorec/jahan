# A running study shows decisions before they are record

A tick is recorded whole or not at all (ADR 0033), and every reader sees closed ticks only. That kept every view
honest, but it made a running study look dead: the engine hands a tick's turns to the model as one batch and
records them when the last reply lands, so a 1,500-persona concept test (one tick, about an hour of calls on a
rate-limited model) showed nothing at all until it was over.

Each persona's decision is now published the moment its reply lands and parses: the model client tells a
listener about every outcome as it arrives, the agent turns a parsed reply into a decision (who, which channel,
which action, their words, who the item came from), and the study appends it to `live/<world>.decisions.jsonl`.
The file is removed when its tick closes. The interface polls it and plays the open tick's decisions as they
arrive, marked **provisional**, and swaps to the recorded tick when it closes.

## What it does not change

The trace stays the only record. Decisions are not written to it, never counted in a digest, and never read by
analysis; the live digest (written after each closed tick) is unchanged. Listening changes no outcome: the
listener runs after the outcome is stored, and an error in it is swallowed rather than allowed to fail a turn.
Within a tick every persona acts on the tick's opening state, so showing one decision before another misstates
no cause.

## Why provisional

A decision shown early may never become record. The guard can reject a parsed reply and send the turn back with
a stricter prompt; an interrupted tick is discarded and asked again on resume, and a model that ignores seeds may
answer differently the second time. The interface therefore labels the open tick as provisional and replaces it
with the recorded tick, and nothing that computes a number reads the provisional file.

## Considered options

Writing each turn into the trace as it lands was rejected: it would end ADR 0033's guarantee that a tick is whole
or absent, and every reader would have to learn to ignore half-ticks. Splitting a tick into smaller batches was
rejected: it trades throughput for visibility and still shows nothing within a batch.
