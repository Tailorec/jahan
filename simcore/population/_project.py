"""Projection: turning eligible rows into personas, completing sparse fields from the corpus's own values.

The ontology's relevance order selects fields, the conditioning set lands in `Persona.conditioning`
and everything else in `Persona.attributes`, and every projected field states where it came from.
Completion is a constrained choice from the corpus's value set — classification, not generation,
batched at most twenty-five personas a call and retried once for whoever is still missing — so a
model can never invent a vocabulary the
filters and gates do not know. Demographics and psychographics are never completed, whatever the
policy says (the contract refuses a policy that lists them, and this refuses to act on one)."""

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from simcore.ports import ChatPort, CoresetSource
from simcore.ports.coreset import DecodedRow
from simcore.schemas import (
    AttributeId,
    AttributeValue,
    BeliefDim,
    Beliefs,
    BriefPack,
    CompletionProvenance,
    FieldOrigin,
    FrozenDict,
    GateFailure,
    InferenceRole,
    Persona,
    PersonaFieldDomain,
)

COMPLETION_TEMPLATE_ID = "field_completion"
# Personas per completion call, and the answer tokens budgeted per persona. Operational: they bound what
# one request asks of a model, so an answer always fits the budget it is given.
COMPLETION_BATCH_SIZE = 25
ANSWER_TOKENS_PER_PERSONA = 32
ANSWER_TOKENS_OVERHEAD = 64
COMPLETION_SYSTEM = (
    "You complete sparse persona fields for a population simulation. For each persona, choose exactly "
    "one value from the offered set for the named attribute. Never invent a value. Reply only with a "
    "JSON object mapping each persona id to its chosen value."
)
COMPLETION_RETRY_SYSTEM = (
    COMPLETION_SYSTEM + " Your previous answer used a value outside the offered set; every answer must be "
    "exactly one of the offered values."
)

_NEVER_SYNTHESIZED = frozenset({PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC})


@dataclass
class _Draft:
    row: DecodedRow
    conditioning: dict[AttributeId, AttributeValue] = field(default_factory=dict)
    attributes: dict[AttributeId, AttributeValue] = field(default_factory=dict)
    origins: dict[AttributeId, FieldOrigin] = field(default_factory=dict)


@dataclass(frozen=True)
class Projection:
    personas: tuple[Persona, ...]
    completion: CompletionProvenance | None
    synthesized_share: float


def project(
    pack: BriefPack,
    rows: Sequence[DecodedRow],
    coreset: CoresetSource,
    *,
    inference: ChatPort,
) -> Projection:
    """Project each decoded row into a persona, completing sparse fields from the corpus's value sets.

    The completing model is read from the completions themselves, never supplied by the caller: a model a
    caller expected is not evidence of the model that answered, and a fallback route would otherwise be
    recorded as the primary it replaced."""
    ontology = pack.ontology
    conditioning = set(ontology.conditioning_set)
    drafts: dict[str, _Draft] = {}
    declared = set(ontology.attribute_domains)
    for row in rows:
        persona_id = f"p-{row.row_id}"
        if persona_id in drafts:
            raise GateFailure(f"the sample drew row {row.row_id!r} more than once; one row is one persona")
        drafts[persona_id] = _draft(row, declared, conditioning)
    synthesized, models = _complete(_missing(drafts, ontology, conditioning), drafts, coreset, inference)
    personas = tuple(_persona(persona_id, draft, pack) for persona_id, draft in drafts.items())
    total = sum(len(draft.origins) for draft in drafts.values())
    return Projection(personas, _provenance(models, synthesized), synthesized / total if total else 0.0)


def _draft(row: DecodedRow, declared: set[AttributeId], conditioning: set[AttributeId]) -> _Draft:
    draft = _Draft(row)
    for attribute, value in row.values.items():
        if attribute not in declared:
            continue
        draft.origins[attribute] = row.tiers.get(attribute, FieldOrigin.MEASURED)
        (draft.conditioning if attribute in conditioning else draft.attributes)[attribute] = value
    return draft


def _missing(
    drafts: Mapping[str, _Draft], ontology, conditioning: set[AttributeId]
) -> dict[AttributeId, list[str]]:
    """The personas missing each attribute a model may complete: declared, non-conditioning, and in a
    domain the completion policy allows. Demographics and psychographics are never offered."""
    completable = ontology.completion_policy.completable_domains
    missing: dict[AttributeId, list[str]] = defaultdict(list)
    for persona_id, draft in drafts.items():
        projected = set(draft.conditioning) | set(draft.attributes)
        for attribute, domain in ontology.attribute_domains.items():
            if attribute in projected or attribute in conditioning:
                continue
            if domain not in completable or domain in _NEVER_SYNTHESIZED:
                continue
            missing[attribute].append(persona_id)
    return missing


