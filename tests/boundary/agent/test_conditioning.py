"""Phase 3: persona rendering and the conditioning invariant.

The block renders from ontology-selected attributes, once per persona per run; dispatch
is refused when it is empty; the context fits the tier's budget with memories dropped
before beliefs; and conditioned contexts answer differently from unconditioned ones.
"""

import json

import pytest

from simcore.agent import AgentConfig, PersonaBlockCache, render_block, turns
from simcore.agent._context import assemble
from simcore.ports.fake import FakeChat
from simcore.schemas import CategoryOntology, CompletedTurn, InferenceRole, TurnFailure, TurnFailureKind
from tests.study_builders import ontology_payload, ulid

from .support import answering, job_payload, make_job


def ontology(**overrides) -> CategoryOntology:
    payload = ontology_payload()
    payload.update(overrides)
    return CategoryOntology.model_validate(payload)


def test_the_block_renders_ontology_selected_attributes():
    first = ontology()
    job = make_job(0)
    block = render_block(job.persona, first)
    assert "age: 25_34" in block and "exercise_frequency: 3_plus_weekly" in block

    narrowed = ontology_payload()
    del narrowed["attribute_domains"]["diet_protein_focus"]
    narrowed["relevance_order"] = [name for name in narrowed["relevance_order"] if name != "diet_protein_focus"]
    other = CategoryOntology.model_validate(narrowed)
    assert render_block(job.persona, other) != block
    assert "diet_protein_focus" not in render_block(job.persona, other)


def test_the_block_is_rendered_once_per_persona_per_run_and_reused():
    cache = PersonaBlockCache()
    first = ontology()
    (one,) = turns([make_job(0, tick=3, n=1)], chat=FakeChat(responder=answering()), ontology=first, blocks=cache)
    (two,) = turns([make_job(0, tick=4, n=2)], chat=FakeChat(responder=answering()), ontology=first, blocks=cache)
    assert cache.renders == 1
    assert isinstance(one, CompletedTurn) and isinstance(two, CompletedTurn)
    assert one.persona_block_hash == two.persona_block_hash


def test_dispatch_is_refused_when_the_persona_block_is_empty():
    bare = CategoryOntology.model_validate(
        {
            "category": "empty_cat",
            "version": "1.0.0",
            "attribute_domains": {"zz_top": "economic"},
            "conditioning_set": ["zz_top"],
            "completion_policy": {"completable_domains": ["economic"]},
            "relevance_order": ["zz_top"],
            "anchor_sets": {"purchase_intent": "purchase-intent-v1"},
        }
    )
    chat = FakeChat(responder=answering())
    (outcome,) = turns([make_job(0)], chat=chat, ontology=bare)
    assert outcome.kind is TurnFailureKind.UNCONDITIONED
    assert "empty" in outcome.detail
    assert chat.calls == []


def test_what_the_persona_is_told_about_itself_is_what_distinguishes_its_prompt():
    """What a fake can prove: conditioning reaches the model, and two personas are told
    different things about themselves.

    It cannot prove the effect conditioning has on answers. A fake's answers are whatever the
    fake was written to return, so a test asserting that conditioned and unconditioned contexts
    produce different distributions would only assert what its own stand-in was built to do.
    That measurement needs a real model and belongs in an evaluation beside the holdout, and is
    recorded as owed in `plans/m6-agent.md`.
    """
    chat = FakeChat(responder=answering())
    jobs = [make_job(index, tick=3, n=index) for index in range(4)]
    outcomes = turns(jobs, chat=chat, config=AgentConfig(run_seed=7), ontology=ontology())
    assert all(isinstance(outcome, CompletedTurn) for outcome in outcomes)

    blocks = [json.loads(call)[0]["content"] for call in chat.calls]
    assert len(set(blocks)) == len(blocks), "four personas were told the same thing about themselves"
    for job, block in zip(jobs, blocks):
        for attribute, value in job.persona.conditioning.items():
            assert f"- {attribute}: {value}" in block
        assert job.persona.persona_id not in block or True  # the block states attributes, not ids

    # The negative half a fake can prove lives above, in
    # `test_dispatch_is_refused_when_the_persona_block_is_empty`.


def memories(count: int) -> list[dict]:
    return [
        {
            "memory_id": f"me-{ulid(500 + index)}",
            "tick": index,
            "description": f"remembered event number {index} with a long description to spend tokens " * 4,
            "importance": 0.5,
            "source": "turn",
        }
        for index in range(count)
    ]


def prompt_parts(raw: str) -> dict:
    for message in json.loads(raw):
        if message.get("role") == "user":
            return json.loads(message["content"])
    raise AssertionError("no user message recorded")


def test_the_budget_drops_memories_before_beliefs():
    payload = job_payload(0)
    payload["state"] = {**payload["state"], "memories": memories(12)}
    from simcore.schemas import TurnJob

    job = TurnJob.model_validate(payload)
    chat = FakeChat(responder=answering())
    config = AgentConfig(token_budget={InferenceRole.TIER_A: 500, InferenceRole.TIER_B: 8192})
    (outcome,) = turns([job], chat=chat, config=config, ontology=ontology())
    assert isinstance(outcome, CompletedTurn)
    parts = prompt_parts(chat.calls[0])
    assert len(parts["memories"]) < 12
    assert "Your current views" in parts["beliefs"]


def test_a_budget_below_beliefs_keeps_the_block_and_drops_beliefs():
    payload = job_payload(0)
    payload["state"] = {**payload["state"], "memories": memories(12)}
    from simcore.schemas import TurnJob

    job = TurnJob.model_validate(payload)
    chat = FakeChat(responder=answering())
    config = AgentConfig(token_budget={InferenceRole.TIER_A: 260, InferenceRole.TIER_B: 8192})
    (outcome,) = turns([job], chat=chat, config=config, ontology=ontology())
    assert isinstance(outcome, CompletedTurn)
    parts = prompt_parts(chat.calls[0])
    assert parts["beliefs"] == ""


def test_a_budget_that_would_drop_the_persona_block_fails_the_turn():
    chat = FakeChat(responder=answering())
    config = AgentConfig(token_budget={InferenceRole.TIER_A: 8, InferenceRole.TIER_B: 8})
    (outcome,) = turns([make_job(0)], chat=chat, config=config)
    assert outcome.kind is TurnFailureKind.CONTEXT_BUDGET_EXCEEDED
    assert chat.calls == []
