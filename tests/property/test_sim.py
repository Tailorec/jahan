import inspect

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from simcore import schemas
from simcore.schemas import (
    MIN_REFERENCE_SETS,
    PMF5,
    ActionKind,
    BeliefChange,
    Beliefs,
    Exposure,
    ExposureReason,
    Impression,
    ImpressionId,
    Presentation,
    MemoryView,
    Reaction,
    SimBaseModel,
    SsrResult,
    Stimulus,
    StimulusContext,
    StimulusId,
    Turn,
    View,
)
from tests.study_builders import beliefs_payload, ssr_payload, stimulus_id, turn_payload, ulid


def exposure(n: int = 1, **overrides):
    return {"stimulus_id": stimulus_id(n), "reason": "interest", "attention": 0.8, **overrides}


def impression(**overrides):
    payload = {"impression_id": f"im-{ulid(7)}", "persona_id": "p-000042", "channel": "social_feed", "tick": 7, "exposures": [exposure()]}
    payload.update(overrides)
    return payload


def stimulus(**overrides):
    payload = {"stimulus_id": stimulus_id(1), "tick": 3, "kind": "concept", "text": "Clear protein water"}
    payload.update(overrides)
    return payload


# --- response masses --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [(-0.1, 0.3, 0.3, 0.3, 0.2), (0.1, 0.2, 0.2, 0.3, 0.19), (float("nan"), 0.2, 0.2, 0.3, 0.3), (float("inf"), 0.2, 0.2, 0.3, 0.3)])
def test_pmf_refuses_negative_non_finite_and_sums_outside_tolerance(bad):
    with pytest.raises(ValidationError):
        TypeAdapter(PMF5).validate_python(bad)


def test_pmf_accepts_a_mass_the_published_formula_gives_exactly_zero():
    """The published SSR formula subtracts the least similar anchor's similarity, so with the paper's
    epsilon of zero that anchor receives exactly zero within each set, and a community whose members all
    place the same anchor last averages to zero there too (ADR 0026). A digest that refused such a mass
    crashed a whole study's report after its worlds had finished."""
    assert TypeAdapter(PMF5).validate_python((0.0, 0.2, 0.3, 0.3, 0.2)) == (0.0, 0.2, 0.3, 0.3, 0.2)


def test_pmf_accepts_a_strictly_positive_mass_and_refuses_wrong_arity():
    assert TypeAdapter(PMF5).validate_python((0.1, 0.2, 0.2, 0.3, 0.2)) == (0.1, 0.2, 0.2, 0.3, 0.2)
    with pytest.raises(ValidationError):
        TypeAdapter(PMF5).validate_python((0.5, 0.5))


# --- exposures and impressions ----------------------------------------------------------------


def test_exposure_reason_is_a_closed_set():
    assert {r.value for r in ExposureReason} == {"interest", "social_proof", "random", "wom", "forum", "launch"}
    with pytest.raises(ValidationError):
        Exposure.model_validate(exposure(reason="intrest"))


@pytest.mark.parametrize(("attention", "seen"), [(0.8, True), (0.01, True), (0.0, False)])
def test_seen_is_computed_from_attention(attention, seen):
    parsed = Exposure.model_validate(exposure(attention=attention))
    assert parsed.seen is seen
    assert Exposure.model_validate(parsed.model_dump(mode="json")) == parsed


def test_supplied_seen_contradicting_attention_refused():
    with pytest.raises(ValidationError, match="computed"):
        Exposure.model_validate(exposure(attention=1.0, seen=False))


def test_impression_holds_at_least_one_exposure():
    with pytest.raises(ValidationError):
        Impression.model_validate(impression(exposures=[]))


def test_survey_room_impression_holds_exactly_one_exposure_of_the_same_type():
    survey = Impression.model_validate(impression(channel="survey_room"))
    feed = Impression.model_validate(impression(exposures=[exposure(1), exposure(2)]))
    assert type(survey) is type(feed) is Impression
    with pytest.raises(ValidationError, match="exactly one"):
        Impression.model_validate(impression(channel="survey_room", exposures=[exposure(1), exposure(2)]))


def test_feed_exposure_budget_belongs_to_the_scenario_not_the_impression_type():
    wide = Impression.model_validate(impression(exposures=[exposure(n) for n in range(1, 6)]))
    assert len(wide.exposures) == 5


