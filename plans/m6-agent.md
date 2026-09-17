# Plan: M6 `agent` — one persona's reaction to what it was shown

> Source PRD: `docs/prd/M6-agent.md`
> Binding decisions: ADR 0030 (persona state travels with its job), ADR 0031 (the agent answers in batches, in request order), ADR 0032 (an unscorable reaction keeps its verbatim), ADR 0023 (batches answered in request order, failures as outcomes), ADR 0021 (one OpenAI-compatible endpoint, no provider SDK), ADR 0024 (the engine samples a completed attitude), ADR 0010 (within-tick independence), ADR 0029 (anchors are a study input), ADR 0008 (trust stays uncalibrated). `CONTEXT.md` (Persona State, Memory, Reflection, Character Probe, Drift, Affordance, Conditioning, Turn, Guardrail Violation). Where `FINAL_ARCH.md` §5.6 disagrees, the ADRs win — §5.6 is amended in phase 9.

## Architectural decisions

Durable across every phase:

- **Batch first** — `turns(jobs) -> outcomes`: one outcome per job in request order, a completed turn or a recorded turn failure, never an exception for one persona and never a silent gap. A single turn is `turns([job])[0]`.
- **The agent stores nothing** — `PersonaState` (beliefs, that persona's memories, reflection counters) travels in and out. The trace is the only store; the runner is its only writer.
- **Conditioning is the invariant** — the persona block is assembled here and nowhere else, checked for non-emptiness before dispatch, and its hash is recorded with the turn. A turn cannot proceed unconditioned.
- **One persona per prompt** — batching coalesces calls, never contexts. No prompt mentions another persona's attributes, beliefs or private reactions, and none carries an aggregate outcome.
- **Memory is arithmetic the engine owns** — retrieval scores a persona's own memories by recency × importance × relevance in numpy. No agent framework, no memory framework, no vector database.
- **Importance is a rule on tier A** — from the action taken and the size of the belief change; the model rates it only inside a tier-B call already being made.
- **The world owns affordances** — the agent proposes an action; a channel that does not support it rejects it there, and the rejection is data, not an error.
- **Purchase intent is scored when it can be** — with a pinned anchor version, through `elicitation`; without one, the verbatim and the recorded elicitation failure stand in its place, and no code path asks a model for a number.
- **Everything seeded is derived** — reflection jitter, probe sampling and any other draw come from the run seed and a named purpose, so adding a draw cannot shift an existing one.
- **Contract amendments come first** — `SCHEMA_VERSION` stays 1.0.0 and unreleased, so moved identities are re-pinned rather than migrated.
- **Test posture** — boundary tests through `turns`, with `FakeInference` and `FakeEmbed` and a fake trace writer. The suite never reaches a network.

---

## Phase 1: The shared contracts

**User stories**: 11

> This phase lands on `master` before either parallel branch begins. It is the only work both branches share, and it carries no behaviour.

### What to build

The types the agent's boundary needs and the trace payloads its output requires. `PersonaState` carries a persona's beliefs, its own memory events and the counters that decide reflection. A `TurnJob` is one persona, its state and its presentation; a `TurnOutcome` is a completed turn or a recorded turn failure. The trace gains payloads for a memory event, a belief snapshot and a character-probe result, so nothing the agent produces has to be invented later.

### Acceptance criteria

- [x] `PersonaState` holds beliefs, that persona's memory events and its reflection counters, and is frozen like every other contract
- [x] A memory event carries its tick, description, importance, source and the embedding used to retrieve it
- [x] `TurnJob` and `TurnOutcome` exist, and an outcome is either a completed turn or a recorded failure naming its kind — never both, never neither
- [x] Trace payloads exist for a memory event, a belief snapshot and a probe result, and `TurnRecorded.memory_ids` resolves to memory events that exist
- [x] Pinned identities are re-pinned, with the change recorded in the commit that moves them
- [x] The existing suite passes unchanged in behaviour

---

## Phase 2: A conditioned turn, end to end

**User stories**: 1, 2, 3, 4, 5

### What to build

The module's shape made true on the narrowest possible path: a batch of jobs in, a batch of outcomes out, through a fake model. A persona block, the impression and the frozen question go into a prompt; the response comes back as a reaction naming the stimulus it is about. Nothing is retrieved, nothing reflects, no guardrail runs yet — but the order, the failure contract and the one-persona-per-prompt rule are settled here and never revisited.

### Acceptance criteria

- [x] A batch returns one outcome per job, in request order
- [x] One persona's failed call is recorded as its own outcome, and every other job in the batch still produces one
- [x] `turns([job])[0]` is the single-persona path, with no separate code path behind it
- [x] Each job's prompt contains that persona's block and no other persona's attributes, beliefs or reactions
- [x] A reaction records the impression it saw and the `subject_stimulus_id` it is about, even when the impression held several exposures
- [x] A reaction carries no aggregate outcome, asserted over the assembled context

---

## Phase 3: Persona rendering and the conditioning invariant

**User stories**: 6, 7, 8, 9, 10

### What to build

The invariant the module exists to own. Attributes the category ontology selects are rendered into a persona block by the salvaged MatrAIx templating, once per persona per run and reused. The context is token-budgeted per tier, and when the budget binds, memories go before beliefs and beliefs before the persona block — which is never dropped. Before dispatch, an empty persona block refuses the turn. The conditioning test demonstrates the difference conditioning makes rather than asserting it.

### Acceptance criteria

- [x] The persona block renders from ontology-selected attributes, and a category that selects different attributes produces a different block
- [x] The block is rendered once per persona per run and reused across ticks, with its hash recorded on every turn
- [x] Dispatch is refused when the persona block is empty, and the refusal is loud and recorded
- [ ] Conditioned and unconditioned contexts produce measurably different distributions, in the direction the literature reports — **owed, and not tickable with a fake**: a stand-in model's answers are whatever the stand-in was written to return, so a boundary test asserting this would assert only its own fake. The boundary tests prove what they can — the block reaches the prompt, two personas are told different things, an empty block is refused — and the measurement itself needs a real model, as an evaluation beside `docs/evaluations/2026-09-17-holdout-bedrock`
- [x] The token budget is respected per tier, dropping memories before beliefs
- [x] A budget that would drop the persona block fails the turn instead of dropping it

---

## Phase 4: Memory — written, embedded, retrieved

**User stories**: 12, 13, 14

### What to build

What a persona remembers and what it recalls when it looks at something. A turn writes memory events with an importance from the rule — the action taken and the size of the belief change — and each is embedded once through `EmbedPort` when written. Retrieval scores that persona's own memories by `exp(-Δt/τ_r) · importance · cos(memory, stimulus)` and takes the top 3 for tier A, 8 for tier B, into the context assembled in phase 3.

### Acceptance criteria

- [x] A turn writes memory events carrying tick, description, importance, source and embedding
- [x] Importance follows the rule deterministically, and no extra model call is made for it on tier A
- [x] Retrieval returns the k most relevant memories under a known fixture, k by tier
- [x] Retrieval never returns another persona's memory, asserted against a fixture where another persona's memories would score higher
- [x] A memory is embedded once when written and never re-embedded at retrieval
- [x] Retrieved memories appear in the assembled context and are dropped first when the budget binds

---

## Phase 5: Beliefs and reflection

**User stories**: 15, 16, 17, 18

### What to build

How a persona changes. Belief deltas apply across the closed dimension set and per claim; reflection fires on a per-persona cadence jittered from the run seed, or whenever `max |Δ| > 0.3` across dimensions and claims together, and produces a belief change plus one to three consolidated memories of high importance. A persona's memories are capped, with consolidation keeping the state and the prompt bounded over a long horizon.

### Acceptance criteria

- [x] Belief deltas apply across dimensions and per claim, and a flip on a single claim is visible when aggregate belief barely moves
- [x] Reflection fires at the jittered cadence and at the delta threshold, and not otherwise
- [x] The jitter is derived from the run seed, so a rerun reflects on the same ticks
- [x] Reflection writes a belief snapshot and one to three consolidated high-importance memories
- [x] A persona's memories are capped, and consolidation keeps the cap without discarding the highest-importance items
- [x] State after N ticks is bounded in size, asserted over a long-horizon fixture

---

## Phase 6: Guardrails and parsing

**User stories**: 21, 22

### What to build

What happens when the model invents. Output is parsed per task type; a response referring to a stimulus that was in neither the impression, the view nor the persona's retrieved memories is rejected, retried once with a stricter instruction, and then recorded as a `guardrail_violation` carrying the impression, the view, both prompt hashes and the rule broken — in place of a reaction, so the persona does not react that tick. Unparseable output takes the same path.

### Acceptance criteria

- [x] A stimulus absent from context triggers the guardrail path exactly once
- [x] A turn accepted on retry records the hash of the prompt it rejected
- [x] A turn whose retry also fails records a violation and no reaction
- [x] Unparseable output follows the same one-retry path
- [x] The two rules are the only guardrails, asserted over the module so a third cannot be added silently
- [x] The violation's two prompt hashes differ, so a retry that changed nothing cannot be recorded as one

---

## Phase 7: Tier routing and purchase intent

**User stories**: 23, 24

### What to build

Which model answers, and what happens to what it says. The routing table — `{first_seen, conversation, reflection, purchase, claim_audit}` to tier B, everything else to tier A — is configuration, not code. A purchase-intent task is scored through `elicitation` when a passing anchor version is pinned; when none is, the verbatim is kept and the recorded elicitation failure stands in place of the distribution, so a run without intent data is visibly that.

### Acceptance criteria

- [x] Tier routing matches the configuration table for every event class, and the table is data a study can change
- [x] A purchase-intent turn with a pinned, passing anchor version records an `SsrResult` on the reaction
- [x] A purchase-intent turn with no pinned version records the verbatim and the elicitation failure, and no distribution
- [x] No code path asks a model for a rating, asserted over the module
- [x] Tier-B importance rating rides inside the call already being made, adding no call of its own
- [x] Tier-A turns in one tick coalesce into batches through the inference client rather than one call per persona

---

## Phase 8: The character probe

**User stories**: 19, 20

### What to build

Turning drift from a worry into a number. A seeded 2% sample of activated personas, every 10 ticks, is asked two or three questions whose answers are already in that persona's attributes. The answers are compared with the attributes, and the disagreement rate is recorded per run as its own trace payload.

### Acceptance criteria

- [x] The probe samples the configured share of activated personas on the configured cadence, derived from the run seed
- [x] Probe questions are drawn from the persona's own attributes, and a persona with a different attribute is asked a different question
- [x] The probe runs on tier A and adds no tier-B call
- [x] A probe result is recorded with the persona, the questions, the answers and whether each agreed
- [x] The run's disagreement rate is derivable from the trace alone
- [x] A probe answer that disagrees does not fail the turn or alter the reaction — drift is measured, not corrected

---

## Phase 9: State round-trip and reconciliation

**User stories**: 11

### What to build

Proof that the state crossing the boundary is the state the trace describes, and that two machines agree. State rebuilt by replaying a run's recorded events equals the state the run carried; two processes produce identical turns from identical jobs under a fixed seed. The architecture, salvage inventory and glossary are checked against what was built.

### Acceptance criteria

- [x] State rebuilt from replayed trace events equals the state carried through the run, memory for memory and belief for belief
- [x] Two processes produce identical outcomes from identical jobs under a fixed seed
- [x] A resumed run continues from checkpointed state without re-running completed turns
- [x] `FINAL_ARCH.md` §5.6 describes the batch interface and the state that crosses it, and no claim contradicts the code
- [x] `SALVAGE.md` and `CONTEXT.md` describe what was built
- [x] Any defect this phase exposes is fixed with a test that fails on the old code
