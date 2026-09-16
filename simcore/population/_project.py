"""Projection: turning eligible rows into personas, completing sparse fields from distributions the
corpus's models state, sampled by the engine.

The ontology's relevance order selects fields, the conditioning set lands in `Persona.conditioning` and
everything else in `Persona.attributes`, and every projected field states where it came from. A
completion call asks for a probability distribution over the corpus's value set per persona — not a
value — and the engine samples the completed field from that distribution under the population's seed
at the study's recorded completion temperature (ADR 0024). A distribution that does not cover the
vocabulary or sum to one leaves the field uncompleted rather than inventing one, and a population
records the distribution behind every completed field so projection's calibration can be measured after
the fact. All of a build's completion batches are submitted in one batch call; whoever is still missing
afterwards is asked once more, strictly. Demographics and psychographics are never completed, whatever
the policy says (the contract refuses a policy that lists them, and this refuses to act on one)."""

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from simcore.ports import ChatPort, CoresetSource
from simcore.ports.coreset import DecodedRow
from simcore.schemas import (
    AttributeId,
    AttributeValue,
    BeliefDim,
    Beliefs,
    BriefPack,
    ChatRequest,
    Completion,
    CompletedDistribution,
    CompletionProvenance,
    FieldOrigin,
    FrozenDict,
    GateFailure,
    InferenceRole,
    Persona,
    PersonaFieldDomain,
)

COMPLETION_TEMPLATE_ID = "field_completion"
# Personas per completion call, and the answer tokens budgeted per value per persona. Operational: they
# bound what one request asks of a model, so an answer always fits the budget it is given.
COMPLETION_BATCH_SIZE = 25
ANSWER_TOKENS_PER_VALUE = 8
ANSWER_TOKENS_OVERHEAD = 64
# A persona's answer is its id as a JSON key as well as its probabilities, and identifiers and digits tokenize
# poorly. The budget once counted only the probabilities: Ministral 3 8B on Bedrock wrote 1,414 characters in
# 1,132 tokens (1.25 characters a token, 45 tokens a persona) for twenty-five personas, overran a budget of
# 1,064, and stopped mid-list, leaving the whole batch unparseable. A budget is a ceiling, not a charge, so
# ids are counted at a token a character.
CHARACTERS_PER_ID_TOKEN = 1
ANSWER_TOKENS_PER_ENTRY = 12
# How far a stated distribution may drift from summing to one before it is refused rather than trusted.
DISTRIBUTION_TOLERANCE = 1e-3
COMPLETION_SYSTEM = (
    "You complete sparse persona fields for a population simulation. For each persona and the named "
    "attribute, give the probability that the persona holds each offered value: a JSON object mapping "
    "each persona id to a list of probabilities, one per offered value in the order offered, all "
    "between 0 and 1 and summing to 1. Never invent a value. Reply only with that JSON object."
)
COMPLETION_RETRY_SYSTEM = (
    COMPLETION_SYSTEM + " Your previous answer did not give exactly one probability for every offered "
    "value summing to 1; every answer must."
)

_NEVER_SYNTHESIZED = frozenset({PersonaFieldDomain.DEMOGRAPHIC, PersonaFieldDomain.PSYCHOGRAPHIC})


@dataclass
class _Draft:
    row: DecodedRow
    conditioning: dict[AttributeId, AttributeValue] = field(default_factory=dict)
    attributes: dict[AttributeId, AttributeValue] = field(default_factory=dict)
    origins: dict[AttributeId, FieldOrigin] = field(default_factory=dict)
    distributions: dict[AttributeId, CompletedDistribution] = field(default_factory=dict)


@dataclass(frozen=True)
class _Batch:
    attribute: AttributeId
    values: tuple[AttributeValue, ...]
    persona_ids: tuple[str, ...]
    strict: bool


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
    population_seed: int,
    completion_temperature: float = 1.0,
    evaluatable: frozenset[AttributeId] = frozenset(),
) -> Projection:
    """Project each decoded row into a persona, sampling sparse fields from distributions the model states.

    The completing model is read from the completions themselves, never supplied by the caller: a model a
    caller expected is not evidence of the model that answered, and a fallback route would otherwise be
    recorded as the primary it replaced.

    `evaluatable` exists for one caller, the holdout evaluation: attitudes deliberately measured on real
    rows are psychographic and no study may synthesize them, but the technique of projecting them can
    only be judged by running it — through this same path — against answers that were recorded and then
    hidden. It joins no study input; a study population is still refused by the contract."""
    ontology = pack.ontology
    conditioning = set(ontology.conditioning_set)
    drafts: dict[str, _Draft] = {}
    declared = set(ontology.attribute_domains)
    for row in rows:
        persona_id = f"p-{row.row_id}"
        if persona_id in drafts:
            raise GateFailure(f"the sample drew row {row.row_id!r} more than once; one row is one persona")
        drafts[persona_id] = _draft(row, declared, conditioning)
    synthesized, models = _complete(
        _missing(drafts, ontology, conditioning, evaluatable),
        drafts,
        coreset,
        inference,
        population_seed=population_seed,
        completion_temperature=completion_temperature,
    )
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
    drafts: Mapping[str, _Draft], ontology, conditioning: set[AttributeId], evaluatable: frozenset[AttributeId] = frozenset()
) -> dict[AttributeId, list[str]]:
    """The personas missing each attribute a model may complete: declared, non-conditioning, and in a
    domain the completion policy allows — or named for evaluation, which is the holdout's one exception
    and reaches no study. Demographics and psychographics are never offered otherwise."""
    completable = ontology.completion_policy.completable_domains
    missing: dict[AttributeId, list[str]] = defaultdict(list)
    for persona_id, draft in drafts.items():
        projected = set(draft.conditioning) | set(draft.attributes)
        for attribute, domain in ontology.attribute_domains.items():
            if attribute in projected or attribute in conditioning:
                continue
            if attribute not in evaluatable and (domain not in completable or domain in _NEVER_SYNTHESIZED):
                continue
            missing[attribute].append(persona_id)
    return missing


