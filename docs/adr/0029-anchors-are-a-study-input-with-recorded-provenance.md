# Anchors are a study input with recorded provenance, and the gate judges every one of them

ADR 0027 rejected model-generated anchors: a model's phrasing habits carry into the statements, and embeddings of
model-written text sit nearer model-written responses. The anchor families shipped as `purchase_intent/v1` and
`satisfaction/v1` were nevertheless written by a model during implementation. Both failed the check — on Amazon
Titan Text Embeddings v2 and again on Amazon Nova 2 multimodal embeddings, at the same places, with rank stability
0.500 and 0.714 against a threshold of 0.8. An engine-free recomputation confirmed the numbers are the models', not
a defect.

The paper's own anchors cannot be borrowed. Appendix C.1 describes their design but does not publish them; the
authors' implementation carries the algorithm and no statements. Theirs were human-written and checked on
`text-embedding-3-small`, and the paper records that "different anchor sets can lead to slightly different
mappings" — the sensitivity the engine's gate exists to catch.

So anchors are a **study input**, not an engine fixture. A study names an anchors directory, which may live outside
the repository; a version there is frozen, hashed and pinned exactly as before; and a provenance note beside each
version records who wrote the statements and where they came from — a client's own survey instrument, a published
scale, or a model. Provenance sits beside the version rather than inside it, so a version's identity stays the hash
of its statements. The repository keeps `v1` of both families as a runnable **example, labelled model-written**, so
the engine works out of the box without anyone mistaking the default for a validated instrument.

The gate is unchanged and applies to every anchor set, whoever wrote it. Human authorship is not stability: whether
statements rank consistently under an embedding model is an empirical property of those statements and that model
together, and only the check can tell.

## Considered options

Writing a second engine-authored family was rejected: it repeats the experiment that just failed, and the per-set
diagnostics from the Nova run show which wordings break the ladder, so a version written after reading them would
be fitted to its own test (ADR 0027). Lowering the 0.8 threshold or relaxing the ladder was rejected as tuning the
gate to the result it just produced. Copying anchors from community reimplementations remains rejected for unknown
provenance. Scoring purchase intent without a passing version was rejected outright — see ADR 0032 for what happens
to a reaction that cannot be scored.

## Consequences

Out of the box, no anchor version can be pinned, so purchase intent is elicited and recorded but not scored until
someone supplies a version that passes. The two realistic paths to one are a client's validated scale — the wording
their human respondents already see, which also makes the simulation comparable to their own surveys — and a
re-check of the existing families on `text-embedding-3-small`, which would be the closest available replication of
the paper. Anchor authorship moves to where the domain knowledge is, and the engine's contribution is the refusal
to run on statements that do not hold their order.

A future anchor workbench, where a user revises statements against evaluation results, must keep a tuning set and a
held-out set apart: revising until the numbers improve fits the instrument to its own test, and the agreement it
would report would be inflated (§12).
