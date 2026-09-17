"""Phase 7: tier routing and purchase intent.

Tier routing follows a configuration table, never code. A purchase-intent turn is scored
through `elicitation` when a passing anchor version is pinned; when none is, the
verbatim is kept and the recorded elicitation failure stands in place of the
distribution — and no code path asks a model for a number.
"""

import ast
import re
from pathlib import Path

import pytest

from simcore.agent import AgentConfig, DEFAULT_TIER_ROUTING, turns
from simcore.elicitation import clear_anchor_cache
from simcore.ports.fake import FakeChat, FakeEmbed
from simcore.schemas import (
    CompletedTurn,
    ElicitationFailure,
    ElicitationFailureKind,
    InferenceRole,
    Reaction,
    SsrResult,
    TurnTask,
)
from tests.boundary.elicitation.staging import FAKE_MODEL, pinned, stage_passing
from tests.study_builders import stimulus_id

from .support import BatchCountingChat, answering, by_template, make_job


def purchase_job(**overrides) -> dict:
    from .support import job_payload

    payload = job_payload(0, shown=[(1, "interest", 0.9)])
    payload["task"] = "purchase"
    payload.update(overrides)
    return payload


def purchase_config(tmp_path, **overrides) -> AgentConfig:
    staged = stage_passing(tmp_path)
    return AgentConfig(
        category="beverage_protein",
        anchors_dir=str(staged),
        anchor_set_ids={"purchase_intent": "purchase-intent-v1"},
        anchor_versions={"purchase_intent": "v1"},
        anchor_hashes=pinned(staged),
        **overrides,
    )


def test_an_unscorable_reaction_keeps_its_verbatim_beside_the_failure():
    """The contract defect, failing first: a reaction must carry the elicitation failure."""
    failure = ElicitationFailure.model_validate(
        {
            "kind": "unpinned_anchors",
            "detail": "no anchor version is pinned for purchase_intent",
            "response_text": "I would try it after training",
            "construct_id": "purchase_intent",
        }
    )
    reaction = Reaction.model_validate(
        {
            "reaction_id": "rc-00000000000000000000000000",
            "subject_stimulus_id": stimulus_id(1),
            "action": "answer",
            "verbatim": "I would try it after training",
            "elicitation_failure": failure.model_dump(),
        }
    )
    assert reaction.intent is None
    assert reaction.elicitation_failure is not None
    assert reaction.elicitation_failure.kind is ElicitationFailureKind.UNPINNED_ANCHORS


def test_tier_routing_matches_the_configuration_table_for_every_task():
    assert set(DEFAULT_TIER_ROUTING) == set(TurnTask)
    assert DEFAULT_TIER_ROUTING[TurnTask.PURCHASE] is InferenceRole.TIER_B
    assert DEFAULT_TIER_ROUTING[TurnTask.REACTION] is InferenceRole.TIER_A

    for task in TurnTask:
        from simcore.schemas import TurnJob

        payload = purchase_job()
        payload["task"] = task.value
        job = TurnJob.model_validate(payload)
        chat = BatchCountingChat(responder=answering())
        turns([job], chat=chat, config=AgentConfig())
        assert chat.roles[0] == [DEFAULT_TIER_ROUTING[task].value]


def test_the_routing_table_is_data_a_study_can_change():
    from simcore.schemas import TurnJob

    config = AgentConfig(tier_routing={**DEFAULT_TIER_ROUTING, TurnTask.REACTION: InferenceRole.TIER_B})
    job = TurnJob.model_validate(purchase_job(task="reaction"))
    chat = BatchCountingChat(responder=answering())
    (outcome,) = turns([job], chat=chat, config=config)
    assert isinstance(outcome, CompletedTurn)


