"""The character probe: turning drift from a worry into a number.

A seeded share of activated personas, on a fixed cadence, is asked questions whose
answers are already in that persona's own attributes. The answers are compared with the
attributes and the disagreement rate is recorded per run as its own trace payload. The
probe runs on tier A and adds no tier-B call; a probe that disagrees never fails the
turn or alters the reaction — drift is measured, not corrected.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Sequence

from simcore.ports.answers import coerce_json
from simcore.schemas import ChatRequest, InferenceRole, Persona, ProbeAnswer, ProbeResult

PROBE_QUESTION = (
    "Answer each question below with a JSON object with key 'answers' holding one answer per "
    "question, in order, as yourself. Each answer must be exactly one of the options offered "
    "for that question, copied as written."
)


def sampled_for_probe(persona_id: str, tick: int, run_seed: int, share: float) -> bool:
    """Whether the persona is probed this tick: a seeded draw, so reruns agree."""
    if share <= 0.0:
        return False
    if share >= 1.0:
        return True
    digest = hashlib.sha256(f"character-probe|{run_seed}|{tick}|{persona_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 < share


def probe_options(
    attribute: str,
    expected: str,
    ontology=None,
    *,
    run_seed: int,
    tick: int,
    count: int = 4,
    extra_domain: Sequence[str] = (),
) -> tuple[str, ...]:
    """The closed set offered for one attribute: the persona's own value among distractors.

    The domain comes from the ontology's ordinal scale for the attribute, or from values the
    persona's own completion distribution named. An attribute with no known domain gets no
    question at all, because an open answer cannot be judged: a persona answering in its own
    words would read as drift when it is perfectly in character.
    """
    domain: list[str] = []
    if ontology is not None:
        for scale in getattr(ontology, "ordinal_scales", ()):
            if scale.attribute == attribute:
                domain = [band.label for band in scale.bands]
                break
    if not domain:
        domain = [str(value) for value in extra_domain]
    domain = [value for value in dict.fromkeys(domain) if value]
    if expected not in domain or len(domain) < 2:
        return ()
    distractors = sorted(value for value in domain if value != expected)
    rng = _rng(f"probe-options|{run_seed}|{tick}|{attribute}")
    rng.shuffle(distractors)
    offered = [expected, *distractors[: max(1, count - 1)]]
    rng.shuffle(offered)
    return tuple(offered)


def probe_attributes(
    persona: Persona, run_seed: int, tick: int, count: int, ontology=None
) -> list[tuple[str, str, tuple[str, ...]]]:
    """The questions this persona is asked: its own attributes that have a domain to choose from.

    The asked set rotates by a seeded offset, so a probe does not freeze on the first
    attributes alphabetically; attributes with no known domain are skipped.
    """
    projected = {**persona.conditioning, **persona.attributes}
    names = sorted(projected)
    if not names:
        return []
    digest = hashlib.sha256(f"probe-attributes|{run_seed}|{tick}|{persona.persona_id}".encode("utf-8")).digest()
    offset = digest[0] % len(names)
    ordered = [names[(offset + index) % len(names)] for index in range(len(names))]
    asked: list[tuple[str, str, tuple[str, ...]]] = []
    for name in ordered:
        if len(asked) == count:
            break
        expected = str(projected[name])
        completed = persona.completed_distributions.get(name)
        options = probe_options(
            name,
            expected,
            ontology,
            run_seed=run_seed,
            tick=tick,
            extra_domain=tuple(completed.values) if completed is not None else (),
        )
        if options:
            asked.append((name, expected, options))
    return asked


def probe_question(attribute: str) -> str:
    return f"Which of these is your {attribute}?"


def _rng(purpose: str) -> random.Random:
    """A stream named by its purpose, so adding a draw elsewhere cannot shift this one."""
    digest = hashlib.sha256(purpose.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def normalise(text: str) -> str:
    """Comparable form: case, underscores and punctuation carry no meaning in an answer."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def probe_request(block: str, asked: Sequence[tuple[str, str, Sequence[str]]], template_id: str) -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(
            {"role": "system", "content": block},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "questions": [
                            {"attribute": attribute, "question": probe_question(attribute), "options": list(options)}
                            for attribute, _, options in asked
                        ],
                        "instruction": PROBE_QUESTION,
                    }
                ),
            },
        ),
        temp=0.0,
        max_tokens=256,
        template_id=template_id,
    )


def parse_probe_answers(text: str, count: int) -> list[str] | None:
    """The model's answers in order, or nothing when the response cannot be used."""
    # The same tolerance the turn parser has: a real model fences its JSON, and every probe of
    # the first real study came back "(no answer)" because this one did not.
    try:
        raw = coerce_json(text)
    except ValueError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("answers"), list):
        return None
    answers = raw["answers"]
    if len(answers) != count or not all(isinstance(answer, str) and answer.strip() for answer in answers):
        return None
    return [answer.strip() for answer in answers]


def _tokens(text: str) -> list[str]:
    return normalise(text).split()


def _names(spoken: list[str], option: list[str]) -> bool:
    """Whether the answer's words contain the option's words, in order and adjacent."""
    if not option:
        return False
    return any(spoken[start : start + len(option)] == option for start in range(len(spoken) - len(option) + 1))


def named_options(answer: str, options: Sequence[str]) -> list[str]:
    """Which of the offered options an answer names, however it is written.

    One option's words can sit inside another's — `weekly` inside `3_plus_weekly` — so an
    option named only as part of a longer one it matched is not counted: an answer of
    "3_plus_weekly" names that band, not the `weekly` band beside it.
    """
    spoken = _tokens(answer)
    matched = [(option, _tokens(option)) for option in options if _names(spoken, _tokens(option))]
    return [
        option
        for option, words in matched
        if not any(other is not words and _names(other, words) for _, other in matched)
    ]


def agrees(expected: str, answer: str, options: Sequence[str] = ()) -> bool:
    """Whether the answer chose the persona's own value, and only that one."""
    if not options:
        return normalise(expected) == normalise(answer)
    named = named_options(answer, options)
    return named == [expected] if len(named) == 1 else False


def probe_result(
    persona_id: str,
    tick: int,
    asked: Sequence[tuple[str, str, Sequence[str]]],
    answers: Sequence[str] | None,
) -> ProbeResult:
    """The recorded result: the questions, the options, the answers and whether each agreed.

    An answer that named no option, and a probe whose call never answered, are recorded as
    unanswered — they carry no verdict, so they cannot inflate the drift rate.
    """
    entries = []
    for index, (attribute, expected, options) in enumerate(asked):
        raw = answers[index] if answers is not None and index < len(answers) else None
        named = named_options(raw, options) if raw else []
        answered = bool(raw) and len(named) == 1
        entries.append(
            ProbeAnswer(
                question=probe_question(attribute),
                attribute=attribute,
                expected=expected,
                answer=raw.strip() if isinstance(raw, str) and raw.strip() else "(no answer)",
                agreed=answered and named == [expected],
                options=tuple(options),
                answered=answered,
            )
        )
    return ProbeResult(persona_id=persona_id, tick=tick, answers=tuple(entries))


def disagreement_rate(results: Sequence[ProbeResult]) -> float:
    """The run's disagreement rate from its recorded probe results alone — the trace suffices."""
    answers = [answer for result in results for answer in result.answers if answer.answered]
    if not answers:
        return 0.0
    return sum(not answer.agreed for answer in answers) / len(answers)