def _complete(
    missing: Mapping[AttributeId, list[str]],
    drafts: Mapping[str, _Draft],
    coreset: CoresetSource,
    inference: ChatPort,
    *,
    population_seed: int,
    completion_temperature: float,
) -> tuple[int, set[str]]:
    """How many fields were completed by sampling, and the models whose distributions supplied them."""
    batches = [
        _Batch(attribute, tuple(coreset.values(attribute)), tuple(persona_ids[start : start + COMPLETION_BATCH_SIZE]), False)
        for attribute, persona_ids in missing.items()
        for start in range(0, len(persona_ids), COMPLETION_BATCH_SIZE)
    ]
    if not batches:
        return 0, set()
    # All of projection's completion batches go out in one batch call; the engine owns the concurrency.
    settled = _ask_all(inference, batches, drafts, population_seed=population_seed, completion_temperature=completion_temperature)
    retrying = []
    for batch in batches:
        done, _model = settled.get((batch.attribute, batch.persona_ids, False), ((), ""))
        remaining = tuple(persona_id for persona_id in batch.persona_ids if persona_id not in done)
        if remaining:
            retrying.append(_Batch(batch.attribute, batch.values, remaining, True))
    if retrying:
        settled.update(_ask_all(inference, retrying, drafts, population_seed=population_seed, completion_temperature=completion_temperature))
    completed = sum(len(personas) for personas, _model in settled.values())
    models = {model for personas, model in settled.values() if personas and model}
    return completed, models


def _ask_all(
    inference: ChatPort,
    batches: Sequence[_Batch],
    drafts: Mapping[str, _Draft],
    *,
    population_seed: int,
    completion_temperature: float,
) -> dict[tuple, tuple[tuple[str, ...], str]]:
    """One batch call; each accepted distribution is sampled into its persona immediately."""
    asks = [_chat_request(batch, drafts) for batch in batches]
    outcomes = inference.complete(asks)
    accepted: dict[tuple, tuple[tuple[str, ...], str]] = {}
    for batch, outcome in zip(batches, outcomes, strict=True):
        key = (batch.attribute, batch.persona_ids, batch.strict)
        if not isinstance(outcome, Completion):
            accepted[key] = ((), "")
            continue
        distributions = _accepted_distributions(_parse(outcome.text), batch, completion_temperature)
        done: list[str] = []
        for persona_id in batch.persona_ids:
            distribution = distributions.get(persona_id)
            if distribution is None:
                continue
            draft = drafts[persona_id]
            draft.attributes[batch.attribute] = _sample(distribution, batch.values, population_seed=population_seed, attribute=batch.attribute, persona_id=persona_id)
            draft.origins[batch.attribute] = FieldOrigin.SYNTHESIZED
            draft.distributions[batch.attribute] = distribution
            done.append(persona_id)
        accepted[key] = (tuple(done), outcome.cost.model_id if done else "")
    return accepted


def _chat_request(batch: _Batch, drafts: Mapping[str, _Draft]) -> ChatRequest:
    payload = {
        "attribute": batch.attribute,
        "values": list(batch.values),
        "personas": [
            {"persona_id": persona_id, "known": {**drafts[persona_id].conditioning, **drafts[persona_id].attributes}}
            for persona_id in batch.persona_ids
        ],
    }
    messages = (
        {"role": "system", "content": COMPLETION_RETRY_SYSTEM if batch.strict else COMPLETION_SYSTEM},
        {"role": "user", "content": json.dumps(payload, sort_keys=True)},
    )
    budget = _answer_budget(batch)
    return ChatRequest(
        role=InferenceRole.TIER_A,
        messages=tuple(FrozenDict(message) for message in messages),
        temp=0.0,
        max_tokens=budget,
        template_id=COMPLETION_TEMPLATE_ID,
        # The schema states only the answer's structure — an object of probability lists — because that is
        # what a repair can fix and what fails a whole call. Whether each persona is present, has one
        # probability per offered value, in range, summing to one, is judged per persona by projection: a
        # schema requiring all of it failed a batch of twenty-five for one malformed vector, and left none
        # of the twenty-four good answers completed.
        json_schema=json.dumps(
            {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "number"}}},
            sort_keys=True,
        ),
    )


