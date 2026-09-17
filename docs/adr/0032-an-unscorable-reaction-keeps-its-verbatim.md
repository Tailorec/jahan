# An unscorable reaction keeps its verbatim, and is scored when a version passes

No anchor version is pinned (ADR 0029), and scoring refuses a version without a passing check. A purchase-intent
turn therefore produces text that cannot be mapped to a distribution today.

The turn still happens and the verbatim is still recorded. `Reaction.intent` is absent, and the reason — the
recorded elicitation failure — travels with it. A run whose purchase-intent turns could not be scored is visibly a
run with no intent data, never a run that quietly produced none: `analysis` refuses to compute adoption, or any
metric derived from intent, from turns that carry no distribution.

Because the expensive half of elicitation is the model call and the cheap half is the embedding, a closed run can be
scored later. When a version passes its check, the recorded verbatims of a finished study are scored against it
without re-running a single completion, and a study already scored can be re-scored under a different ε or
temperature from the per-set similarities the record already keeps.

## Considered options

Refusing to dispatch purchase-intent turns at all without a pinned version was rejected: it blocks `agent` and
`runner` behind an anchor problem that is not theirs, and it discards the verbatims that will be scorable later.
Asking the model for a rating directly as an interim was rejected — it is the numeric elicitation the paper's
method and the engine's own numeric-answer failure path exist to avoid, and a study run that way could never be
compared with one scored by SSR.

## Consequences

Module 6 and module 8 can be built and run end to end on a real model before the anchor problem is solved, at the
cost of runs whose intent column is empty. Re-scoring a closed run is a capability the engine now owes: a command
that reads a trace, scores its recorded verbatims against a newly pinned version, and writes the results as a new
scoring rather than mutating the original record.
