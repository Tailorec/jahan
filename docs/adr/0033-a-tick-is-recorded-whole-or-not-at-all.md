# A tick is recorded whole, or not at all

The runner is a partition's only writer, and `TracePartition` refuses sequence gaps and repeats, so whoever
numbers events must see a whole tick at once. ADR 0011 already says a resumed world discards everything after
the last closed tick. Together these leave one coherent write path: the runner buffers a tick's events, numbers
them, and writes them together with the tick's `tick_closed` event in one transaction. A crash mid-tick leaves
nothing of that tick behind, so the trace only ever holds whole ticks and stays append-only in the strict
sense — nothing is ever deleted to make a resume possible.

At a study's scale a tick is tens of thousands of events, tens of megabytes held for the duration of one tick
against a hundred-odd megabytes for a finished world. The memory is affordable; the alternative is not.

The consequence is that a discarded tick's model calls were billed and never recorded. That is not hidden: on
resume the runner records the tick it threw away, the registry states how much spend is recorded and how many
ticks were discarded, and the budget is enforced against the pessimistic figure — recorded spend plus, for each
discarded tick, the mean cost of the ticks that did complete. A crash therefore makes a run stop earlier than it
strictly had to, never later.

## Considered options

Streaming events as they happen was rejected: a crash leaves a partial tick on disk, and "discard anything after
the last closed tick" becomes a deletion the trace has to support — a record that can be mutated is not an audit
spine. Numbering by reserved sequence ranges was rejected with it, since a range the crash never filled is a gap
the partition refuses. A disk staging area promoted at tick close was rejected as the same design as this one with
more moving parts, worth building only if a tick stopped fitting in memory, which at these sizes it does not.

Enforcing the budget against the recorded total alone was rejected: every crash would silently raise the real
ceiling, and a run that crashed repeatedly could overspend a stated budget by a tick's worth each time. For an
instrument someone runs on their own card, stopping slightly early is the better failure.

## Consequences

The trace is whole ticks only, which makes every read — live or finalized — consistent without a transaction
protocol of its own. A crash costs at most one tick of work and of unrecorded spend, and both are recorded rather
than assumed away. A report quoting a run's cost can say exactly what was recorded and what is unknown.
