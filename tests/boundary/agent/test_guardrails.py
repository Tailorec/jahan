"""Phase 6: guardrails and parsing.

A response naming what it was never shown — or no parseable answer at all — is rejected,
retried once with a stricter instruction, and then recorded as a violation in place of a
reaction. Two rules, and only two, guard the module.
"""

import re
from pathlib import Path

from simcore.agent import GUARDRAILS, turns
from simcore.schemas import CompletedTurn, GuardrailRule, TurnFailure, TurnFailureKind
from tests.study_builders import stimulus_id, ulid

from .support import BatchCountingChat, answering, by_template, inventing, make_job


def unshown() -> str:
    return f"st-{ulid(999)}"


def test_an_unshown_stimulus_triggers_the_guardrail_path_exactly_once():
    target = unshown()
    chat = BatchCountingChat(responder=inventing(target))
    (outcome,) = turns([make_job(0)], chat=chat)
    assert isinstance(outcome, TurnFailure)
    assert outcome.kind is TurnFailureKind.GUARDRAIL_VIOLATION
    assert outcome.rule is GuardrailRule.REFERENCES_UNSHOWN_STIMULUS
    assert len(outcome.prompt_hashes) == 2 and outcome.prompt_hashes[0] != outcome.prompt_hashes[1]
    # One batch for the turn, one for the single stricter retry — never more.
    assert chat.batches == [["persona_turn"], ["persona_turn_strict"]]
    assert not hasattr(outcome, "turn")


def test_a_turn_accepted_on_retry_records_the_prompt_it_rejected():
    target = unshown()
    chat = BatchCountingChat(
        responder=by_template({"persona_turn": inventing(target), "persona_turn_strict": answering()})
    )
    (outcome,) = turns([make_job(0)], chat=chat)
    assert isinstance(outcome, CompletedTurn)
    assert len(outcome.rejected_prompt_hashes) == 1
    assert outcome.rejected_prompt_hashes[0] != outcome.prompt_hash
    assert outcome.turn.reaction.subject_stimulus_id == stimulus_id(1)
    assert chat.batches == [["persona_turn"], ["persona_turn_strict"]]


def test_a_retry_that_also_fails_records_a_violation_and_no_reaction():
    chat = BatchCountingChat(
        responder=by_template({"persona_turn": "this is not json", "persona_turn_strict": "still not json"})
    )
    (outcome,) = turns([make_job(0)], chat=chat)
    assert isinstance(outcome, TurnFailure)
    assert outcome.kind is TurnFailureKind.GUARDRAIL_VIOLATION
    assert outcome.rule is GuardrailRule.UNPARSEABLE_OUTPUT
    assert outcome.prompt_hashes[0] != outcome.prompt_hashes[1]
    assert chat.batches == [["persona_turn"], ["persona_turn_strict"]]


def test_unparseable_output_follows_the_same_one_retry_path():
    chat = BatchCountingChat(responder=by_template({"persona_turn": "not json", "persona_turn_strict": answering()}))
    (outcome,) = turns([make_job(0)], chat=chat)
    assert isinstance(outcome, CompletedTurn)
    assert len(outcome.rejected_prompt_hashes) == 1


def test_a_verbatim_naming_an_unshown_stimulus_is_rejected_too():
    target = unshown()
    chat = BatchCountingChat(
        responder=by_template(
            {
                "persona_turn": inventing(stimulus_id(1), verbatim=f"reminds me of {target}"),
                "persona_turn_strict": answering(),
            }
        )
    )
    (outcome,) = turns([make_job(0)], chat=chat)
    assert isinstance(outcome, CompletedTurn)
    assert len(outcome.rejected_prompt_hashes) == 1


def test_the_two_rules_are_the_only_guardrails():
    assert set(GUARDRAILS) == {GuardrailRule.REFERENCES_UNSHOWN_STIMULUS, GuardrailRule.UNPARSEABLE_OUTPUT}
    package = Path("simcore/agent")
    references = []
    for path in sorted(package.glob("*.py")):
        if path.name == "_guard.py":
            continue
        for match in re.finditer(r"GuardrailRule\.([A-Z_]+)", path.read_text()):
            references.append((path.name, match.group(1)))
    assert references == []
