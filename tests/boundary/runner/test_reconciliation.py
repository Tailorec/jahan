"""Phase 8 reconciliation: the real trace writer seam, partition validity, and end to end."""

from __future__ import annotations

import pytest

from simcore.runner import InMemoryRegistry, InMemoryTraceSink, RunnerTraceView, run
from simcore.schemas import BriefPack, EventFilter, Population, RunConfig, TracePartition, VerbatimGrouping, canonical_hash
from tests.study_builders import pack_payload, population_payload, run_config_payload, scenario_payload


def _pack():
    return BriefPack.model_validate(pack_payload())


def _population():
    return Population.model_validate(population_payload())


def _config(pins, horizon: int = 3):
    scenario = scenario_payload(horizon_ticks=horizon, interventions=[])
    payload = run_config_payload(scenarios=[scenario], seeds=[4021], template_hashes={"persona_turn": "ab" * 32})
    payload["pins"] = pins
    config = RunConfig.model_validate(payload)
    return config, scenario


def test_full_run_reads_back_identically_through_view():
    from simcore.runner import expand_sweep

    pack, population = _pack(), _population()
    pins = {"tier_a": "fake/chat", "tier_b": "fake/chat", "embed": "fake-embed"}
    config, _ = _config(pins)
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()

    from simcore.agent import AgentConfig, PersonaBlockCache
    from simcore.ports.fake import FakeChat, FakeEmbed
    from simcore.world import World, WorldConfig
    from tests.boundary.agent.support import answering

    chat, embed = FakeChat(responder=answering("answer", "I would try it after training")), FakeEmbed()
    blocks = PersonaBlockCache()
    agent_config = AgentConfig(run_seed=4021, horizon_ticks=3, template_id="persona_turn")

    def world_factory(header):
        return World(header, population=population, config=WorldConfig())

    def agent_fn(jobs, plan=None):
        from simcore.agent import turns as _turns

        return _turns(jobs, chat=chat, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=embed)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=world_factory, agent_fn=agent_fn)
    assert result.status.value == "completed"
    world_id = result.outcomes[0].world_id
    events = trace.events_for(world_id)
    view = RunnerTraceView(events)
    assert tuple(e.event_id for e in view.events(EventFilter())) == tuple(e.event_id for e in events)
    assert view.resolve([events[0].event_id])[0] == events[0]
    assert view.verbatims(VerbatimGrouping.PERSONA)
    with pytest.raises(KeyError):
        view.resolve(["ev-00000000000000000000000000"])


def test_recorded_events_validate_as_partition():
    pack, population = _pack(), _population()
    pins = {"tier_a": "fake/chat", "tier_b": "fake/chat", "embed": "fake-embed"}
    config, scenario = _config(pins)
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()

    from simcore.agent import AgentConfig, PersonaBlockCache
    from simcore.ports.fake import FakeChat, FakeEmbed
    from simcore.world import World, WorldConfig
    from tests.boundary.agent.support import answering

    chat, embed = FakeChat(responder=answering("answer", "I would try it")), FakeEmbed()
    blocks = PersonaBlockCache()
    agent_config = AgentConfig(run_seed=4021, horizon_ticks=3, template_id="persona_turn")

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: World(header, population=population, config=WorldConfig()),
                 agent_fn=lambda jobs, plan=None: __import__("simcore.agent", fromlist=["turns"]).turns(
                     jobs, chat=chat, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=embed))
    world_id = result.outcomes[0].world_id
    events = trace.events_for(world_id)
    header = {
        "contract_version": "1.0.0",
        "config": config.model_dump(mode="json"),
        "pack": pack.model_dump(mode="json"),
        "population": population.manifest.model_dump(mode="json"),
        "scenario": scenario,
        "replicate_seed": 4021,
    }
    partition = TracePartition.model_validate({"header": header, "events": [e.model_dump(mode="json") for e in events]})
    assert partition.header.world_id == world_id


def test_end_to_end_brief_to_trace_with_cost():
    pack, population = _pack(), _population()
    pins = {"tier_a": "fake/chat", "tier_b": "fake/chat", "embed": "fake-embed"}
    config, _ = _config(pins)
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()

    from simcore.agent import AgentConfig, PersonaBlockCache
    from simcore.ports.fake import FakeChat, FakeEmbed
    from simcore.world import World, WorldConfig
    from tests.boundary.agent.support import answering

    chat, embed = FakeChat(responder=answering("answer", "Clear protein water would help my training")), FakeEmbed()
    blocks = PersonaBlockCache()
    agent_config = AgentConfig(run_seed=4021, horizon_ticks=3, template_id="persona_turn")
    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=lambda header: World(header, population=population, config=WorldConfig()),
                 agent_fn=lambda jobs, plan=None: __import__("simcore.agent", fromlist=["turns"]).turns(
                     jobs, chat=chat, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=embed))
    entry = registry.entry(config.run_id)
    assert entry is not None
    assert entry.recorded_cost >= 0.0
    assert len(trace.all_events()) > 10
    assert result.outcomes[0].status.value == "completed"


