# The agent answers in batches, in request order

A tick activates thousands of personas at once, and `inference` is batch-first: `complete(requests) -> outcomes`,
one outcome per request in request order, failures as outcomes rather than exceptions (ADR 0023). `elicitation`
keeps the same contract. The agent does too: `turns(jobs) -> outcomes`, where a job is one persona with its state
and its presentation, and an outcome is either a completed turn or a recorded turn failure.

A single turn is a batch of one. Nothing is merged into a shared prompt — every persona still gets its own,
conditioned on itself alone.

The alternative — one call per persona — forces the runner to assemble batches itself if the tier coalescing and
rate limiting built into `inference` are to be used at all. That puts prompt assembly outside the module that owns
the conditioning invariant, which ADR-worthy or not is the one thing this codebase refuses to let happen.

## Considered options

`turn(persona, impression, view) -> Reaction` per persona, as sketched in the architecture, was rejected: it either
wastes the batching `inference` exists to provide, or leaks batch assembly into the runner. Splitting the agent into
`plan_turn` and `parse_turn` so the runner batches the dispatch between them was rejected because the guardrail
check needs both halves — it compares parsed output against the context that produced it — and splitting them puts
one invariant on two sides of a module boundary.

## Consequences

All tier-A turns in a tick coalesce into real batches, and the adaptive rate limiter sees them as such. One
persona's failure cannot end a tick: it is an outcome beside the others, and the policy for it is the contract
rather than something the runner invents. The runner stays thin — it hands a tick's jobs over and receives
outcomes — and never builds a prompt. The cost is that the simple mental model is gone from the signature; tests
and the docs keep `turns([job])[0]` readable for the single-persona case.
