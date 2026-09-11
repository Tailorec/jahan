import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simcore.schemas import (
    ActionKind,
    BeliefChange,
    BeliefDim,
    Beliefs,
    Channel,
    MemoryView,
    PMF5,
    ProductBrief,
    Reaction,
    RetrievedMemory,
    SsrResult,
    Stimulus,
    Exposure,
    Impression,
    ImpressionId,
    StimulusKind,
    StimulusId,
)
from tests.study_builders import load_fixture

VALID_ULID = "01j7x9k2m3n4p5q6r7s8t9v0wx"
BRIEF_CLAIMS = frozenset(claim.id for claim in ProductBrief.model_validate(load_fixture("example_brief.json")).claims)


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


# --- reactions, beliefs, memory, elicitation --------------------------------------------------


def beliefs_payload(**overrides):
    payload = {
        "claim_ids": list(BRIEF_CLAIMS),
        "dimensions": {"value": 0.6, "fit": 0.4, "trust": 0.7},
        "claim_credence": {"C1": 0.8, "C2": 0.3, "C3": 0.5},
    }
    payload.update(overrides)
    return payload


def change_payload(**overrides):
    payload = {
        "claim_ids": list(BRIEF_CLAIMS),
        "dimensions": {"value": -0.2},
        "claim_credence": {"C1": 0.3},
    }
    payload.update(overrides)
    return payload


def ssr_payload(**overrides):
    payload = {
        "response_text": "I would probably try it after training.",
        "pmf": (0.05, 0.1, 0.2, 0.3, 0.35),
        "per_set_pmfs": [(0.05, 0.1, 0.2, 0.3, 0.35), (0.06, 0.1, 0.19, 0.3, 0.35)],
        "construct_id": "purchase_intent",
        "category": "beverage_protein",
        "anchor_set_id": "pi-oralcare-v3",
        "anchor_version": "3.0.0",
        "embed_model_id": "openai/text-embedding-3-small",
        "tau": 0.42,
    }
    payload.update(overrides)
    return payload


def reaction_payload(**overrides):
    payload = {
        "reaction_id": f"rc-{VALID_ULID}",
        "persona_id": "p-000042",
        "impression_id": f"im-{VALID_ULID}",
        "subject_stimulus_id": f"st-{VALID_ULID}",
        "tick": 7,
        "action": "comment",
        "verbatim": "the protein claim is the one that would get me",
        "belief_change": change_payload(),
        "intent": ssr_payload(),
    }
    payload.update(overrides)
    return payload


def test_reaction_references_the_impression_and_separately_the_subject_stimulus():
    reaction = Reaction.model_validate(reaction_payload())
    assert reaction.impression_id.startswith("im-")
    assert reaction.subject_stimulus_id.startswith("st-")
    assert {"impression_id", "subject_stimulus_id"} <= set(Reaction.model_fields)


def test_belief_levels_bounded_and_deltas_signed():
    assert Beliefs.model_validate(beliefs_payload()).dimensions["value"] == 0.6
    with pytest.raises(ValidationError):
        Beliefs.model_validate(beliefs_payload(dimensions={"value": 1.5, "fit": 0.4, "trust": 0.7}))
    change = BeliefChange.model_validate(change_payload())
    assert change.dimensions["value"] == -0.2
    with pytest.raises(ValidationError):
        BeliefChange.model_validate(change_payload(dimensions={"value": -1.2}))
    with pytest.raises(ValidationError):
        BeliefChange.model_validate(change_payload(dimensions={"value": 0.0}, claim_credence={"C1": -1.5}))


def test_credence_keys_must_match_the_tracked_claims_exactly():
    with pytest.raises(ValidationError, match="exactly"):
        Beliefs.model_validate(beliefs_payload(claim_credence={"C1": 0.8, "C2": 0.3}))


def test_credence_keys_are_checked_against_the_tracked_claim_vocabulary():
    beliefs = Beliefs.model_validate(beliefs_payload())
    assert beliefs.claim_ids == BRIEF_CLAIMS
    assert set(beliefs.claim_credence) == BRIEF_CLAIMS
    foreign = Beliefs.model_validate(
        beliefs_payload(claim_ids=["C9"], claim_credence={"C9": 1.0})
    )
    assert foreign.claim_ids != BRIEF_CLAIMS


def test_belief_dimensions_are_the_closed_set():
    with pytest.raises(ValidationError, match="closed dimension set|missing"):
        Beliefs.model_validate(beliefs_payload(dimensions={"value": 0.5, "fit": 0.5}))


def test_belief_change_stays_within_tracked_claims():
    with pytest.raises(ValidationError, match="untracked"):
        BeliefChange.model_validate(change_payload(claim_credence={"C9": 0.4}))


def test_memory_view_carries_retrieved_items_or_none():
    empty = MemoryView.model_validate({"items": []})
    assert empty.items == ()
    view = MemoryView.model_validate(
        {
            "items": [
                {
                    "memory_id": "mem-001",
                    "tick": 2,
                    "description": "saw the launch post",
                    "importance": 0.7,
                    "relevance": 0.9,
                }
            ]
        }
    )
    item = view.items[0]
    assert isinstance(item, RetrievedMemory) and item.relevance == 0.9


def test_elicitation_result_carries_the_embedding_model():
    result = SsrResult.model_validate(ssr_payload())
    assert result.embed_model_id == "openai/text-embedding-3-small"
    mismatched = SsrResult.model_validate({**ssr_payload(), "embed_model_id": "openai/text-embedding-ada-002"})
    assert mismatched.embed_model_id != result.embed_model_id


def test_no_schema_type_accepts_a_model_emitted_numeric_rating():
    from simcore import schemas

    for name in schemas.__all__:
        model = getattr(schemas, name)
        if isinstance(model, type) and issubclass(model, schemas.SimBaseModel):
            assert "rating" not in model.model_fields, f"{name} accepts a rating"
            assert "numeric_rating" not in model.model_fields, f"{name} accepts a numeric rating"


def test_reaction_and_beliefs_round_trip_through_json():
    reaction = Reaction.model_validate(reaction_payload())
    assert Reaction.model_validate(reaction.model_dump(mode="json")) == reaction
    beliefs = Beliefs.model_validate(beliefs_payload())
    assert Beliefs.model_validate(beliefs.model_dump(mode="json")) == beliefs


unit = st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False)
signed = st.floats(-1.0, 1.0, allow_nan=False, allow_infinity=False)


@given(value=unit, fit=unit, trust=unit, credence=st.lists(unit, min_size=3, max_size=3))
def test_beliefs_round_trip_over_generated_values(value, fit, trust, credence):
    payload = beliefs_payload(
        dimensions={"value": value, "fit": fit, "trust": trust},
        claim_credence=dict(zip(sorted(BRIEF_CLAIMS), credence)),
    )
    beliefs = Beliefs.model_validate(payload)
    assert Beliefs.model_validate(beliefs.model_dump(mode="json")) == beliefs