def test_the_same_stimulus_cannot_be_shown_twice_in_one_impression():
    with pytest.raises(ValidationError, match="more than once"):
        Impression.model_validate(impression(exposures=[exposure(1), exposure(1, attention=0.2)]))


def test_exposures_retain_attention_reason_and_seen_flag_when_grouped():
    first, second = Impression.model_validate(
        impression(exposures=[exposure(1, reason="interest", attention=0.9), exposure(2, reason="random", attention=0.0)])
    ).exposures
    assert (first.reason, first.attention, first.seen) == (ExposureReason.INTEREST, 0.9, True)
    assert (second.reason, second.attention, second.seen) == (ExposureReason.RANDOM, 0.0, False)


# --- stimuli ----------------------------------------------------------------------------------


def test_persona_and_study_stimuli_are_one_type_told_apart_by_author():
    peer = Stimulus.model_validate(stimulus(kind="peer_post", author="p-000042", text="tried it after the gym"))
    study = Stimulus.model_validate(stimulus(kind="claim_post", claim_id="C1", text="20g protein, zero sugar"))
    assert peer.author is not None and study.author is None
    assert type(peer) is type(study) is Stimulus


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"kind": "peer_post"}, "must name its author"),
        ({"kind": "wom_message"}, "must name its author"),
        ({"kind": "concept", "author": "p-000042"}, "carries no persona author"),
        ({"kind": "claim_post"}, "name the claim"),
        ({"kind": "peer_reply", "author": "p-000042"}, "replies to"),
        ({"kind": "peer_post", "author": "p-000042", "in_reply_to": stimulus_id(9)}, "replies to"),
        ({"kind": "peer_reply", "author": "p-000042", "in_reply_to": stimulus_id(1)}, "itself"),
    ],
    ids=["peer-post-unauthored", "wom-unauthored", "concept-authored", "claim-post-without-claim",
         "reply-without-parent", "post-with-parent", "self-reply"],
)
def test_stimulus_kind_decides_authorship_and_references(overrides, match):
    with pytest.raises(ValidationError, match=match):
        Stimulus.model_validate(stimulus(**overrides))


def test_identifier_formats():
    assert TypeAdapter(ImpressionId).validate_python(f"im-{ulid(1)}")
    assert TypeAdapter(StimulusId).validate_python(stimulus_id(1))
    lettered = ulid(10**9)
    assert lettered != lettered.upper()
    for bad in (f"rc-{lettered}", f"im-{lettered.upper()}", lettered):
        with pytest.raises(ValidationError):
            TypeAdapter(ImpressionId).validate_python(bad)


def test_action_kind_is_a_closed_set_covering_every_channel_and_not_reacting():
    assert {member.value for member in ActionKind} == {
        "answer", "post", "comment", "like", "repost", "quote", "follow", "buy", "ask_peer", "reject", "complain",
        "reply", "upvote", "downvote", "ignore",
    }


# --- beliefs and memory -----------------------------------------------------------------------


def test_beliefs_cover_every_dimension_and_carry_no_claim_list_of_their_own():
    beliefs = Beliefs.model_validate(beliefs_payload())
    assert set(beliefs.claim_credence) == {"C1", "C2", "C3"}
    assert "claim_ids" not in Beliefs.model_fields and "claim_ids" not in BeliefChange.model_fields
    with pytest.raises(ValidationError, match="missing"):
        Beliefs.model_validate(beliefs_payload(dimensions={"value": 0.6, "fit": 0.4}))
    with pytest.raises(ValidationError, match="at least one"):
        Beliefs.model_validate(beliefs_payload(claim_credence={}))


def test_belief_levels_bounded_and_changes_signed():
    with pytest.raises(ValidationError):
        Beliefs.model_validate(beliefs_payload(dimensions={"value": 1.2, "fit": 0.4, "trust": 0.7}))
    change = BeliefChange.model_validate({"dimensions": {"value": -0.2}, "claim_credence": {"C1": -1.0}})
    assert change.claim_credence["C1"] == -1.0
    with pytest.raises(ValidationError):
        BeliefChange.model_validate({"claim_credence": {"C1": -1.5}})
    assert BeliefChange() == BeliefChange.model_validate({})


def test_memory_view_holds_distinct_memories_or_none():
    memory = {"memory_id": "m-1", "tick": 2, "description": "saw the launch post", "importance": 0.6, "relevance": 0.8}
    assert MemoryView.model_validate({"items": []}).items == ()
    assert len(MemoryView.model_validate({"items": [memory]}).items) == 1
    with pytest.raises(ValidationError, match="more than once"):
        MemoryView.model_validate({"items": [memory, memory]})


