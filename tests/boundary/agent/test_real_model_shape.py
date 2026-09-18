"""What the first real-model study exposed about the turn prompt and its parser.

Sixty personas, sixty guardrail violations, every one `unparseable_output`. The answers
themselves were fine — the model wrote its JSON inside a markdown fence, which the parser
refused, and before that it had been reacting to the engine's own plumbing: the prompt carried
the impression and the view as serialized JSON, so a persona was shown stimulus *ids* and a
`contexts` field and never the text of the thing it was meant to react to.
"""

from __future__ import annotations

import json

from simcore.agent import AgentConfig, turns
from simcore.agent._parse import parse_reaction
from simcore.ports.fake import FakeChat
from simcore.schemas import CompletedTurn
from tests.boundary.agent.support import make_job

CONCEPT = "An AI code-review assistant that comments on pull requests and flags risky changes"


def fenced(messages, template_id: str) -> str:
    """A real model's answer: correct JSON, wrapped in a markdown fence."""
    user = json.loads(next(message for message in reversed(messages) if message.get("role") == "user")["content"])
    shown = user["shown"]
    stimulus_id = shown[0]["stimulus_id"]
    body = json.dumps({"subject_stimulus_id": stimulus_id, "action": "comment", "verbatim": "I would try this on my own PRs"})
    return f"```json\n{body}\n```"


def test_a_fenced_answer_is_parsed_rather_than_refused():
    """The engine already owns a parser that tolerates decorated model output — the projection
    path uses it after a real run tripped over exactly this — and the turn parser did not."""
    body = '{"subject_stimulus_id": "st-00000000000000000000000001", "action": "comment", "verbatim": "fine by me"}'
    parsed = parse_reaction(f"```json\n{body}\n```")
    assert parsed.action.value == "comment" and parsed.verbatim == "fine by me"
    assert parse_reaction(f"Here you go:\n```\n{body}\n```\nhope that helps").verbatim == "fine by me"
    assert parse_reaction(body).verbatim == "fine by me"


def test_a_persona_is_shown_what_the_stimulus_says():
    """The prompt carried `impression` and `view` as raw JSON, so the persona saw ids and
    internal fields. A real model then reacted to the plumbing — commenting on its own trust
    score and asking what the `contexts` field was for."""
    job = make_job(0, tick=1)
    stimulus_id = job.presentation.impression.exposures[0].stimulus_id
    chat = FakeChat(responder=fenced)
    (outcome,) = turns(
        [job], chat=chat, config=AgentConfig(run_seed=7), stimulus_texts={stimulus_id: CONCEPT}
    )
    assert isinstance(outcome, CompletedTurn)
    sent = json.loads(chat.calls[0])
    user = json.loads(next(message for message in sent if message.get("role") == "user")["content"])
    rendered = json.dumps(user)
    assert CONCEPT in rendered, "the persona was never shown what the stimulus says"
    assert stimulus_id in rendered, "the persona cannot name a subject it was not given an id for"
    for plumbing in ("impression_id", "contexts", "persona_id", "attention"):
        assert plumbing not in rendered, f"the prompt still carries the engine's own {plumbing}"


def test_a_stimulus_with_no_text_given_still_names_itself():
    """A caller that passes no texts keeps working: the id stands in, as it did before."""
    job = make_job(0, tick=1)
    chat = FakeChat(responder=fenced)
    (outcome,) = turns([job], chat=chat, config=AgentConfig(run_seed=7))
    assert isinstance(outcome, CompletedTurn)
    sent = json.loads(chat.calls[0])
    user = json.loads(next(message for message in sent if message.get("role") == "user")["content"])
    assert job.presentation.impression.exposures[0].stimulus_id in json.dumps(user)


def test_the_question_asks_for_a_short_answer():
    """A verbatim that runs long is cut off at the token ceiling mid-string, and the JSON that
    arrives is unparseable through no fault of the model."""
    from simcore.agent._prompt import REACTION_QUESTION

    assert "brief" in REACTION_QUESTION.lower() or "short" in REACTION_QUESTION.lower()
    assert "sentence" in REACTION_QUESTION.lower()


def test_a_probe_answer_is_parsed_as_models_write_it():
    """Every probe in the first real study came back `(no answer)`: the probe parser had the same
    bare `json.loads` the turn parser had, and the model fenced its JSON the same way."""
    from simcore.agent._probe import parse_probe_answers

    body = '{"answers": ["6-10"]}'
    assert parse_probe_answers(f"```json\n{body}\n```", 1) == ["6-10"]
    assert parse_probe_answers(body, 1) == ["6-10"]
    assert parse_probe_answers("I would rather not say", 1) is None


def test_the_turn_asks_the_persona_how_its_views_moved():
    """Across 400 real turns no belief moved at all — the parser reads `belief_deltas` but the
    question never asked for them. With beliefs frozen, reflection can only ever fire on its
    cadence, word of mouth never fires at all (its gate is how strongly a reaction was felt),
    and a belief-shift finding has nothing to find."""
    from simcore.agent._prompt import REACTION_QUESTION

    assert "belief_deltas" in REACTION_QUESTION
    for dimension in ("value", "fit", "trust"):
        assert dimension in REACTION_QUESTION


def test_a_stated_belief_move_reaches_the_turn_and_the_state():
    from simcore.agent import advance_state

    job = make_job(0, tick=1)
    stimulus_id = job.presentation.impression.exposures[0].stimulus_id

    def moved(messages, template_id: str) -> str:
        body = json.dumps(
            {
                "subject_stimulus_id": stimulus_id,
                "action": "comment",
                "verbatim": "that claim moved me",
                "belief_deltas": {"dimensions": {"trust": 0.2}, "claim_credence": {"C1": 0.3}},
            }
        )
        return f"```json\n{body}\n```"

    (outcome,) = turns([job], chat=FakeChat(responder=moved), config=AgentConfig(run_seed=7))
    assert isinstance(outcome, CompletedTurn)
    assert outcome.belief_change.dimensions, "a stated belief move never reached the turn"
    after = advance_state(job.state, outcome, tick=1, memory_cap=50)
    assert after.beliefs.dimensions != job.state.beliefs.dimensions
