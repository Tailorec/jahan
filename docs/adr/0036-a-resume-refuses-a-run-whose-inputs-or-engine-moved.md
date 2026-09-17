# A resume refuses a run whose inputs or engine moved

Resuming a run continues a study, so everything the study rests on must be the same study. The registry pins the
brief, the ontology, the population, the scenario and the model pins, and a resume refuses when any of them moved,
naming the one that did. That much the architecture already required for `brief_hash`.

The registry also records the engine version, and a resume under different engine code refuses on the same terms.
This is not hypothetical. `reddit_hot` was fixed mid-development from ranking the oldest stimulus first to the
newest: a run paused before that fix and resumed after it would hold ten ticks under one ranker and twenty under
another, with nothing in the trace to say so. A replay check might have caught it as a divergence, but a study
should not be protected by an error message from an unrelated mechanism — the refusal belongs at the point where
someone asks for the continuation, and it should name what changed.

A resume can be forced. Forcing is recorded in the registry, and the run's results are marked as spanning engine
versions, so a reader is told rather than left to notice.

## Considered options

Refusing only on the brief hash was rejected: the brief is one of several things a study rests on, and the engine
is the one that changes most often. Allowing a version change silently, relying on replay divergence to surface it,
was rejected because divergence is detected only where a recorded delta is re-derived — a behaviour change in a
path replay does not touch would pass unnoticed. Forbidding forced resumes outright was rejected as too rigid for a
research instrument: a maintainer who knows a fix is irrelevant to the ticks already recorded should be able to
proceed and have that choice recorded.

## Consequences

The registry gains the engine version as a pinned fact, and every refusal names the thing that moved. A long run
across an engine upgrade is either restarted or explicitly forced and labelled. Development that changes world or
agent behaviour invalidates in-flight runs, which is the honest cost of changing an instrument mid-measurement.
