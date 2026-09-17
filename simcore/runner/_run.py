"""The tick loop: one world end to end.

The runner asks `world` for a delta, turns its presentations into `TurnJob`s
carrying each persona's state, hands them to `agent` as one batch, feeds the
completed turns back into `world`, and writes the tick's events with its
`tick_closed` through the trace port in one call. Sequence numbers, event
ids and the tick boundary are settled here and never revisited.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from simcore.agent import advance_state
from simcore.schemas import (
    SCHEMA_VERSION,
    Beliefs,
    CompletedTurn,
    Degraded,
    LifecycleRecorded,
    PartitionHeader,
    PersonaState,
    Population,
    Presentation,
    RunConfig,
    RunRegistryEntry,
    RunResult,
    RunStatus,
    TraceEvent,
    Turn,
    TurnFailure,
    TurnFailureKind,
    TurnJob,
    TurnOutcome,
    WorldOutcome,
    WorldStatus,
    BriefPack,
    CostRecorded,
    derive_world_id,
)
from simcore.schemas.base import canonical_hash
from simcore.schemas.enums import LifecyclePhase
from simcore.schemas.trace import (
    BeliefSnapshot,
    ExposureDropped,
    GuardrailViolation,
    InterventionApplied,
    MemoryRecorded,
    ProbeRecorded,
    StimulusPublished,
    TickClosed,
    TurnRecorded,
)

from ._ids import event_id
from ._plans import LadderConfig, TickPlan
from ._resume import last_closed_tick, next_seq, rebuild_persona_states, turns_by_tick, validate_checkpoint
from ._version import ENGINE_VERSION


WorldFactory = Callable[[PartitionHeader], object]
AgentFn = Callable[[list[TurnJob]], Sequence[TurnOutcome]]


def _persona_index(population: Population) -> dict[str, object]:
    return {p.persona_id: p for p in population.personas}


def _initial_states(population: Population) -> dict[str, PersonaState]:
    states: dict[str, PersonaState] = {}
    for persona in population.personas:
        states[persona.persona_id] = PersonaState(
            persona_id=persona.persona_id,
            beliefs=persona.baseline_beliefs,
            memories=(),
            last_reflection_tick=0,
            turns_since_reflection=0,
        )
    return states


def _make_event(world_id: str, tick: int, seq: int, payload: object, persona_id: str | None = None) -> TraceEvent:
    return TraceEvent.model_validate(
        {
            "event_id": event_id(world_id, seq),
            "world_id": world_id,
            "tick": tick,
            "seq": seq,
            "persona_id": persona_id,
            "payload": payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload,
        }
    )


def _turn_events(
    world_id: str,
    tick: int,
    seq_start: int,
    presentation: Presentation,
    outcome: TurnOutcome,
    state: PersonaState,
    memory_cap: int = 50,
) -> tuple[list[TraceEvent], PersonaState]:
    """Events for one persona's outcome; returns them and the state to carry forward."""
    events: list[TraceEvent] = []
    seq = seq_start
    persona_id = presentation.impression.persona_id

    def _next(payload: object, pid: str | None = None) -> TraceEvent:
        nonlocal seq
        event = _make_event(world_id, tick, seq, payload, pid)
        seq += 1
        events.append(event)
        return event

    if isinstance(outcome, CompletedTurn):
        _next(
            TurnRecorded(
                kind="turn",
                turn=Turn(
                    impression=presentation.impression,
                    view=presentation.view,
                    reaction=outcome.turn.reaction,
                ),
                template_id=outcome.template_id,
                prompt_hash=outcome.prompt_hash,
                persona_block_hash=outcome.persona_block_hash,
                memory_ids=outcome.memory_ids,
                rejected_prompt_hashes=outcome.rejected_prompt_hashes,
            ),
            persona_id,
        )
        for memory in outcome.memories:
            _next(MemoryRecorded(kind="memory", memory=memory.model_copy(update={"embedding": None, "embed_model_id": None}) if memory.embedding is not None else memory), persona_id)
        new_state = advance_state(state, outcome, tick, memory_cap=memory_cap)
        _next(BeliefSnapshot(kind="belief_snapshot", beliefs=new_state.beliefs), persona_id)
        if outcome.probe is not None:
            _next(ProbeRecorded(kind="probe", result=outcome.probe), persona_id)
        for cost in outcome.costs:
            _next(cost, persona_id)
        return events, new_state
    assert isinstance(outcome, TurnFailure)
    if outcome.kind is TurnFailureKind.GUARDRAIL_VIOLATION:
        assert outcome.rule is not None and len(outcome.prompt_hashes) == 2
        _next(
            GuardrailViolation(
                kind="guardrail_violation",
                impression=presentation.impression,
                view=presentation.view,
                prompt_hashes=(outcome.prompt_hashes[0], outcome.prompt_hashes[1]),  # type: ignore[arg-type]
                rule=outcome.rule,
            ),
            persona_id,
        )
    for cost in outcome.costs:
        _next(cost, persona_id)
    return events, state


