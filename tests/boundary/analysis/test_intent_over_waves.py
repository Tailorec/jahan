"""M15 phase 6: intent over time — read from survey waves only, per wave and per audience.

Channel turns are behaviour: a purchase on a channel is counted in the action mix and never
scored as intent, even when a turn carries a distribution. Each wave splits its respondents by
whether any channel had reached them by then. Hand-computed mixtures pin every number.
"""

import pytest

from simcore.analysis import digest
from simcore.schemas import Persona, Population, Scenario, TraceEvent, derive_population_hash, derive_world_id
from tests.study_builders import event, population_payload, scenario_payload, ssr_payload, stimulus_id, turn_payload

A = (0.10, 0.10, 0.20, 0.30, 0.30)
B = (0.30, 0.30, 0.20, 0.10, 0.10)
C = (0.20, 0.20, 0.20, 0.20, 0.20)
D = (0.00, 0.10, 0.10, 0.40, 0.40)
TWHIN = "openai/twhin-bert-base"


def mixed_population() -> Population:
    """p-000001/2 are gym regulars, p-000003/4 protein dieters."""
    population = Population.model_validate(population_payload())
    personas = [
        Persona.model_copy(p, update={"conditioning": {"age": "25_34", "sex": "female", "exercise_frequency": "never"}})
        if p.persona_id in ("p-000003", "p-000004") else p
        for p in population.personas
    ]
    population_hash = derive_population_hash(
        population.pack, population.manifest.population_seed, personas, population.graph, population.communities)
    manifest = population.manifest.model_copy(update={"population_hash": population_hash})
    return Population.model_copy(population, update={"personas": tuple(personas), "manifest": manifest})


class View:
    def __init__(self, events):
        self._events = events

    def events(self, _filter):
        return list(self._events)

    def edges(self):
        return []

    def resolve(self, ids):
        known = {event.event_id for event in self._events}
        assert set(ids) <= known


def scored(pmf, model="openai/text-embedding-3-small"):
    return ssr_payload(per_set_pmfs=[pmf] * 6, per_set_similarities=[(0.5,) * 5] * 6, embed_model_id=model)


def world(answers: list[tuple[int, str, tuple, str | None]], channel_turns=(), model="openai/text-embedding-3-small"):
    """A world whose survey answers are `(tick, persona, pmf)` and whose channel turns are
    `(tick, persona, action, pmf-or-None)`, recorded in tick order."""
    population = mixed_population()
    scenario = Scenario.model_validate(scenario_payload(channels=["social_feed"]))
    world_id = derive_world_id(scenario, 4021, population.manifest.population_hash)
    rows = []
    for tick, persona, pmf, *_ in answers:
        rows.append((tick, 1, persona, turn_payload(persona, tick, [(1, "interest", 1.0)], {
            "subject_stimulus_id": stimulus_id(1), "action": "answer", "verbatim": "I might",
            "intent": scored(pmf, model)}, channel="survey_room", n=len(rows))))
    for tick, persona, action, pmf in channel_turns:
        reaction = {"subject_stimulus_id": stimulus_id(1), "action": action}
        if pmf is not None:
            reaction["intent"] = scored(pmf)
        rows.append((tick, 0, persona, turn_payload(persona, tick, [(1, "interest", 1.0)], reaction, n=len(rows))))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    events = [
        TraceEvent.model_validate(event(seq, tick, {"kind": "turn", "turn": turn, "template_id": "persona_turn",
                                                     "prompt_hash": "12" * 32, "persona_block_hash": "34" * 32},
                                        persona, world=world_id))
        for seq, (tick, _, persona, turn) in enumerate(rows)
    ]
    return View(events), scenario, population


def mean(*pmfs):
    return tuple(sum(p[i] for p in pmfs) / len(pmfs) for i in range(5))


def top_two(pmf):
    return pmf[3] + pmf[4]


def test_each_wave_is_the_hand_computed_share_weighted_mixture():
    view, scenario, population = world([
        (0, "p-000001", A), (0, "p-000002", B), (0, "p-000003", C), (0, "p-000004", D),
        (2, "p-000001", D), (2, "p-000002", D), (2, "p-000003", B), (2, "p-000004", B),
    ])
    result = digest(view, scenario=scenario, population=population, seed=4021)
    first, last = result.waves
    assert (first.tick, first.respondents, last.tick, last.respondents) == (0, 4, 2, 4)
    assert first.audience_pmfs["gym_regulars"] == pytest.approx(mean(A, B))
    assert first.audience_pmfs["protein_dieters"] == pytest.approx(mean(C, D))
    assert first.adoption == pytest.approx(0.6 * top_two(mean(A, B)) + 0.4 * top_two(mean(C, D)))
    assert last.adoption == pytest.approx(0.6 * top_two(D) + 0.4 * top_two(B))
    # The headline is where intent stood when the study ended.
    assert result.adoption == pytest.approx(last.adoption)