# --- elicitation ------------------------------------------------------------------------------


def test_headline_mass_is_computed_as_the_mean_of_the_reference_sets():
    result = SsrResult.model_validate(ssr_payload())
    sets = ssr_payload()["per_set_pmfs"]
    assert result.pmf == pytest.approx(tuple(sum(s[i] for s in sets) / len(sets) for i in range(5)))
    assert "pmf" not in SsrResult.model_fields


def test_supplied_headline_mass_contradicting_its_reference_sets_refused():
    with pytest.raises(ValidationError, match="computed"):
        SsrResult.model_validate({**ssr_payload(), "pmf": (0.05, 0.05, 0.1, 0.3, 0.5)})


def test_elicitation_needs_the_minimum_number_of_reference_sets():
    assert MIN_REFERENCE_SETS == 6
    with pytest.raises(ValidationError):
        SsrResult.model_validate(ssr_payload(per_set_pmfs=ssr_payload()["per_set_pmfs"][:5]))


def test_elicitation_result_carries_the_embedding_model_and_anchor_set():
    result = SsrResult.model_validate(ssr_payload())
    assert (result.embed_model_id, result.anchor_set_id, result.anchor_version) == ("openai/text-embedding-3-small", "purchase-intent-v1", "1.0.0")
    with pytest.raises(ValidationError):
        SsrResult.model_validate(ssr_payload(embed_model_id="openai/text-embedding-latest"))


def test_elicitation_round_trips_with_its_computed_mass():
    result = SsrResult.model_validate(ssr_payload())
    assert SsrResult.model_validate_json(result.model_dump_json()) == result


# --- reactions and turns ----------------------------------------------------------------------


def reaction(**overrides):
    payload = {"reaction_id": f"rc-{ulid(3)}", "subject_stimulus_id": stimulus_id(1), "action": "comment", "verbatim": "the protein claim lands"}
    payload.update(overrides)
    return payload


def test_reaction_belongs_to_its_turn_and_names_only_its_subject():
    assert not {"persona_id", "tick", "impression_id"} & set(Reaction.model_fields)
    assert Reaction.model_validate(reaction()).subject_stimulus_id == stimulus_id(1)


@pytest.mark.parametrize("action", ["answer", "post", "comment", "reply", "quote", "complain", "ask_peer"])
def test_text_producing_actions_need_a_verbatim(action):
    with pytest.raises(ValidationError, match="needs a verbatim"):
        Reaction.model_validate(reaction(action=action, verbatim=None))


def test_ignoring_produces_neither_verbatim_nor_elicitation():
    assert Reaction.model_validate(reaction(action="ignore", verbatim=None)).verbatim is None
    assert Reaction.model_validate(reaction(action="like", verbatim=None)).action is ActionKind.LIKE
    with pytest.raises(ValidationError, match="neither"):
        Reaction.model_validate(reaction(action="ignore", verbatim="meh"))
    with pytest.raises(ValidationError, match="neither"):
        Reaction.model_validate(reaction(action="ignore", verbatim=None, intent=ssr_payload()))


def test_turn_joins_an_impression_with_the_reaction_to_it():
    turn = Turn.model_validate(turn_payload("p-000042", 7, [(1, "interest", 0.8), (2, "random", 0.0)], reaction()))
    assert turn.reaction.subject_stimulus_id in turn.impression.stimulus_ids
    assert Turn.model_validate_json(turn.model_dump_json()) == turn


def test_turn_refuses_a_reaction_about_a_stimulus_not_shown():
    with pytest.raises(ValidationError, match="did not show"):
        Turn.model_validate(turn_payload("p-000042", 7, [(1, "interest", 0.8)], reaction(subject_stimulus_id=stimulus_id(4))))


def test_turn_refuses_engaging_with_a_stimulus_not_noticed_but_allows_ignoring_it():
    shown = [(1, "interest", 0.0), (2, "random", 0.5)]
    with pytest.raises(ValidationError, match="did not notice"):
        Turn.model_validate(turn_payload("p-000042", 7, shown, reaction()))
    ignored = Turn.model_validate(turn_payload("p-000042", 7, shown, reaction(action="ignore", verbatim=None)))
    assert ignored.reaction.action is ActionKind.IGNORE