def _complete(
    missing: Mapping[AttributeId, list[str]],
    drafts: Mapping[str, _Draft],
    coreset: CoresetSource,
    inference: ChatPort,
) -> tuple[int, set[str]]:
    """How many fields were synthesized, and the models whose answers supplied them."""
    synthesized = 0
    models: set[str] = set()
    for attribute, persona_ids in missing.items():
        values = tuple(coreset.values(attribute))
        for start in range(0, len(persona_ids), COMPLETION_BATCH_SIZE):
            batch = persona_ids[start : start + COMPLETION_BATCH_SIZE]
            accepted, answered_by = _ask_batch(inference, attribute, values, batch, drafts)
            for persona_id, value in accepted.items():
                drafts[persona_id].attributes[attribute] = value
                drafts[persona_id].origins[attribute] = FieldOrigin.SYNTHESIZED
                synthesized += 1
            models |= answered_by
    return synthesized, models


def _ask_batch(
    inference: ChatPort,
    attribute: AttributeId,
    values: tuple[AttributeValue, ...],
    persona_ids: Sequence[str],
    drafts: Mapping[str, _Draft],
) -> tuple[dict[str, AttributeValue], set[str]]:
    """One call for the batch; whoever is still missing is asked once more, strictly, then left absent.

    An answer already accepted is kept: the retry asks only about the personas it has no valid value for."""
    answers, model = _ask(inference, _request(attribute, values, persona_ids, drafts), strict=False)
    accepted = _accepted(answers, values, persona_ids)
    answered_by = {model} if accepted else set()
    still_missing = [persona_id for persona_id in persona_ids if persona_id not in accepted]
    if still_missing:
        answers, model = _ask(inference, _request(attribute, values, still_missing, drafts), strict=True)
        retried = _accepted(answers, values, still_missing)
        if retried:
            answered_by.add(model)
        accepted.update(retried)
    return accepted, answered_by


def _request(attribute: AttributeId, values: tuple[AttributeValue, ...], persona_ids: Sequence[str], drafts: Mapping[str, _Draft]) -> dict:
    return {
        "attribute": attribute,
        "values": list(values),
        "personas": [{"persona_id": persona_id, "known": {**drafts[persona_id].conditioning, **drafts[persona_id].attributes}} for persona_id in persona_ids],
    }


def _accepted(answers: Mapping[str, object], values: tuple[AttributeValue, ...], persona_ids: Sequence[str]) -> dict[str, AttributeValue]:
    """The answers that name an offered value, each recorded as the value the corpus offered — its own
    type included, so an integer-coded attribute is completed with integers rather than their spelling."""
    offered = {}
    for value in values:
        offered.setdefault(_comparable(value), value)
    wanted = set(persona_ids)
    accepted: dict[str, AttributeValue] = {}
    for persona_id, answer in answers.items():
        key = _comparable(answer)
        if persona_id in wanted and key is not None and key in offered:
            accepted[persona_id] = offered[key]
    return accepted


def _comparable(value: object) -> tuple[str, object] | None:
    """A value's form for matching an answer to what was offered. A number is compared by its value, so a
    model answering 10, 10.0 or "10" names the offered 10; text is compared as written. A JSON answer can
    only spell a value, and requiring its spelling to match an integer's type would refuse every correct
    answer to an integer-coded attribute."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return ("number", float(value)) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        try:
            number = float(text)
        except ValueError:
            return ("text", text)
        return ("number", number) if math.isfinite(number) else ("text", text)
    return None


def _ask(inference: ChatPort, request: dict, *, strict: bool) -> tuple[dict[str, object], str]:
    messages = [
        {"role": "system", "content": COMPLETION_RETRY_SYSTEM if strict else COMPLETION_SYSTEM},
        {"role": "user", "content": json.dumps(request, sort_keys=True)},
    ]
    budget = ANSWER_TOKENS_OVERHEAD + ANSWER_TOKENS_PER_PERSONA * len(request["personas"])
    completion = inference.chat(InferenceRole.TIER_A, messages, temp=0.0, max_tokens=budget, template_id=COMPLETION_TEMPLATE_ID)
    return _parse(completion.text), completion.cost.model_id


def _parse(text: str) -> dict[str, object]:
    """Persona id to answer, answers kept as the JSON types the model wrote them in."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): value for key, value in parsed.items()}


def _persona(persona_id: str, draft: _Draft, pack: BriefPack) -> Persona:
    return Persona(
        persona_id=persona_id,
        source=draft.row.source,
        conditioning=FrozenDict(draft.conditioning),
        attributes=FrozenDict(draft.attributes),
        origins=FrozenDict(draft.origins),
        embedding=None,
        baseline_beliefs=Beliefs(
            dimensions=FrozenDict({dimension: 0.5 for dimension in BeliefDim}),
            claim_credence=FrozenDict({claim.id: 0.5 for claim in pack.brief.claims}),
        ),
    )


def _provenance(models: set[str], synthesized: int) -> CompletionProvenance | None:
    """The one model whose answers completed this population, or a refusal when there were several.

    A population records a single completing model, so fields invented by a primary and by its fallback
    cannot share one without the record misstating one of them (ADR 0012)."""
    if synthesized == 0:
        return None
    if len(models) != 1:
        raise GateFailure(
            f"sparse fields were completed by more than one model {sorted(models)}; a population records the one "
            "model that completed it, so its synthesized fields are never an unrecorded mixture"
        )
    return CompletionProvenance(
        model_id=next(iter(models)),
        template_id=COMPLETION_TEMPLATE_ID,
        template_hash=hashlib.sha256(COMPLETION_SYSTEM.encode("utf-8")).hexdigest(),
    )
