"""Projection: turning eligible rows into personas, completing sparse fields from the corpus's own values.

The ontology's relevance order selects fields, the conditioning set lands in `Persona.conditioning`
and everything else in `Persona.attributes`, and every projected field states where it came from.
Completion is a constrained choice from the corpus's value set — classification, not generation,
batched one call per attribute and retried once — so a model can never invent a vocabulary the
filters and gates do not know. Demographics and psychographics are never completed, whatever the
policy says (the contract refuses a policy that lists them, and this refuses to act on one)."""

import hashlib
import json
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
    InferenceRole,
    Persona,
    PersonaFieldDomain,
)

COMPLETION_TEMPLATE_ID = "field_completion"
COMPLETION_MAX_TOKENS = 1024
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
    completion_model_id: str,
) -> Projection:
    """Project each decoded row into a persona, completing sparse fields from the corpus's value sets."""
    ontology = pack.ontology
    conditioning = set(ontology.conditioning_set)
    drafts = {f"p-{row.row_id}": _draft(row, set(ontology.attribute_domains), conditioning) for row in rows}
    synthesized = _complete(_missing(drafts, ontology, conditioning), drafts, coreset, inference)
    personas = tuple(_persona(persona_id, draft, pack) for persona_id, draft in drafts.items())
    total = sum(len(draft.origins) for draft in drafts.values())
    return Projection(personas, _provenance(completion_model_id, synthesized), synthesized / total if total else 0.0)


def _draft(row: DecodedRow, declared: set[AttributeId], conditioning: set[AttributeId]) -> _Draft:
    draft = _Draft(row)
    for attribute, value in row.values.items():
        if attribute not in declared:
            continue
        draft.origins[attribute] = FieldOrigin.GROUNDED
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
) -> int:
    synthesized = 0
    for attribute, persona_ids in missing.items():
        values = tuple(coreset.values(attribute))
        answers = _ask_batch(inference, attribute, values, persona_ids, drafts)
        for persona_id, value in answers.items():
            if value in values:
                drafts[persona_id].attributes[attribute] = value
                drafts[persona_id].origins[attribute] = FieldOrigin.SYNTHESIZED
                synthesized += 1
    return synthesized


def _ask_batch(
    inference: ChatPort,
    attribute: AttributeId,
    values: tuple[AttributeValue, ...],
    persona_ids: Sequence[str],
    drafts: Mapping[str, _Draft],
) -> dict[str, str]:
    """One call for the whole batch; an off-list answer is retried once, then left absent."""
    request = {
        "attribute": attribute,
        "values": list(values),
        "personas": [{"persona_id": persona_id, "known": {**drafts[persona_id].conditioning, **drafts[persona_id].attributes}} for persona_id in persona_ids],
    }
    accepted = {persona_id: value for persona_id, value in _ask(inference, request, strict=False).items() if value in values}
    if len(accepted) < len(persona_ids):
        retried = _ask(inference, request, strict=True)
        accepted.update({persona_id: value for persona_id, value in retried.items() if value in values})
    wanted = set(persona_ids)
    return {persona_id: value for persona_id, value in accepted.items() if persona_id in wanted}


def _ask(inference: ChatPort, request: dict, *, strict: bool) -> dict[str, str]:
    messages = [
        {"role": "system", "content": COMPLETION_RETRY_SYSTEM if strict else COMPLETION_SYSTEM},
        {"role": "user", "content": json.dumps(request, sort_keys=True)},
    ]
    completion = inference.chat(
        InferenceRole.TIER_A, messages, temp=0.0, max_tokens=COMPLETION_MAX_TOKENS, template_id=COMPLETION_TEMPLATE_ID
    )
    return _parse(completion.text)


def _parse(text: str) -> dict[str, str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


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


def _provenance(completion_model_id: str, synthesized: int) -> CompletionProvenance | None:
    if synthesized == 0:
        return None
    return CompletionProvenance(
        model_id=completion_model_id,
        template_id=COMPLETION_TEMPLATE_ID,
        template_hash=hashlib.sha256(COMPLETION_SYSTEM.encode("utf-8")).hexdigest(),
    )