def _answer_budget(batch: _Batch) -> int:
    """Tokens enough for every persona's entry: its id as a key, its probabilities, and the punctuation between."""
    width = max(1, len(batch.values))
    return ANSWER_TOKENS_OVERHEAD + sum(
        -(-len(persona_id) // CHARACTERS_PER_ID_TOKEN) + ANSWER_TOKENS_PER_ENTRY + ANSWER_TOKENS_PER_VALUE * width
        for persona_id in batch.persona_ids
    )


def _accepted_distributions(
    answers: Mapping[str, object], batch: _Batch, completion_temperature: float
) -> dict[str, CompletedDistribution]:
    """Each persona's answer that is one probability per offered value summing to one, shaped by the
    study's completion temperature — or nothing for that persona.

    A probability vector is matched positionally to the offered values: there is no value spelling to
    get wrong, and a distribution that cannot be honoured as stated is refused, never repaired by
    hand. What is recorded and drawn from alike is the temperature-applied distribution."""
    accepted: dict[str, CompletedDistribution] = {}
    wanted = set(batch.persona_ids)
    names = tuple(str(value) for value in batch.values)
    for persona_id, answer in answers.items():
        if persona_id not in wanted or not isinstance(answer, (list, tuple)) or len(answer) != len(batch.values):
            continue
        probabilities: list[float] = []
        for probability in answer:
            if isinstance(probability, bool) or not isinstance(probability, (int, float)):
                probabilities = []
                break
            value = float(probability)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                probabilities = []
                break
            probabilities.append(value)
        if len(probabilities) != len(batch.values):
            continue
        total = sum(probabilities)
        if not math.isfinite(total) or total <= 0.0 or abs(total - 1.0) > DISTRIBUTION_TOLERANCE:
            continue
        if completion_temperature != 1.0:
            # Tempered in log space, relative to the likeliest value: p ** (1/T) underflowed every probability
            # to zero at small temperatures and the renormalisation divided by that zero. Here the likeliest
            # value becomes exactly one first, so the total can never vanish; an impossible value stays zero.
            logs = [math.log(probability) if probability > 0.0 else -math.inf for probability in probabilities]
            top = max(logs)
            probabilities = [math.exp((log - top) / completion_temperature) if log != -math.inf else 0.0 for log in logs]
        accepted[persona_id] = _normalised(names, probabilities)
    return accepted


def _normalised(names: tuple[str, ...], probabilities: list[float]) -> CompletedDistribution:
    """Probabilities that sum to one exactly, so what a population records is what it drew from."""
    total = sum(probabilities)
    scaled = [probability / total for probability in probabilities]
    # The rounding residual is absorbed by the largest probability, which is at least one over the width:
    # given to the last one instead, a residual of -2e-16 on a zero made it negative and failed the build.
    largest = max(range(len(scaled)), key=scaled.__getitem__)
    scaled[largest] += 1.0 - sum(scaled)
    return CompletedDistribution(values=names, probabilities=tuple(scaled))


def _sample(
    distribution: CompletedDistribution,
    values: tuple[AttributeValue, ...],
    *,
    population_seed: int,
    attribute: AttributeId,
    persona_id: str,
) -> AttributeValue:
    """The value one seeded draw of the distribution returns: the same seed and the same distribution
    reproduce the same value, and only the population's seed decides the draw. The value is the
    corpus's own — its type included — because the draw picks an index into what was offered."""
    probabilities = np.clip(np.asarray(distribution.probabilities, dtype=np.float64), 0.0, None)
    probabilities = probabilities / probabilities.sum()
    material = f"{population_seed}|{attribute}|{persona_id}".encode("utf-8")
    child = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    index = int(np.random.default_rng(child).choice(len(values), p=probabilities))
    return values[index]


def _parse(text: str) -> dict[str, object]:
    """Persona id to stated probabilities, as the model wrote them."""
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
        completed_distributions=FrozenDict(draft.distributions),
        embedding=None,
        baseline_beliefs=Beliefs(
            dimensions=FrozenDict({dimension: 0.5 for dimension in BeliefDim}),
            claim_credence=FrozenDict({claim.id: 0.5 for claim in pack.brief.claims}),
        ),
    )


def _provenance(models: set[str], synthesized: int) -> CompletionProvenance | None:
    """The one model whose distributions completed this population, or a refusal when there were several.

    A population records a single completing model, so fields completed by a primary and by its fallback
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
