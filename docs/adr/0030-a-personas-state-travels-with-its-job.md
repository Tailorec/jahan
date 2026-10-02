# A persona's state travels with its job, and the trace is the only store

`agent` needs a persona's current beliefs to condition a prompt, its past memories to retrieve from, and it produces
new ones. The architecture's sketch — `turn(persona, impression, view) -> Reaction` — carries none of that, so the
state had to live somewhere: inside the agent, behind a memory port, or across the boundary.

It travels across the boundary. A turn takes the persona, its presentation and a `PersonaState` — beliefs, the
persona's own memory events, and the counters that decide reflection — and returns the reaction together with the
new memories and the belief change. The agent itself stores nothing and is a pure function of its inputs. The trace
is the store: memory events, belief snapshots and character-probe results are trace events like any other, and the
runner is their only writer.

The decision is driven by the runner. A study spreads personas across workers, and no worker holds them all. If the
agent owned the store, each persona would be pinned to the worker holding its history and a resume would replay a
whole trace into memory. With state crossing the boundary, any worker takes any persona, a checkpoint is state that
has already been serialised, and rebuilding state from the trace is an independent check on the checkpoint rather
than the only way to get it back.

Retrieval stays arithmetic the engine owns: `exp(-Δt/τ) · importance · cos(memory, stimulus)` over one persona's own
memories, embedded once when written through the existing `EmbedPort`. Importance comes from a rule — the action
taken and the size of the belief change — except on tier B events, where the model is already being paid for and can
rate it in the same call. A persona's memories are capped, with reflection consolidating older ones into fewer,
higher-importance summaries, so neither the prompt nor the state grows without bound.

## Considered options

An agent-internal store rebuilt by replay, mirroring `world` (ADR 0011), was rejected: the world is a single
authority with one writer per run, while persona state is sharded across workers and must be addressable. A
`MemoryPort` the agent writes through was rejected because it puts persistence back inside the module that owns the
conditioning invariant, and makes deterministic replay harder to test. A memory framework (LangChain, LlamaIndex,
Mem0, Letta) was rejected on the same grounds as provider SDKs (ADR 0021), and more sharply: such a framework owns
prompt assembly and retrieval policy, which is exactly the invariant that decides this engine's validity and cannot
be co-owned. A vector database was rejected at this scale — every search is scoped to one persona's few dozen
memories, which is a dot product, not an index.

## Consequences

The agent's interface is wider than the architecture's sketch, and `FINAL_ARCH.md` §5.6 is amended to match. The
runner owns persistence, checkpointing and resume, and gains a determinism check it did not have: state rebuilt by
replaying a trace must equal the checkpoint written during the run. Memory events, belief snapshots and probe
results need trace payloads, which land in `jahan/schemas` before either the agent or the world branch begins.
