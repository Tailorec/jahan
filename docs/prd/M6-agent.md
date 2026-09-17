# PRD — M6 `agent`: one persona's reaction to what it was shown

## Problem Statement

Everything the engine has built so far describes people and machinery: a population with 1,290 attributes per
persona, a way to call models in batches, and a way to turn free text into a rating distribution. Nothing yet makes
a persona react to anything.

The module that does it owns the invariant the whole engine's validity rests on. The SSR literature is consistent
that conditioning is load-bearing: unconditioned personas produce optimistic, narrow distributions and rank
correlation falls to roughly half. The architecture is explicit that an invariant deciding validity cannot be
co-owned, which is why context assembly, persona rendering, memory and belief updates all live here rather than
being spread across the runner and the world.

Four risks are specific to this module. A turn that dispatches without a persona block produces a plausible answer
from nobody in particular, and nothing downstream can tell. A persona that answers about something it was never
shown contaminates the result with the model's own invention. A persona that slowly stops sounding like itself over
a long horizon invalidates the study's later ticks without any single turn looking wrong. And an agent that holds
persona state internally cannot be spread across workers, which the runner needs for any study at scale.

Two constraints arrive from outside. No anchor version is pinned (ADR 0029), so purchase-intent turns produce text
that cannot yet be scored, and the module must record that honestly rather than either failing or inventing a
number (ADR 0032). And `trace` (module 9) does not exist yet, so the module writes through a port with a fake.

## Solution

One module, batch-first like `inference` and `elicitation`, which is a pure function of what it is given.

`turns(jobs) -> outcomes` returns one outcome per job in request order — a completed turn or a recorded turn
failure, never an exception for one persona and never a silent gap (ADR 0031). A job carries one persona, its
`PersonaState` and its presentation. An outcome carries the reaction, the memories written, the belief change and
the records the trace needs. State travels in and out; the agent stores nothing (ADR 0030).

The context is assembled here and nowhere else: the persona block rendered from ontology-selected attributes,
current beliefs, retrieved memories, the impression and its view, and the frozen question. Before dispatch, the
context is checked for a non-empty persona block; a turn cannot proceed unconditioned, and the failure is loud.
After parsing, a response referring to a stimulus that was never in context is retried once with a stricter
instruction and then recorded as a guardrail violation in place of a reaction.

Memory is arithmetic the engine owns — no framework, no vector database. Retrieval scores a persona's own memories
by recency, importance and similarity to the stimulus. Importance comes from a rule, except on tier-B events where
the model is already being paid for. Reflection consolidates on a jittered cadence and whenever beliefs move
sharply. A character probe, asked of a small sample every few ticks, turns persona drift into a number a report can
carry.

## User Stories

**The turn**

1. As a runner, I want a tick's turns answered as one batch in request order, so tier-A work coalesces into real
   batches and the rate limiter sees them as such.
2. As a runner, I want one persona's failure recorded as an outcome beside the others, so a single bad response
   cannot end a tick.
3. As a maintainer, I want a single turn to be a batch of one, so the simple case stays readable in tests and docs.
4. As a methodologist, I want every persona's prompt conditioned on that persona alone, so nothing is merged into a
   shared prompt for efficiency.
5. As an analyst, I want a reaction to name the stimulus it is about, even when several were on screen, so intent is
   attributable to a proposition rather than to a screenful.

**Conditioning, the invariant**

6. As a methodologist, I want the persona block rendered from the attributes the category ontology selects, so a
   study conditions on what the category says matters.
7. As a methodologist, I want dispatch refused when the persona block is empty, so an unconditioned turn can never
   be recorded as a persona's reaction.
8. As a methodologist, I want conditioned and unconditioned contexts to produce measurably different distributions
   in the direction the literature reports, so the invariant is demonstrated rather than asserted.
9. As an analyst, I want the persona block's hash recorded with the turn, so two runs can be compared on what the
   persona was told about itself.
10. As a maintainer, I want the persona block rendered once per persona per run and reused, so a long horizon does
    not re-render 1,290 attributes every tick.

**State, memory and belief**

11. As a runner, I want a persona's state to travel with its job, so any worker can take any persona and a
    checkpoint is state that has already crossed the boundary.
12. As a persona, I want to retrieve my own memories by recency, importance and relevance to what I am looking at,
    so what I recall depends on what is in front of me.
13. As a methodologist, I want memory retrieval never to reach another persona's memories, so nothing leaks between
    personas.
14. As an operator, I want memory importance decided by a rule for tier-A events, so a study does not pay a model
    call per memory.
15. As an analyst, I want beliefs to move across the closed dimension set and per claim, so a persona who flips on a
    single claim is visible even when aggregate belief barely moves.
16. As a persona, I want to reflect on a cadence and whenever my beliefs move sharply, so experience consolidates
    instead of accumulating forever.
17. As an operator, I want reflection cadence jittered per persona from the seed, so reflections spread across ticks
    instead of spiking on one.
18. As a maintainer, I want a persona's memories capped with consolidation, so neither the prompt nor the state
    grows without bound over a long horizon.

**Staying in character**

19. As a methodologist, I want a small sample of personas probed every few ticks on facts that are in their own
    attributes, so drift is measured rather than assumed absent.