def test_subsample_plan_reaches_real_world_activation():
    """Integration defect: the real world ignored the runner's plan until `WorldConfig.activation_rate` existed."""
    from simcore.world import WorldConfig

    assert WorldConfig(activation_rate=0.25).activation_rate == 0.25
    pack, population = _pack(), _population()
    pins = {"tier_a": "fake/chat", "tier_b": "fake/chat", "embed": "fake-embed"}
    config, _ = _config(pins)
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    trace, registry = InMemoryTraceSink(), InMemoryRegistry()

    from simcore.agent import AgentConfig, PersonaBlockCache
    from simcore.ports.fake import FakeChat, FakeEmbed
    from simcore.runner import LadderConfig
    from simcore.world import World
    from tests.boundary.agent.support import answering, by_template, reflecting

    chat, embed = FakeChat(responder=by_template({"persona_reflection": reflecting()})), FakeEmbed()
    blocks = PersonaBlockCache()
    agent_config = AgentConfig(run_seed=4021, horizon_ticks=8, template_id="persona_turn")
    seen_rates: list[float] = []

    def world_factory(header):
        # A ticked channel, so activation draws happen: the survey wave surveys everyone, never gated.
        world = World(header, population=population, config=WorldConfig(platform="social_feed"))
        orig_activated = world._activated

        def recording(tick):
            seen_rates.append(world._config.activation_rate)
            return orig_activated(tick)

        world._activated = recording  # type: ignore[method-assign]
        return world

    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "scenarios": [{**config.scenarios[0].model_dump(mode="json"), "horizon_ticks": 8}],
         "budget": {"max_cost": 0.5, "currency": "USD"}})
    run(config, pack=pack, population=population, trace=trace, registry=registry,
        world_factory=world_factory,
        agent_fn=lambda jobs, plan=None: __import__("simcore.agent", fromlist=["turns"]).turns(
            jobs, chat=chat, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=embed),
        ladder=LadderConfig(warn_at=0.0, freeze_at=0.0, subsample_at=0.0, pause_at=10.0, subsample_rate=0.25))
    assert any(rate == 0.25 for rate in seen_rates)


def test_a_run_moves_its_registry_entry_rather_than_recording_it_twice():
    """`record` pins a new run and refuses a second entry; `update` moves what the run learns.
    The runner called `record` at the start and again at the end, which the in-memory fake
    accepted as an upsert and the real registry refuses — so every real run would have crashed
    on its last write, and a resume on its first."""
    from simcore.runner import InMemoryRegistry

    registry = InMemoryRegistry()
    assert hasattr(registry, "update"), "the fake cannot move an entry"

    from simcore.agent import AgentConfig, PersonaBlockCache
    from simcore.agent import turns as _turns
    from simcore.ports.fake import FakeChat, FakeEmbed
    from simcore.world import World, WorldConfig
    from tests.boundary.agent.support import answering

    pack, population = _pack(), _population()
    pins = {"tier_a": "fake/chat", "tier_b": "fake/chat", "embed": "fake-embed"}
    config, _ = _config(pins)
    config = RunConfig.model_validate(
        {**config.model_dump(mode="json"), "brief_hash": canonical_hash(pack.brief),
         "ontology_hash": canonical_hash(pack.ontology),
         "population_hash": population.manifest.population_hash, "graph_hash": population.manifest.graph_hash}
    )
    chat, embed, blocks = FakeChat(responder=answering("answer", "I would try it")), FakeEmbed(), PersonaBlockCache()
    agent_config = AgentConfig(run_seed=4021, horizon_ticks=3, template_id="persona_turn")
    trace = InMemoryTraceSink()

    def world_factory(header):
        return World(header, population=population, config=WorldConfig())

    def agent_fn(jobs, plan=None):
        return _turns(jobs, chat=chat, config=agent_config, ontology=pack.ontology, blocks=blocks, embed=embed)

    result = run(config, pack=pack, population=population, trace=trace, registry=registry,
                 world_factory=world_factory, agent_fn=agent_fn)
    assert result.status.value in ("completed", "partial")
    assert registry.records == 1, f"the run pinned its entry {registry.records} times"
    assert registry.updates >= 1, "the run never moved its entry"
    stored = registry.entry(config.run_id)
    assert stored is not None and stored.status is result.status

    # and a resume moves it again rather than re-pinning it
    resumed = run(config, pack=pack, population=population, trace=trace, registry=registry,
                  world_factory=world_factory, agent_fn=agent_fn)
    assert registry.records == 1
    assert resumed.status.value in ("completed", "partial")
