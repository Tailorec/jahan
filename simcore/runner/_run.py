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
from ._refusal import ResumeRefused, check_resume_inputs
from ._resume import last_closed_tick, next_seq, rebuild_persona_states, turns_by_tick, validate_checkpoint
from ._version import ENGINE_VERSION


WorldFactory = Callable[[PartitionHeader], object]
AgentFn = Callable[[list[TurnJob]], Sequence[TurnOutcome]]


class WorldFailed(Exception):
    """A world that raised — outage, corrupt scenario, exhausted circuit.

    Isolated: the world is recorded as partial or not started and the rest
    of the run continues. Crashes (agent failures mid-tick for resume) are a
    different thing and still propagate so the tick writes nothing and the
    run can resume it.
    """


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


def _replay_world_to(world: object, recorded: dict[int, list[Turn]], through_tick: int, plan: TickPlan | None = None) -> None:
    """Position a fresh world after `through_tick` by replaying recorded turns."""
    if through_tick < 0:
        return
    _call_reset(world, plan)
    for tick in range(1, through_tick + 1):
        _call_step(world, tick, recorded.get(tick - 1, []), plan)


def _apply_plan(world: object, plan: TickPlan | None) -> None:
    """Hand a real world its per-tick plan without telling it about budgets."""
    if plan is None:
        return
    config = getattr(world, "_config", None)
    if config is not None and hasattr(config, "activation_rate"):
        try:
            import dataclasses

            if dataclasses.is_dataclass(config):
                object.__setattr__(world, "_config", dataclasses.replace(config, activation_rate=plan.activation_rate))
                return
        except Exception:
            pass
        try:
            world._config = config.model_copy(update={"activation_rate": plan.activation_rate})  # type: ignore[attr-defined]
        except Exception:
            pass


def _call_reset(world: object, plan: TickPlan | None):
    _apply_plan(world, plan)
    reset = getattr(world, "reset")
    try:
        import inspect

        if plan is not None and "plan" in inspect.signature(reset).parameters:
            return reset(plan=plan)
    except (TypeError, ValueError):
        pass
    return world.reset()  # type: ignore[attr-defined]


def _call_step(world: object, tick: int, turns: list[Turn], plan: TickPlan | None):
    _apply_plan(world, plan)
    step = getattr(world, "step")
    try:
        import inspect

        if plan is not None and "plan" in inspect.signature(step).parameters:
            return step(tick, turns, plan=plan)
    except (TypeError, ValueError):
        pass
    return world.step(tick, turns)  # type: ignore[attr-defined]


