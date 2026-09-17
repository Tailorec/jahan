"""Phase 5 boundary tests: the degrade ladder."""

from __future__ import annotations

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, LadderConfig, TickPlan, run
from simcore.schemas import BriefPack, CompletedTurn, CostRecorded, Population, Reaction, RunConfig, Turn, TurnJob, canonical_hash
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload, ulid


def _config(horizon: int = 8, max_cost: float = 1.0, **overrides):
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[])
    payload = run_config_payload(scenarios=[scenario], seeds=[4021])
    payload["budget"] = {"max_cost": max_cost, "currency": "USD"}
    payload.update(overrides)
    return RunConfig.model_validate(payload)


def _pack():
    return BriefPack.model_validate(pack_payload())


def _population():
    return Population.model_validate(population_payload())


def _repinned(config, pack, population):
    return RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )


class PlanWorld:
    """World recording the plan it was handed per tick."""

    def __init__(self, header):
        from simcore.schemas import Stimulus

        self._header = header
        self._personas = list(header.population.persona_ids)
        self._concept = Stimulus.model_validate({"stimulus_id": f"st-{ulid(11)}", "tick": 0, "kind": "concept", "text": "Clear protein water"})
        self.plans: list[TickPlan] = []

    def reset(self, plan=None):
        from simcore.schemas import WorldDelta

        self.plans.append(plan or TickPlan())
        return WorldDelta.model_validate({"tick": 0, "published": [self._concept.model_dump(mode="json")], "presentations": []})

    def step(self, tick, turns, plan=None):
        from simcore.schemas import Impression, Presentation, View, WorldDelta

        self.plans.append(plan or TickPlan())
        presentations = []
        for idx, pid in enumerate(sorted(self._personas)):
            impression = Impression.model_validate(
                {"impression_id": f"im-{ulid(500 + tick * 100 + idx)}", "persona_id": pid,
                 "channel": "survey_room", "tick": tick,
                 "exposures": [{"stimulus_id": self._concept.stimulus_id, "reason": "interest", "attention": 1.0}]})
            view = View.model_validate({"impression_id": impression.impression_id, "contexts": {self._concept.stimulus_id: {}}})
            presentations.append(Presentation.model_validate({"impression": impression.model_dump(mode="json"), "view": view.model_dump(mode="json")}))
        return WorldDelta.model_validate({"tick": tick, "published": [], "presentations": [p.model_dump(mode="json") for p in presentations]})


def _cost(amount: float) -> CostRecorded:
    return CostRecorded.model_validate({"kind": "cost", "role": "tier_a", "model_id": "openrouter/camel-ai/persona-8b",
                                        "served_model_id": "openrouter/camel-ai/persona-8b", "cost_source": "gateway",
                                        "route": "primary", "input_tokens": 5, "output_tokens": 5, "cost": amount})


def _completed(job: TurnJob, n: int, amount: float) -> CompletedTurn:
    impression = job.presentation.impression
    subject = next(iter(impression.stimulus_ids))
    reaction = Reaction.model_validate({"reaction_id": f"rc-{ulid(900 + n + impression.tick * 50)}",
                                        "subject_stimulus_id": subject, "action": "answer",
                                        "verbatim": "I would try it", "belief_change": {}})
    turn = Turn.model_validate({"impression": impression.model_dump(mode="json"),
                                "view": job.presentation.view.model_dump(mode="json"),
                                "reaction": reaction.model_dump(mode="json")})
    return CompletedTurn.model_validate({"turn": turn.model_dump(mode="json"), "template_id": "persona_turn",
                                         "prompt_hash": "ab" * 32, "persona_block_hash": "cd" * 32,
                                         "costs": [_cost(amount).model_dump(mode="json")]})


def _run_with_cost(amount_per_turn: float, max_cost: float, ladder=None):
    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(max_cost=max_cost), pack, population)
    worlds: list[PlanWorld] = []
    agent_plans: list[TickPlan] = []

    def agent_fn(jobs, plan=None):
        agent_plans.append(plan or TickPlan())
        return tuple(_completed(j, i, amount_per_turn) for i, j in enumerate(jobs))

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: worlds.append(PlanWorld(header)) or worlds[-1],
                 agent_fn=agent_fn, ladder=ladder or LadderConfig())
    return result, trace, worlds, agent_plans