def _replay_world_to(world: object, recorded: dict[int, list[Turn]], through_tick: int) -> None:
    """Position a fresh world after `through_tick` by replaying recorded turns."""
    if through_tick < 0:
        return
    world.reset()  # type: ignore[attr-defined]
    for tick in range(1, through_tick + 1):
        world.step(tick, recorded.get(tick - 1, []))  # type: ignore[attr-defined]


def run_world(
    header: PartitionHeader,
    population: Population,
    trace: object,
    world: object,
    agent_fn: AgentFn,
    plan: TickPlan | None = None,
    memory_cap: int = 50,
    starting_seq: int = 0,
    starting_states: dict[str, PersonaState] | None = None,
    from_tick: int = -1,
    previous_turns: list[Turn] | None = None,
) -> tuple[tuple[TraceEvent, ...], dict[str, PersonaState], int]:
    """Drive one world from after `from_tick` to its horizon.

    Returns all newly written events, the carried states, and the next free
    sequence number. Each tick is buffered and written in one call with its
    `tick_closed` last; an interruption writes nothing for that tick.
    """
    _ = plan
    world_id = header.world_id
    states = dict(starting_states) if starting_states is not None else _initial_states(population)
    personas = _persona_index(population)
    seq = starting_seq
    written: list[TraceEvent] = []
    horizon = header.scenario.horizon_ticks

    # Tick 0 comes from reset; later ticks from step(previous turns).
    # When resuming, the caller already replayed the world; the previous
    # tick's turns come from the record so the next step feeds correctly.
    previous: list[Turn] = list(previous_turns) if previous_turns is not None else []
    # When resuming, previous turns must be re-fed? The caller replays the
    # world itself; here we only continue. The world object handed in is
    # already positioned after `from_tick`.
    for tick in range(from_tick + 1, horizon):
        if tick == 0:
            delta = world.reset()  # type: ignore[attr-defined]
        else:
            delta = world.step(tick, previous)  # type: ignore[attr-defined]
        # Build jobs for this tick's presentations.
        jobs: list[TurnJob] = []
        order: list[Presentation] = list(delta.presentations)
        for presentation in order:
            pid = presentation.impression.persona_id
            persona = personas[pid]
            jobs.append(
                TurnJob.model_validate(
                    {
                        "persona": persona.model_dump(mode="json"),
                        "state": states[pid].model_dump(mode="json"),
                        "presentation": presentation.model_dump(mode="json"),
                        "task": "reaction",
                    }
                )
            )
        # One batch to the agent. A raise here writes nothing for this tick.
        outcomes = tuple(agent_fn(jobs))
        if len(outcomes) != len(jobs):
            raise ValueError(f"agent returned {len(outcomes)} outcomes for {len(jobs)} jobs")
        # Buffer the tick.
        batch: list[TraceEvent] = []

        def _emit(payload: object, pid: str | None = None) -> None:
            nonlocal seq
            batch.append(_make_event(world_id, tick, seq, payload, pid))
            seq += 1

        if tick == 0:
            _emit(LifecycleRecorded(kind="lifecycle", phase=LifecyclePhase.STARTED))
        for stimulus in delta.published:
            _emit(StimulusPublished(kind="stimulus_published", stimulus=stimulus))
        for kind in delta.interventions:
            _emit(InterventionApplied(kind="intervention", intervention_kind=kind))
        for dropped in sorted(delta.dropped, key=lambda d: (d.persona_id, d.drop.stimulus_id)):
            _emit(
                ExposureDropped(
                    kind="exposure_dropped",
                    stimulus_id=dropped.drop.stimulus_id,
                    channel=dropped.drop.channel,
                    reason=dropped.drop.reason,
                ),
                dropped.persona_id,
            )
        next_turns: list[Turn] = []
        for presentation, outcome in zip(order, outcomes, strict=True):
            pid = presentation.impression.persona_id
            tick_events, new_state = _turn_events(world_id, tick, seq, presentation, outcome, states[pid], memory_cap)
            states[pid] = new_state
            for event in tick_events:
                assert event.seq == seq
                batch.append(event)
                seq += 1
            if isinstance(outcome, CompletedTurn):
                next_turns.append(outcome.turn)
        _emit(TickClosed(kind="tick_closed"))
        # One call per tick, tick_closed last.
        trace.write(batch)  # type: ignore[attr-defined]
        written.extend(batch)
        previous = next_turns
    # Lifecycle close: after the final tick_closed, same tick, no new close.
    closing: list[TraceEvent] = []
    closing.append(_make_event(world_id, horizon - 1, seq, LifecycleRecorded(kind="lifecycle", phase=LifecyclePhase.COMPLETED)))
    seq += 1
    trace.write(closing)  # type: ignore[attr-defined]
    written.extend(closing)
    return tuple(written), states, seq


