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
from collections.abc import Sequence

from simcore.schemas import ChatRequest, InferenceRole, Persona, ProbeAnswer, ProbeResult

PROBE_QUESTION = (
    "Answer each question below with a JSON object with key 'answers' holding one short "
    "answer per question, in order, as yourself. Use your own words."
)


def sampled_for_probe(persona_id: str, tick: int, run_seed: int, share: float) -> bool:
    """Whether the persona is probed this tick: a seeded draw, so reruns agree."""
    if share <= 0.0:
        return False
    if share >= 1.0:
        return True
    digest = hashlib.sha256(f"character-probe|{run_seed}|{tick}|{persona_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2**32 < share


def probe_attributes(persona: Persona, run_seed: int, tick: int, count: int) -> list[tuple[str, str]]:
    """The questions' attributes: the persona's own, rotated by a seeded offset.

    A persona with a different attribute value is asked about the same attribute but held
    to a different expected answer; the rotation keeps the asked set from freezing on the
    first attributes alphabetically.
    """
    projected = {**persona.conditioning, **persona.attributes}
    names = sorted(projected)
    if not names:
        return []
    digest = hashlib.sha256(f"probe-attributes|{run_seed}|{tick}|{persona.persona_id}".encode("utf-8")).digest()
    offset = digest[0] % len(names)
    ordered = [names[(offset + index) % len(names)] for index in range(min(count, len(names)))]
    return [(name, str(projected[name])) for name in ordered]


def probe_question(attribute: str) -> str:
    return f"What is your {attribute}?"


def probe_request(block: str, questions: Sequence[str], template_id: str) -> ChatRequest:
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=(
            {"role": "system", "content": block},
            {"role": "user", "content": json.dumps({"questions": list(questions), "instruction": PROBE_QUESTION})},
        ),
        temp=0.0,
        max_tokens=256,
        template_id=template_id,
    )


def parse_probe_answers(text: str, count: int) -> list[str] | None:
    """The model's answers in order, or nothing when the response cannot be used."""
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("answers"), list):
        return None
    answers = raw["answers"]
    if len(answers) != count or not all(isinstance(answer, str) and answer.strip() for answer in answers):
        return None
    return [answer.strip() for answer in answers]


def agrees(expected: str, answer: str) -> bool:
    return expected.casefold().strip() == answer.casefold().strip()


def probe_result(
    persona_id: str, tick: int, asked: Sequence[tuple[str, str]], answers: Sequence[str] | None
) -> ProbeResult:
    """The recorded result: the persona, the questions, the answers and whether each agreed."""
    entries = []
    for (attribute, expected), answer in zip(asked, answers if answers is not None else ["(no answer)"] * len(asked)):
        entries.append(
            ProbeAnswer(
                question=probe_question(attribute),
                attribute=attribute,
                expected=expected,
                answer=answer if isinstance(answer, str) and answer.strip() else "(no answer)",
                agreed=answers is not None and agrees(expected, answer),
            )
        )
    return ProbeResult(persona_id=persona_id, tick=tick, answers=tuple(entries))


def disagreement_rate(results: Sequence[ProbeResult]) -> float:
    """The run's disagreement rate from its recorded probe results alone — the trace suffices."""
    answers = [answer for result in results for answer in result.answers]
    if not answers:
        return 0.0
    return sum(not answer.agreed for answer in answers) / len(answers)