20. As an analyst, I want the probe's disagreement rate recorded per run, so a study that drifted can be identified
    after the fact.

**Guardrails and output**

21. As a methodologist, I want a response referring to a stimulus that was never in context retried once and then
    recorded as a violation, so invention is never kept silently.
22. As an analyst, I want the rejected prompt's hash recorded when a retry succeeds, so the retry rate is
    measurable.
23. As a researcher, I want purchase-intent text scored when a passing anchor version exists, and recorded with its
    failure when none does, so a run without intent data is visibly that (ADR 0032).
24. As an operator, I want tier routing to follow a configuration table rather than code, so which events deserve
    the better model is a study decision.

## Implementation Decisions

**Interface.** `turns(jobs: Sequence[TurnJob]) -> tuple[TurnOutcome, ...]`, one outcome per job in request order.
`TurnJob` carries `persona`, `state`, `presentation` and the task; `TurnOutcome` carries the reaction, new memories,
belief change, probe result where one was asked, and the trace records for the turn.

**Contract amendments, landing before either branch.** `PersonaState`, `TurnJob`, `TurnOutcome`, and trace payloads
for a memory event, a belief snapshot and a probe result. `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved
identities are re-pinned rather than migrated.

**Context assembly.** Persona block (ontology-selected attributes, rendered by the salvaged MatrAIx templating),
then beliefs read directly, then retrieved memories, then the impression and view, then the frozen question.
Token-budgeted per tier; when the budget binds, memories are dropped before beliefs and beliefs before the persona
block, so the invariant is the last thing to go and its removal is refused rather than silent.

**Retrieval.** `score = exp(-Δt/τ_r) · importance · cos(emb_memory, emb_stimulus)`, `τ_r ≈ horizon/4`, top-k of 3
for tier A and 8 for tier B, over that persona's own memories only. Memories are embedded once when written,
through `EmbedPort`.

**Importance.** A rule from the action taken and the magnitude of the belief change, deterministic and free. On
tier-B events (first exposure, purchase, reflection) the model rates importance in the call already being made.

**Reflection.** Every 4–8 ticks, the exact cadence derived per persona from the run seed, or whenever
`max |Δ| > 0.3` across dimensions and claims together. Produces a belief change and one to three consolidated
memories of high importance.

**Character probe.** 2% of activated personas every 10 ticks, seeded, two or three questions whose answers are in
the persona's attributes, tier A. Recorded as its own trace payload with the agreement result.

**Guardrails.** Two rules only: a stimulus referenced that was not in the impression, the view or the persona's
retrieved memories; and output that cannot be parsed for the task. One stricter retry, then a `guardrail_violation`
carrying both prompt hashes.

**Affordances are the world's.** The agent proposes an action; a channel that does not support it rejects it there.
No retry — a refused action is data about the persona.

**Nothing third-party.** No agent or memory framework, no vector database, no provider SDK. Retrieval is numpy over
a persona's own memories (ADR 0030).

**Salvage.** OASIS `agent.py`, `agent_action.py`, `agent_environment.py` for the agent-action-environment shape
(CAMEL stripped, our `ChatPort` injected); MatrAIx `templating.py` for attribute rendering; MatrAIx `user_sim.py`
for conversational turns; Generative Agents (Park et al.) for the memory and reflection method, paper only.

## Testing Decisions

Boundary tests through `turns`, with `FakeInference` and `FakeEmbed`; the suite never reaches a network.

- **The conditioning test**: conditioned and unconditioned contexts produce measurably different distributions, in
  the direction the literature reports; unconditioned dispatch is refused outright.
- A stimulus absent from context triggers the guardrail path exactly once, then records a violation and no reaction.
- Reflection fires at the cadence and at the belief-delta threshold — including a flip on a single claim — and not
  otherwise; the jitter is deterministic under a fixed seed.
- A survey-room impression carries exactly one exposure and produces exactly one reaction.
- Memory retrieval returns the k most relevant items under a known fixture, and never another persona's memory.
- The token budget is respected per tier, and a budget that would drop the persona block fails the turn instead.
- Tier routing matches the configuration table for every event class.
- A batch returns one outcome per job in request order, with one persona's failure recorded beside the others.
- State round-trip: state rebuilt by replaying recorded events equals the state the run carried.
- Two processes produce identical turns from identical jobs under a fixed seed.
- A purchase-intent turn with no pinned anchor version records the verbatim and the elicitation failure, and no
  distribution.

## Out of Scope

Orchestration, worker pools, checkpointing and budget enforcement (`runner`, module 8). Trace storage and its read
views (`trace`, module 9); this module writes through a port with a fake. Environment mechanics, exposure and
affordance rules (`world`, module 7). Anchor authorship and the mapping validation (`elicitation`, module 5, and
ADR 0029). Re-scoring a closed run against a newly pinned version, which ADR 0032 records as owed.

## Further Notes

`FINAL_ARCH.md` §5.6 gives the interface as `turn(persona, impression, view) -> Reaction`; ADRs 0030 and 0031
supersede it, and the section is amended in the same commit that lands the contracts.

The character probe is new — it appears in no ADR before 0030's companion discussion — and is included because
drift is the failure mode most likely to invalidate a long study while every individual turn still looks
reasonable. Retrofitting its trace payload after runs exist would make those runs incomparable.