def run(
    config: RunConfig,
    *,
    pack: BriefPack,
    population: Population,
    trace: object,
    registry: object,
    world_factory: WorldFactory,
    agent_fn: AgentFn,
    ladder: LadderConfig | None = None,
    engine_version: str = ENGINE_VERSION,
    memory_cap: int = 50,
    checkpoints: dict[str, dict] | None = None,
) -> RunResult:
    """Run every world of the configuration to its horizon.

    Resume needs nothing but the trace and the registry entry: worlds pick
    up after their last closed tick, personas are rebuilt from the record,
    and completed ticks are never re-run. A checkpoint, if present, is a
    cache validated against the record and discarded on disagreement.
    """
    _ = ladder
    running = RunRegistryEntry.model_validate(
        {
            "config": config.model_dump(mode="json"),
            "contract_version": SCHEMA_VERSION,
            "status": RunStatus.RUNNING.value,
            "engine_version": engine_version,
            "recorded_cost": 0.0,
            "discarded_ticks": 0,
        }
    )
    if registry.entry(config.run_id) is None:  # type: ignore[attr-defined]
        registry.record(running)  # type: ignore[attr-defined]
    outcomes: list[WorldOutcome] = []
    recorded_cost = 0.0
    for scenario in config.scenarios:
        for seed in config.seeds:
            world_id = derive_world_id(scenario, seed, config.population_hash)
            header = PartitionHeader.model_validate(
                {
                    "contract_version": SCHEMA_VERSION,
                    "config": config.model_dump(mode="json"),
                    "pack": pack.model_dump(mode="json"),
                    "population": population.manifest.model_dump(mode="json"),
                    "scenario": scenario.model_dump(mode="json"),
                    "replicate_seed": seed,
                }
            )
            assert header.world_id == world_id
            existing = trace.events_for(world_id) if hasattr(trace, "events_for") else ()  # type: ignore[attr-defined]
            closed = last_closed_tick(tuple(existing))
            seq = next_seq(tuple(existing))
            if closed >= 0:
                rebuilt = rebuild_persona_states(population, tuple(existing), memory_cap=memory_cap)
                checkpoint = (checkpoints or {}).get(world_id)
                if checkpoint is not None and not validate_checkpoint(checkpoint, rebuilt, seq):
                    checkpoint = None
                states = dict(rebuilt) if checkpoint is None else dict(checkpoint["states"])
                recorded = turns_by_tick(tuple(existing))
                world = world_factory(header)
                _replay_world_to(world, recorded, closed)
                previous = list(recorded.get(closed, []))
            else:
                states = {}
                for persona in population.personas:
                    states[persona.persona_id] = PersonaState(
                        persona_id=persona.persona_id,
                        beliefs=persona.baseline_beliefs,
                        memories=(),
                        last_reflection_tick=0,
                        turns_since_reflection=0,
                    )
                world = world_factory(header)
                previous = []
            events, _states, _seq = run_world(
                header,
                population,
                trace,
                world,
                agent_fn,
                memory_cap=memory_cap,
                starting_seq=seq,
                starting_states=states,
                from_tick=closed,
                previous_turns=previous,
            )
            for event in tuple(existing) + events:
                payload = event.payload
                if payload.kind == "cost" and payload.cost is not None:
                    recorded_cost += float(payload.cost)
            outcomes.append(
                WorldOutcome.model_validate(
                    {
                        "world_id": world_id,
                        "status": WorldStatus.COMPLETED.value,
                        "last_closed_tick": scenario.horizon_ticks - 1,
                        "rungs": [],
                    }
                )
            )
    status = RunStatus.COMPLETED if all(o.status is WorldStatus.COMPLETED for o in outcomes) else RunStatus.PARTIAL
    entry = RunRegistryEntry.model_validate(
        {
            "config": config.model_dump(mode="json"),
            "contract_version": SCHEMA_VERSION,
            "status": status.value,
            "engine_version": engine_version,
            "recorded_cost": recorded_cost,
            "discarded_ticks": 0,
        }
    )
    registry.record(entry)  # type: ignore[attr-defined]
    return RunResult.model_validate(
        {"registry": entry.model_dump(mode="json"), "outcomes": [o.model_dump(mode="json") for o in outcomes]}
    )
