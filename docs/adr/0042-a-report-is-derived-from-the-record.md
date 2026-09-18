# A report is derived from the record, and carries what produced it

A report is rendered from findings and digests that were themselves derived from a trace, and it records the
run id, configuration hash, seeds and engine commit it came from. It is never assembled beside the record from
numbers a script gathered along the way.

This is not a style preference; it is a defect already observed. The first real study's report was a dictionary
built by its own evaluation script, and it drifted from the trace immediately: the facts that mattered — that
word of mouth fired 113 times, that every turn moved a belief, that turns split across two channels — were in
the trace and never reached the report, while the report's own `probe_disagreement: 0.0` overstated what 18
easy questions established. Nothing tied the two together, so nothing could notice.

Every finding resolves to trace ids at the moment it is authored, by asking the view to resolve them. A finding
whose evidence does not exist therefore fails where it is written rather than where it is rendered, and
`report` cannot introduce a claim because it only formats findings that already passed that check. The run's
calibration is stated once, as its `TrustStatement`; findings carry only their own confidence, so "this
audience was small" is never confused with "this engine has never been benchmarked".

## Considered options

Letting each consumer gather what it needs from a run was rejected: that is the arrangement that produced the
drift above, and the previous design's duplicated objection clustering before it. Recording provenance only in
the registry was rejected because a report travels — it is the artefact that leaves the machine, and a reader
holding it should not need the registry to know which run it describes. Rendering findings without resolving
their evidence was rejected because an unresolvable citation discovered at render time is discovered too late
to fix the finding.

## Consequences

`report` stays thin and testable: same findings in, byte-identical documents out, markdown and JSON carrying
the same set. A report names the engine commit that produced it, so two reports from different code cannot be
mistaken for a difference in findings. And the evaluation script that started this ADR is replaced by the
digest it should have quoted.