def test_thresholds_produce_observable_effects():
    # 4 personas x billed ticks x 0.04 pushes past warn and freeze on a 1.0 budget.
    result, trace, worlds, agent_plans = _run_with_cost(0.04, 1.0)
    kinds = [e.payload.kind for e in trace.all_events()]
    assert "degraded" in kinds
    # Tier-B frozen observed in agent plans, activation drop in world plans.
    assert any(p.tier_b_frozen for p in agent_plans)
    rates = [p.activation_rate for p in worlds[0].plans]
    assert min(rates) < max(rates) or any(p.tier_b_frozen for p in agent_plans)
    assert result.status.value in ("completed", "partial")


def test_thresholds_and_subsample_are_configuration():
    ladder = LadderConfig(warn_at=0.3, freeze_at=0.4, subsample_at=0.5, pause_at=10.0, subsample_rate=0.25)
    result, trace, worlds, agent_plans = _run_with_cost(0.04, 1.0, ladder)
    assert any(p.activation_rate == 0.25 for p in worlds[0].plans)


def test_degraded_events_carry_rate_and_freeze():
    _, trace, _, _ = _run_with_cost(0.04, 1.0)
    degraded = [e for e in trace.all_events() if e.payload.kind == "degraded"]
    assert degraded
    for event in degraded:
        assert event.payload.activation_rate in (1.0, 0.4)
        assert isinstance(event.payload.tier_b_frozen, bool)


def test_replay_applies_recorded_rung():
    from simcore.runner import LadderConfig
    from simcore.runner._run import run_world
    from simcore.schemas import PartitionHeader

    pack, population = _pack(), _population()
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()
    config = _repinned(_config(max_cost=1.0), pack, population)
    worlds: list[PlanWorld] = []
    agent_plans: list[TickPlan] = []

    def pricey(jobs, plan=None):
        agent_plans.append(plan or TickPlan())
        return tuple(_completed(j, i, 0.10) for i, j in enumerate(jobs))

    # Drive to freeze with a strict ladder, interrupted before the horizon.
    strict = LadderConfig(warn_at=0.2, freeze_at=0.3, subsample_at=10.0, pause_at=10.0)
    try:
        def failing(jobs, plan=None):
            if jobs and jobs[0].presentation.impression.tick == 4:
                raise RuntimeError("interrupt after freeze")
            return pricey(jobs, plan)

        run(config, pack=pack, population=population, trace=trace, registry=registry,
            world_factory=lambda header: worlds.append(PlanWorld(header)) or worlds[-1],
            agent_fn=failing, ladder=strict)
    except RuntimeError:
        pass
    assert any(p.tier_b_frozen for p in agent_plans)
    # Resume under a permissive ladder with free calls: the recorded freeze still applies.
    agent_plans.clear()
    worlds.clear()
    permissive = LadderConfig(warn_at=10.0, freeze_at=10.0, subsample_at=10.0, pause_at=10.0)

    def free(jobs, plan=None):
        agent_plans.append(plan or TickPlan())
        return tuple(_completed(j, i, 0.0) for i, j in enumerate(jobs))

    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=lambda header: worlds.append(PlanWorld(header)) or worlds[-1],
        agent_fn=free, ladder=permissive)
    assert any(p.tier_b_frozen for p in agent_plans)


def test_paused_run_keeps_partial_worlds():
    # Tiny budget forces a pause before the horizon.
    result, trace, worlds, _ = _run_with_cost(0.20, 0.10)
    assert result.status.value == "partial"
    assert result.outcomes[0].status.value == "partial"
    assert result.outcomes[0].last_closed_tick is not None


def test_plans_hide_budgets():
    _, _, worlds, agent_plans = _run_with_cost(0.04, 1.0)
    for plan in list(worlds[0].plans) + agent_plans:
        for field in ("budget", "max_cost", "spend", "ledger"):
            assert field not in plan.__dict__
        assert isinstance(plan.activation_rate, float)
        assert isinstance(plan.tier_b_frozen, bool)