def _call_agent(agent_fn: AgentFn, jobs: list[TurnJob], plan: TickPlan | None):
    try:
        import inspect

        if plan is not None and len(inspect.signature(agent_fn).parameters) >= 2:
            return tuple(agent_fn(jobs, plan))  # type: ignore[call-arg]
    except (TypeError, ValueError):
        pass
    return tuple(agent_fn(jobs))


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
    budget_max: float | None = None,
    ladder: LadderConfig | None = None,
    discarded_ticks: int = 0,
    starting_rung: object = None,
) -> tuple[tuple[TraceEvent, ...], dict[str, PersonaState], int, object, bool]:
    """Drive one world from after `from_tick` to its horizon under the ladder.

    Returns newly written events, carried states, next seq, the last rung in
    force, and whether the world paused. Each tick is buffered and written in
    one call with its `tick_closed` last; an interruption writes nothing.
    """
    from simcore.schemas.enums import RUNG_ORDER

    from ._ladder import last_recorded_rung, plan_for, rung_for
    from ._ledger import pessimistic_figure, unpriceable

    ladder_cfg = ladder or LadderConfig()
    world_id = header.world_id
    states = dict(starting_states) if starting_states is not None else _initial_states(population)
    personas = _persona_index(population)
    seq = starting_seq
    written: list[TraceEvent] = []
    horizon = header.scenario.horizon_ticks
    current = starting_rung
    if current is None and from_tick >= 0 and hasattr(trace, "events_for"):
        try:
            current = last_recorded_rung(tuple(trace.events_for(world_id)))  # type: ignore[attr-defined]
        except Exception:
            current = None

    def _all_recorded() -> tuple[TraceEvent, ...]:
        try:
            return tuple(trace.all_events())  # type: ignore[attr-defined]
        except Exception:
            return tuple(written)

    def _figure() -> float:
        try:
            all_events = tuple(trace.all_events())  # type: ignore[attr-defined]
        except Exception:
            all_events = tuple(written)
        return pessimistic_figure(all_events, discarded_ticks)

    # What this world's personas are asked is the scenario's to say (a concept test asks purchase
    # intent; a feed study asks for reactions), and the header carries the scenario.
    elicits = header.scenario.elicits
    previous: list[Turn] = list(previous_turns) if previous_turns is not None else []
    paused = bool(current is not None and getattr(current, "value", None) == "pause")
    if paused:
        return tuple(written), states, seq, current, True
    for tick in range(from_tick + 1, horizon):
        ratio = (_figure() / budget_max) if budget_max else 0.0
        candidate = rung_for(ratio, ladder_cfg)
        # Calls were billed and nothing anywhere carries a price, so there is no figure to
        # enforce a ceiling against. A budget measured against invented prices is not a budget,
        # so the run stops rather than spending blind.
        if budget_max and unpriceable(_all_recorded()):
            candidate = RUNG_ORDER[-1]
        # Escalation only; a replay applies the recorded rung rather than
        # recomputing a lower one from the ledger.
        effective = candidate
        if current is not None:
            if effective is None:
                effective = current
            elif RUNG_ORDER.index(effective) < RUNG_ORDER.index(current):
                effective = current
        if effective is not None and effective.value == "pause" and effective != current:
            batch: list[TraceEvent] = []
            tick_plan = plan_for(effective, ladder_cfg)
            batch.append(_make_event(world_id, tick, seq, Degraded(kind="degraded", rung=effective, activation_rate=tick_plan.activation_rate, tier_b_frozen=tick_plan.tier_b_frozen)))
            seq += 1
            batch.append(_make_event(world_id, tick, seq, LifecycleRecorded(kind="lifecycle", phase=LifecyclePhase.PAUSED)))
            seq += 1
            trace.write(batch)  # type: ignore[attr-defined]
            written.extend(batch)
            current = effective
            paused = True
            break
        if effective is not None and effective.value == "pause":
            # Already paused (resume): stay paused without re-recording.
            paused = True
            break
        tick_plan = plan_for(effective, ladder_cfg)
        if tick == 0:
            delta = _call_reset(world, tick_plan)
        else:
            delta = _call_step(world, tick, previous, tick_plan)
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
                        "task": elicits.value,
                    }
                )
            )
        outcomes = _call_agent(agent_fn, jobs, tick_plan)
        if len(outcomes) != len(jobs):
            raise ValueError(f"agent returned {len(outcomes)} outcomes for {len(jobs)} jobs")
        batch = []

        def _emit(payload: object, pid: str | None = None, at_tick: int = tick) -> None:
            nonlocal seq
            batch.append(_make_event(world_id, at_tick, seq, payload, pid))
            seq += 1

        if tick == 0:
            _emit(LifecycleRecorded(kind="lifecycle", phase=LifecyclePhase.STARTED))
            # What every persona already believed. A belief history is derived from snapshots and
            # the turns between them, so without a baseline the first tick's movement has nothing
            # to move from and is dropped — and the population's starting beliefs, which the trace
            # cannot see, would appear nowhere in the record.
            for persona_id in sorted(states):
                _emit(BeliefSnapshot(kind="belief_snapshot", beliefs=states[persona_id].beliefs), persona_id)
        if effective is not None and effective != current:
            _emit(Degraded(kind="degraded", rung=effective, activation_rate=tick_plan.activation_rate, tier_b_frozen=tick_plan.tier_b_frozen))
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
        trace.write(batch)  # type: ignore[attr-defined]
        written.extend(batch)
        previous = next_turns
        current = effective
    if not paused:
        closing: list[TraceEvent] = []
        closing.append(_make_event(world_id, horizon - 1, seq, LifecycleRecorded(kind="lifecycle", phase=LifecyclePhase.COMPLETED)))
        seq += 1
        trace.write(closing)  # type: ignore[attr-defined]
        written.extend(closing)
    return tuple(written), states, seq, current, paused


