import pytest
from pydantic import ValidationError

from simcore import schemas
from simcore.schemas import WorldDelta
from tests.study_builders import stimulus_id, turn_payload


def presentation(persona: str = "p-000001", tick: int = 1, channel: str = "social_feed", shown=((1, "interest", 0.8),), n: int = 1) -> dict:
    turn = turn_payload(persona, tick, list(shown), {"subject_stimulus_id": stimulus_id(shown[0][0]), "action": "like"}, n=n)
    turn["impression"]["channel"] = channel
    return {"impression": turn["impression"], "view": turn["view"]}


def stimulus(n: int, tick: int = 1, **overrides) -> dict:
    return {"stimulus_id": stimulus_id(n), "tick": tick, "kind": "concept", "text": f"copy {n}", **overrides}


def dropped(persona: str = "p-000002", n: int = 2, channel: str = "social_feed") -> dict:
    return {"persona_id": persona, "drop": {"kind": "exposure_dropped", "stimulus_id": stimulus_id(n), "channel": channel, "reason": "budget_exhausted"}}


def delta(**overrides) -> dict:
    payload = {
        "tick": 1,
        "published": [stimulus(5)],
        "interventions": ["launch"],
        "dropped": [dropped()],
        "presentations": [presentation(), presentation("p-000002", shown=((1, "wom", 0.4),), n=2)],
    }
    payload.update(overrides)
    return payload


def test_delta_carries_publications_interventions_drops_and_presentations():
    parsed = WorldDelta.model_validate(delta())
    assert [s.stimulus_id for s in parsed.published] == [stimulus_id(5)]
    assert [i.value for i in parsed.interventions] == ["launch"]
    assert parsed.dropped[0].persona_id == "p-000002" and parsed.dropped[0].drop.reason.value == "budget_exhausted"
    assert [p.impression.persona_id for p in parsed.presentations] == ["p-000001", "p-000002"]
    assert WorldDelta.model_validate_json(parsed.model_dump_json()) == parsed


def test_delta_carries_no_event_ids_or_sequence_numbers():
    assert not {"event_id", "seq", "sequence", "world_id"} & set(WorldDelta.model_fields)


@pytest.mark.parametrize(
    "overrides",
    [{"published": [stimulus(5, tick=2)]}, {"presentations": [presentation(tick=2)]}],
    ids=["stimulus-from-another-tick", "presentation-from-another-tick"],
)
def test_every_dated_record_shares_the_deltas_tick(overrides):
    with pytest.raises(ValidationError, match="dated at other ticks"):
        WorldDelta.model_validate(delta(**overrides))


def test_a_presentation_inside_a_delta_must_have_a_matching_view():
    mismatched = presentation()
    mismatched["view"]["contexts"] = {stimulus_id(9): {}}
    with pytest.raises(ValidationError, match="covers exactly the stimuli"):
        WorldDelta.model_validate(delta(presentations=[mismatched]))


def test_a_persona_is_presented_once_per_channel_but_may_appear_on_several():
    with pytest.raises(ValidationError, match="at most once per channel"):
        WorldDelta.model_validate(delta(presentations=[presentation(n=1), presentation(n=2)]))
    two_channels = WorldDelta.model_validate(delta(presentations=[presentation(n=1), presentation(channel="forum", n=2)]))
    assert {p.impression.channel.value for p in two_channels.presentations} == {"social_feed", "forum"}


@pytest.mark.parametrize(
    "overrides",
    [{"published": [stimulus(5), stimulus(5)]}, {"presentations": [presentation(n=1), presentation("p-000002", n=1)]}],
    ids=["stimulus-twice", "impression-twice"],
)
def test_each_record_appears_once(overrides):
    with pytest.raises(ValidationError, match="more than once"):
        WorldDelta.model_validate(delta(**overrides))


def test_a_stimulus_cannot_be_both_dropped_and_shown_to_the_same_persona_on_a_channel():
    with pytest.raises(ValidationError, match="both dropped and shown"):
        WorldDelta.model_validate(delta(dropped=[dropped("p-000001", n=1)]))
    with pytest.raises(ValidationError, match="more than once"):
        WorldDelta.model_validate(delta(dropped=[dropped(), dropped()]))
    elsewhere = WorldDelta.model_validate(delta(dropped=[dropped("p-000001", n=1, channel="forum")]))
    assert elsewhere.dropped[0].drop.channel.value == "forum"


def test_no_world_state_type_exists_and_the_opening_delta_is_tick_zero():
    assert not hasattr(schemas, "WorldState")
    opening = WorldDelta.model_validate(
        {"tick": 0, "published": [stimulus(1, tick=0), stimulus(2, tick=0, kind="claim_post", claim_id="C1")], "presentations": []}
    )
    assert opening.tick == 0 and len(opening.published) == 2