def test_channel_turns_never_reach_intent_even_when_scored_and_a_purchase_is_behaviour():
    answers = [(0, "p-000001", A), (0, "p-000002", A), (0, "p-000003", A), (0, "p-000004", A)]
    view, scenario, population = world(answers, channel_turns=[(1, "p-000001", "buy", D), (1, "p-000002", "like", None)])
    result = digest(view, scenario=scenario, population=population, seed=4021)
    assert result.adoption == pytest.approx(top_two(A))
    assert result.action_mix["buy"] == 1 and result.action_mix["answer"] == 4
    assert result.turns_without_intent == 0


def test_a_persona_no_channel_reached_by_a_wave_is_counted_unreached_at_that_wave():
    view, scenario, population = world(
        [(0, pid, A) for pid in ("p-000001", "p-000002", "p-000003", "p-000004")]
        + [(2, "p-000001", D), (2, "p-000002", B), (2, "p-000003", B), (2, "p-000004", B)],
        # p-000002 is reached in the wave's own tick: the wave comes last, so it counts.
        channel_turns=[(1, "p-000001", "like", None), (2, "p-000002", "like", None)],
    )
    result = digest(view, scenario=scenario, population=population, seed=4021)
    first, last = result.waves
    assert (first.reached, first.reached_pmf) == (0, None)
    assert first.unreached_pmf == pytest.approx(A)
    assert last.reached == 2
    assert last.reached_adoption == pytest.approx(top_two(mean(D, B)))
    assert last.unreached_adoption == pytest.approx(top_two(B))
    assert dict(result.exposures_by_channel) == {"social_feed": 2}
    assert result.reach_by_tick["social_feed"] == (0, 1, 2)


def test_a_survey_answer_scored_in_the_feeds_ranking_model_is_refused():
    view, scenario, population = world([(0, "p-000001", A, None)], model=TWHIN)
    with pytest.raises(ValueError, match="scored in openai/twhin-bert-base"):
        digest(view, scenario=scenario, population=population, seed=4021,
               pinned_embed_model="openai/text-embedding-3-small")


def test_one_wave_and_no_channels_is_the_concept_tests_headline():
    view, scenario, population = world([(0, "p-000001", A), (0, "p-000002", B), (0, "p-000003", C), (0, "p-000004", D)])
    result = digest(view, scenario=scenario, population=population, seed=4021)
    assert len(result.waves) == 1
    assert result.adoption == pytest.approx(0.6 * top_two(mean(A, B)) + 0.4 * top_two(mean(C, D)))
    assert result.reach_by_tick == {}


def test_the_trajectory_finding_states_the_move_by_audience_and_cites_the_waves_answers():
    from simcore.analysis._findings import _intent_trajectory_findings

    view, scenario, population = world(
        [(0, pid, A) for pid in ("p-000001", "p-000002", "p-000003", "p-000004")]
        + [(1, pid, B) for pid in ("p-000001", "p-000002", "p-000003", "p-000004")]
        + [(2, pid, D) for pid in ("p-000001", "p-000002", "p-000003", "p-000004")],
        channel_turns=[(1, "p-000001", "like", None)],
    )
    result = digest(view, scenario=scenario, population=population, seed=4021)
    (finding,) = _intent_trajectory_findings(view, result, world_id="w1")
    assert f"rose from {top_two(A):.2f} at tick 0 to {top_two(D):.2f} at tick 2 over 3 survey waves" in finding.statement
    assert "gym_regulars" in finding.statement and "protein_dieters" in finding.statement
    assert "the 1 personas a channel reached" in finding.statement
    assert len(finding.evidence_trace_ids) == 8  # the first and last waves' answers, never the middle one


def test_a_single_wave_authors_no_trajectory():
    from simcore.analysis._findings import _intent_trajectory_findings

    view, scenario, population = world([(0, "p-000001", A)])
    result = digest(view, scenario=scenario, population=population, seed=4021)
    assert _intent_trajectory_findings(view, result) == []