def _finalize(trace, world_id: str) -> None:
    """Ask the record to become the lasting one. A sink without the call is left alone."""
    finalize = getattr(trace, "finalize", None)
    if finalize is None:
        return
    finalize(world_id)


def _remember(registry, entry: RunRegistryEntry) -> None:
    """Pin a run's entry the first time and move it afterwards.

    `record` refuses a second entry for a run, by design — nothing silently replaces a study —
    so everything after the first write is an update. Calling `record` twice worked against an
    upserting fake and raised against the real registry, which would have ended every real run
    on its last write.
    """
    if registry.entry(entry.config.run_id) is None:
        registry.record(entry)
    else:
        registry.update(entry)


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
    force: bool = False,
    max_workers: int = 1,
) -> RunResult:
    """Run every world of the configuration to its horizon.

    Resume needs nothing but the trace and the registry entry: worlds pick
    up after their last closed tick, personas are rebuilt from the record,
    and completed ticks are never re-run. A checkpoint, if present, is a
    cache validated against the record and discarded on disagreement.

    A resume whose inputs or engine moved is refused, naming what moved; a
    forced resume proceeds, is recorded, and spans versions.

    A sweep is not a second concept: scenarios and seeds expand into worlds
    of one run sharing one budget. Worlds run in parallel, one process each
    in production (threads at this boundary, same seam), against that ledger.
    """
    ladder_cfg = ladder or LadderConfig()
    from ._ladder import last_recorded_rung, recorded_rungs
    from ._ledger import ledger_sum

    stored = registry.entry(config.run_id)  # type: ignore[attr-defined]
    forced_from: tuple[str, ...] = tuple(stored.forced_from) if stored is not None else ()
    base_discarded = 0
    if stored is not None:
        base_discarded = int(stored.discarded_ticks)
        try:
            check_resume_inputs(config, pack, population, engine_version, stored.config, stored.engine_version)
        except ResumeRefused:
            if not force:
                raise
            if hasattr(registry, "mark_forced"):
                registry.mark_forced(config.run_id)  # type: ignore[attr-defined]
            # The version it ran under before goes on the entry, so a result that spans engines
            # is marked in the record and not only in the process that forced it (ADR 0036).
            if stored.engine_version != engine_version and stored.engine_version not in forced_from:
                forced_from = (*forced_from, stored.engine_version)
    else:
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
        _remember(registry, running)
    # A resume that picks up an incomplete world lost the tick it was
    # interrupted in: unknown spend, counted before anything else resumes.
    pending_discarded = 0
    if stored is not None:
        for scenario in config.scenarios:
            for seed in config.seeds:
                world_id = derive_world_id(scenario, seed, config.population_hash)
                existing = trace.events_for(world_id) if hasattr(trace, "events_for") else ()  # type: ignore[attr-defined]
                if existing and last_closed_tick(tuple(existing)) < scenario.horizon_ticks - 1:
                    pending_discarded += 1
    if pending_discarded:
        _remember(
            registry,
            RunRegistryEntry.model_validate(
                {
                    "config": stored.config.model_dump(mode="json"),
                    "contract_version": SCHEMA_VERSION,
                    "status": RunStatus.RUNNING.value,
                    "engine_version": stored.engine_version,
                    "recorded_cost": float(stored.recorded_cost),
                    "discarded_ticks": base_discarded + pending_discarded,
                    "forced_from": list(forced_from),
                }
            )
        )
    from ._sweep import expand_sweep

    cells = expand_sweep(config)
    discarded_total = base_discarded + pending_discarded

    def _cell(cell: tuple) -> WorldOutcome:
        scenario, seed, world_id = cell
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
        try:
            existing = trace.events_for(world_id) if hasattr(trace, "events_for") else ()  # type: ignore[attr-defined]
            closed = last_closed_tick(tuple(existing))
            seq = next_seq(tuple(existing))
            starting_rung = last_recorded_rung(tuple(existing)) if closed >= 0 else None
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
        except ResumeRefused:
            raise
        except (WorldFailed, Exception):
            return WorldOutcome.model_validate(
                {"world_id": world_id, "status": WorldStatus.NOT_STARTED.value, "rungs": []}
            )
        try:
            events, _states, _seq, last_rung, paused = run_world(
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
                budget_max=float(config.budget.max_cost),
                ladder=ladder_cfg,
                discarded_ticks=discarded_total,
                starting_rung=starting_rung,
            )
        except ResumeRefused:
            raise
        except WorldFailed:
            existing_now = trace.events_for(world_id) if hasattr(trace, "events_for") else ()  # type: ignore[attr-defined]
            last_closed = last_closed_tick(tuple(existing_now))
            rungs = [r.value for r in recorded_rungs(tuple(existing_now))]
            if last_closed >= 0:
                return WorldOutcome.model_validate(
                    {
                        "world_id": world_id,
                        "status": WorldStatus.PARTIAL.value,
                        "last_closed_tick": last_closed,
                        "rungs": rungs,
                    }
                )
            return WorldOutcome.model_validate(
                {"world_id": world_id, "status": WorldStatus.NOT_STARTED.value, "rungs": []}
            )
        existing_now = trace.events_for(world_id) if hasattr(trace, "events_for") else ()  # type: ignore[attr-defined]
        rungs = [r.value for r in recorded_rungs(tuple(existing_now))]
        if not paused:
            # A world that reached its horizon is finished, so its live record becomes its
            # lasting one. Nothing asked for this before, so a completed study stayed in the
            # live store and every read of it kept answering from there.
            _finalize(trace, world_id)
        if paused:
            last_closed = last_closed_tick(tuple(existing_now))
            return WorldOutcome.model_validate(
                {
                    "world_id": world_id,
                    "status": WorldStatus.PARTIAL.value,
                    "last_closed_tick": last_closed if last_closed >= 0 else None,
                    "rungs": rungs,
                }
            )
        return WorldOutcome.model_validate(
            {
                "world_id": world_id,
                "status": WorldStatus.COMPLETED.value,
                "last_closed_tick": scenario.horizon_ticks - 1,
                "rungs": rungs,
            }
        )

    if max_workers and max_workers > 1:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            outcomes = list(pool.map(_cell, cells))
    else:
        outcomes = [_cell(cell) for cell in cells]
    # The ledger is derived: sum what the trace holds, never a kept number.
    recorded_cost, _ = ledger_sum(tuple(trace.all_events()) if hasattr(trace, "all_events") else ())  # type: ignore[attr-defined]
    status = RunStatus.COMPLETED if all(o.status is WorldStatus.COMPLETED for o in outcomes) else RunStatus.PARTIAL
    entry = RunRegistryEntry.model_validate(
        {
            "config": config.model_dump(mode="json"),
            "contract_version": SCHEMA_VERSION,
            "status": status.value,
            "engine_version": engine_version,
            "recorded_cost": recorded_cost,
            "discarded_ticks": discarded_total,
            "forced_from": list(forced_from),
        }
    )
    _remember(registry, entry)
    return RunResult.model_validate(
        {"registry": entry.model_dump(mode="json"), "outcomes": [o.model_dump(mode="json") for o in outcomes]}
    )
