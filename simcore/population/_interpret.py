"""The natural-language step: an audience described in words becomes predicates, bounded by coverage.

The model is given only the coverage table for the attributes the ontology declares and the sources the
study admits, so it can choose from the corpus's real vocabulary and cannot propose a field because the
schema lists it (ADR 0020). Everything it returns is validated against the catalog before it is shown:
an unknown attribute, one no admissible source carries, or a value outside an attribute's value set is
refused with the coverage that justified the refusal. As ADR 0014 requires of anything drafted from the
corpus, the interpretation is returned to be confirmed by a person before a draw is made.
"""

import json
from collections.abc import Mapping, Sequence

from simcore.ports import ChatPort, CoresetCatalog
from simcore.schemas import (
    AttributeFilter,
    AttributeId,
    AttributeValue,
    Audience,
    BandRange,
    BriefPack,
    CallFailure,
    ChatRequest,
    Exactly,
    FrozenDict,
    InferenceRole,
    OneOf,
    PersonaSource,
    Completion,
)

INTERPRET_TEMPLATE_ID = "audience_interpretation"
INTERPRET_MAX_TOKENS = 512
INTERPRET_SYSTEM = (
    "You translate an audience described in words into attribute filters for a population study. Choose "
    "attribute names and values only from the coverage table you are given, never one that is not listed. "
    "Reply only with a JSON object mapping each chosen attribute to one value, a list of values, or "
    '{"range": [first, last]} for an ordinal attribute.'
)


def interpret_audience(
    description: str,
    pack: BriefPack,
    *,
    name: str = "audience",
    catalog: CoresetCatalog,
    inference: ChatPort,
    sources: Sequence[PersonaSource] | None = None,
) -> Audience:
    """Turn `description` into an `Audience` of predicates, or refuse the proposal that cannot be run.

    The returned filters are exactly what a hand-authored audience carries: the caller confirms them by
    using them, and previews them with `preview` to see the numbers before any draw."""
    ontology = pack.ontology
    admitted = tuple(sources) if sources is not None else catalog.sources()
    declared = tuple(ontology.relevance_order)
    coverage = catalog.coverage(declared, admitted)
    table = [
        {
            "attribute": attribute,
            "values": list(_values(catalog, attribute)),
            "carrying": {source: coverage[attribute][source].present for source in admitted},
        }
        for attribute in declared
    ]
    proposal = _propose(description, table, inference)
    filters: dict[AttributeId, AttributeFilter] = {}
    for attribute, choice in proposal.items():
        if attribute not in declared:
            raise ValueError(
                f"the interpretation names {attribute!r}, which the ontology {ontology.category}@{ontology.version} does "
                f"not declare; permitted attributes are {sorted(declared)}"
            )
        carried = {source: coverage[attribute][source].present for source in admitted}
        if not any(carried.values()):
            raise ValueError(
                f"the interpretation names {attribute!r}, which no admissible source carries; coverage of "
                f"{attribute!r} is {carried}"
            )
        filters[attribute] = _predicate(attribute, choice, _values(catalog, attribute), carried)
    return Audience(name=name, share=None, attribute_filters=filters)


def _values(catalog: CoresetCatalog, attribute: AttributeId) -> tuple[AttributeValue, ...]:
    try:
        return tuple(catalog.values(attribute))
    except KeyError:
        return ()


def _propose(description: str, table: list[dict], inference: ChatPort) -> Mapping[str, object]:
    messages = (
        FrozenDict({"role": "system", "content": INTERPRET_SYSTEM}),
        FrozenDict({"role": "user", "content": json.dumps({"description": description, "attributes": table}, sort_keys=True)}),
    )
    request = ChatRequest(
        role=InferenceRole.TIER_A,
        messages=messages,
        temp=0.0,
        max_tokens=INTERPRET_MAX_TOKENS,
        template_id=INTERPRET_TEMPLATE_ID,
    )
    (outcome,) = inference.complete((request,))
    if isinstance(outcome, CallFailure):
        raise ValueError(f"the interpretation call failed: {outcome.kind.value} — {outcome.detail}")
    assert isinstance(outcome, Completion)
    try:
        parsed = json.loads(outcome.text)
    except json.JSONDecodeError:
        raise ValueError(f"the interpretation was not valid JSON: {outcome.text!r}") from None
    if not isinstance(parsed, dict):
        raise ValueError(f"the interpretation must be a JSON object mapping attributes to values, got {parsed!r}")
    return {str(attribute): choice for attribute, choice in parsed.items()}


def _predicate(
    attribute: AttributeId, choice: object, vocabulary: tuple[AttributeValue, ...], carried: Mapping[str, int]
) -> AttributeFilter:
    """The predicate `choice` describes, or a refusal naming the attribute, the choice and the vocabulary."""
    if isinstance(choice, dict):
        bounds = choice.get("range")
        if set(choice) != {"range"} or not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise _refuse(attribute, choice, vocabulary, carried, "not a value, a list of values or a range")
        first, last = bounds
        _require(attribute, first, vocabulary, carried)
        _require(attribute, last, vocabulary, carried)
        return BandRange(first=str(first), last=str(last))
    if isinstance(choice, (list, tuple)):
        if not choice:
            raise _refuse(attribute, choice, vocabulary, carried, "an empty list matches nothing")
        for value in choice:
            _require(attribute, value, vocabulary, carried)
        return OneOf(values=tuple(choice))
    _require(attribute, choice, vocabulary, carried)
    return Exactly(value=choice)


def _require(attribute: AttributeId, value: object, vocabulary: tuple[AttributeValue, ...], carried: Mapping[str, int]) -> None:
    if value not in vocabulary:
        raise _refuse(attribute, value, vocabulary, carried, "not one of the attribute's values")


def _refuse(attribute: AttributeId, choice: object, vocabulary: tuple[AttributeValue, ...], carried: Mapping[str, int], why: str) -> ValueError:
    return ValueError(
        f"the interpretation chose {choice!r} for {attribute!r}, which is {why}; {attribute!r} takes "
        f"{list(vocabulary)} and is carried by {carried}"
    )