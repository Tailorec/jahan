import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    ActionKind,
    Channel,
    PMF5,
    Stimulus,
    Exposure,
    Impression,
    ImpressionId,
    StimulusKind,
    StimulusId,
)

VALID_ULID = "01j7x9k2m3n4p5q6r7s8t9v0wx"


def exposure(**overrides):
    payload = {
        "stimulus_id": f"st-{VALID_ULID}",
        "reason": "recsys_rank_2",
        "attention": 0.8,
        "seen": True,
    }
    payload.update(overrides)
    return payload


def impression(**overrides):
    payload = {
        "impression_id": f"im-{VALID_ULID}",
        "persona_id": "p-000042",
        "channel": "social_feed",
        "tick": 7,
        "exposures": [exposure()],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("bad", [(0.0, 0.2, 0.2, 0.3, 0.3), (0.1, 0.2, 0.2, 0.3, 0.19)])
def test_pmf_refuses_zero_and_sums_outside_tolerance(bad):
    with pytest.raises(ValidationError, match="softmax|sum to one"):
        TypeAdapter(PMF5).validate_python(bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pmf_refuses_non_finite_values(bad):
    with pytest.raises(ValidationError):
        TypeAdapter(PMF5).validate_python((bad, 0.2, 0.2, 0.3, 0.3))


def test_pmf_accepts_a_strictly_positive_mass_and_refuses_wrong_arity():
    assert TypeAdapter(PMF5).validate_python((0.1, 0.2, 0.2, 0.3, 0.2)) == (0.1, 0.2, 0.2, 0.3, 0.2)
    with pytest.raises(ValidationError):
        TypeAdapter(PMF5).validate_python((0.5, 0.5))


def test_impression_holds_one_to_its_channels_budget_of_exposures():
    assert Impression.model_validate(impression()).exposures
    with pytest.raises(ValidationError, match="one to 3"):
        Impression.model_validate(impression(exposures=[]))
    with pytest.raises(ValidationError, match="one to 3"):
        Impression.model_validate(impression(exposures=[exposure() for _ in range(4)]))


def test_survey_room_impression_holds_exactly_one_exposure():
    survey = Impression.model_validate(impression(channel="survey_room"))
    assert len(survey.exposures) == 1
    assert isinstance(survey, Impression)
    feed = Impression.model_validate(impression(channel="social_feed", exposures=[exposure(), exposure()]))
    assert len(feed.exposures) == 2
    with pytest.raises(ValidationError, match="one to 1"):
        Impression.model_validate(impression(channel="survey_room", exposures=[exposure(), exposure()]))


def test_exposures_retain_attention_reason_and_seen_flag_when_grouped():
    grouped = Impression.model_validate(
        impression(
            exposures=[
                exposure(stimulus_id=f"st-{VALID_ULID}", attention=0.9, reason="rank_1", seen=True),
                exposure(stimulus_id="st-" + VALID_ULID[:-1] + "y", attention=0.1, reason="rank_4", seen=False),
            ]
        )
    )
    first, second = grouped.exposures
    assert (first.attention, first.reason, first.seen) == (0.9, "rank_1", True)
    assert (second.attention, second.reason, second.seen) == (0.1, "rank_4", False)


def test_stimulus_author_presence_distinguishes_persona_from_study_authorship():
    peer = Stimulus.model_validate(
        {
            "stimulus_id": f"st-{VALID_ULID}",
            "tick": 3,
            "author": "p-000042",
            "kind": "peer_post",
            "text": "tried it after the gym",
        }
    )
    study = Stimulus.model_validate(
        {
            "stimulus_id": "st-" + VALID_ULID[:-1] + "z",
            "tick": 3,
            "kind": "claim_post",
            "text": "20g protein, zero sugar",
            "claim_id": "C1",
        }
    )
    assert peer.author is not None and study.author is None
    assert type(peer) is type(study) is Stimulus


def test_impression_id_and_stimulus_id_formats():
    assert TypeAdapter(ImpressionId).validate_python(f"im-{VALID_ULID}")
    assert TypeAdapter(StimulusId).validate_python(f"st-{VALID_ULID}")
    for bad in (f"rc-{VALID_ULID}", f"im-{VALID_ULID.upper()}", VALID_ULID):
        with pytest.raises(ValidationError):
            TypeAdapter(ImpressionId).validate_python(bad)


def test_action_kind_is_a_closed_set():
    assert {member.value for member in ActionKind} == {
        "answer", "post", "comment", "like", "repost", "quote",
        "follow", "buy", "ask_peer", "reject", "complain",
    }