def test_no_schema_type_accepts_a_model_emitted_numeric_rating():
    models = [obj for _, obj in inspect.getmembers(schemas, inspect.isclass) if issubclass(obj, SimBaseModel) and obj is not SimBaseModel]
    assert models
    for model in models:
        for name in model.model_fields:
            assert not any(word in name for word in ("rating", "score", "likert")), f"{model.__name__}.{name} looks like a numeric rating"
    assert "pmf" not in SsrResult.model_fields


@given(value=st.floats(0.0, 1.0), fit=st.floats(0.0, 1.0), trust=st.floats(0.0, 1.0), credence=st.floats(0.0, 1.0))
def test_beliefs_round_trip_over_generated_values(value, fit, trust, credence):
    beliefs = Beliefs.model_validate(beliefs_payload(dimensions={"value": value, "fit": fit, "trust": trust}, claim_credence={"C1": credence}))
    assert Beliefs.model_validate_json(beliefs.model_dump_json()) == beliefs


# --- views ------------------------------------------------------------------------------------


def test_view_covers_exactly_the_stimuli_of_its_impression_and_names_it():
    shown = [(1, "interest", 0.8), (2, "random", 0.2)]
    turn = Turn.model_validate(turn_payload("p-000042", 7, shown, reaction()))
    assert set(turn.view.contexts) == turn.impression.stimulus_ids
    assert turn.view.impression_id == turn.impression.impression_id
    missing = turn_payload("p-000042", 7, shown, reaction())
    missing["view"]["contexts"] = {stimulus_id(1): missing["view"]["contexts"][stimulus_id(1)]}
    with pytest.raises(ValidationError, match="uncovered"):
        Turn.model_validate(missing)
    extra = turn_payload("p-000042", 7, shown, reaction())
    extra["view"]["contexts"][stimulus_id(9)] = {}
    with pytest.raises(ValidationError, match="extra"):
        Turn.model_validate(extra)
    renamed = turn_payload("p-000042", 7, shown, reaction())
    renamed["view"]["impression_id"] = f"im-{ulid(999)}"
    with pytest.raises(ValidationError, match="view names impression"):
        Turn.model_validate(renamed)


def test_view_carries_nothing_private_and_nothing_aggregate():
    assert set(View.model_fields) == {"impression_id", "contexts"}
    # `via_persona_id` is who passed a stimulus on. It is public to the persona being told —
    # you know who told you, and the tie strength beside it is already the tie to them — and it
    # is what lets a word-of-mouth path be read back out of the record.
    assert set(StimulusContext.model_fields) == {
        "likes", "reposts", "replies", "upvotes", "downvotes", "ancestry", "tie_strength",
        "shared_community", "via_persona_id",
    }


def test_author_relationship_may_be_absent_and_tie_strength_is_bounded():
    study_authored = StimulusContext()
    assert (study_authored.tie_strength, study_authored.shared_community) == (None, None)
    assert StimulusContext(tie_strength=0.0, shared_community=False).tie_strength == 0.0
    with pytest.raises(ValidationError):
        StimulusContext(tie_strength=1.5)
    with pytest.raises(ValidationError):
        StimulusContext(shared_community="community-1")


def test_counts_are_non_negative_and_ancestry_cannot_loop():
    with pytest.raises(ValidationError):
        StimulusContext(likes=-1)
    with pytest.raises(ValidationError, match="twice"):
        StimulusContext(ancestry=[stimulus_id(1), stimulus_id(2), stimulus_id(1)])


def test_view_must_cover_at_least_one_stimulus():
    with pytest.raises(ValidationError, match="at least one"):
        View(impression_id=f"im-{ulid(1)}", contexts={})


def test_presentation_pairs_an_impression_with_the_view_that_covers_it():
    shown = [(1, "interest", 0.8), (2, "random", 0.2)]
    turn = turn_payload("p-000042", 7, shown, reaction())
    presentation = Presentation.model_validate({"impression": turn["impression"], "view": turn["view"]})
    assert set(presentation.view.contexts) == presentation.impression.stimulus_ids
    assert Presentation.model_validate_json(presentation.model_dump_json()) == presentation
    uncovered = {"impression": turn["impression"], "view": {**turn["view"], "contexts": {stimulus_id(1): {}}}}
    with pytest.raises(ValidationError, match="uncovered"):
        Presentation.model_validate(uncovered)
    renamed = {"impression": turn["impression"], "view": {**turn["view"], "impression_id": f"im-{ulid(999)}"}}
    with pytest.raises(ValidationError, match="view names impression"):
        Presentation.model_validate(renamed)