def test_a_purchase_turn_with_a_pinned_version_records_a_distribution(tmp_path):
    clear_anchor_cache()
    from simcore.schemas import TurnJob

    config = purchase_config(tmp_path)
    job = TurnJob.model_validate(purchase_job())
    embed = FakeEmbed(dim=8, model_id=FAKE_MODEL)
    (outcome,) = turns(
        [job], chat=FakeChat(responder=answering(verbatim="I would try it after training")), config=config, embed=embed
    )
    assert isinstance(outcome, CompletedTurn)
    assert isinstance(outcome.turn.reaction.intent, SsrResult)
    assert outcome.turn.reaction.elicitation_failure is None
    assert outcome.turn.reaction.verbatim == "I would try it after training"


def test_a_purchase_turn_with_no_pinned_version_records_verbatim_and_failure(tmp_path):
    from simcore.schemas import TurnJob

    config = AgentConfig(category="beverage_protein", anchors_dir=str(tmp_path))
    job = TurnJob.model_validate(purchase_job())
    (outcome,) = turns(
        [job], chat=FakeChat(responder=answering(verbatim="I would try it after training")), config=config,
        embed=FakeEmbed(dim=8, model_id=FAKE_MODEL),
    )
    assert isinstance(outcome, CompletedTurn)
    assert outcome.turn.reaction.intent is None
    assert outcome.turn.reaction.verbatim == "I would try it after training"
    assert outcome.turn.reaction.elicitation_failure is not None
    assert outcome.turn.reaction.elicitation_failure.kind is ElicitationFailureKind.UNPINNED_ANCHORS


def test_no_code_path_asks_a_model_for_a_rating():
    """Every prompt constant the module sends is scanned: none requests a number."""
    prompt_files = ["_prompt.py", "_turns.py", "_guard.py", "_probe.py", "_reflect.py"]
    package = Path("simcore/agent")
    rating_request = re.compile(
        r"(?i)\b(rating|ratings|rate it|rate the|likert|stars?|five-point|five point|1\s*-\s*5|out of (5|10)|/5\b)"
    )
    hits = []
    for name in prompt_files:
        path = package / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 20:
                if rating_request.search(node.value):
                    hits.append((name, node.value[:80]))
    assert hits == []


def test_tier_b_importance_rides_inside_the_call_already_being_made():
    from simcore.schemas import TurnJob

    def rated(messages, template_id: str) -> str:
        import json

        from .support import impression_of

        shown = impression_of(messages)["exposures"]
        return json.dumps(
            {"subject_stimulus_id": shown[0]["stimulus_id"], "action": "comment", "verbatim": "noted", "importance": 0.9}
        )

    config = AgentConfig(tier_routing={**DEFAULT_TIER_ROUTING, TurnTask.REACTION: InferenceRole.TIER_B})
    job = TurnJob.model_validate(purchase_job(task="reaction"))
    chat = BatchCountingChat(responder=rated)
    (outcome,) = turns([job], chat=chat, config=config, embed=FakeEmbed(dim=4))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.memories[0].importance == 0.9
    assert len(chat.batches) == 1


def test_tier_a_turns_in_one_tick_coalesce_into_one_batch():
    jobs = [make_job(index % 4, n=index) for index in range(5)]
    chat = BatchCountingChat(responder=answering())
    outcomes = turns(jobs, chat=chat)
    assert len(outcomes) == 5
    assert len(chat.batches) == 1 and len(chat.batches[0]) == 5


def test_anchors_that_failed_their_check_are_recorded_as_such_not_as_an_embedding_failure(tmp_path):
    """The gate refuses a version whose check failed; recording that as an embedding failure
    would blame the model for a decision about the anchors (ADR 0032)."""
    from simcore.agent import _intent
    from simcore.schemas import ElicitationFailureKind

    def refuses(*args, **kwargs):
        raise ValueError("satisfaction/v1 failed its check (rank stability 0.500): it cannot be pinned")

    original = _intent.elicitation_score
    _intent.elicitation_score = refuses
    try:
        outcomes = _intent.score_intents({0: "I would try it"}, purchase_config(tmp_path), None)
    finally:
        _intent.elicitation_score = original
    assert outcomes[0].kind is ElicitationFailureKind.UNPINNED_ANCHORS
    assert "failed its check" in outcomes[0].detail
    assert outcomes[0].response_text == "I would try it"
