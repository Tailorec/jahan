"""Batch scoring: responses in, outcomes out, in request order (ADR 0023).

Responses are embedded in capped chunks through the port; a chunk whose embedding fails records
only its own responses as embedding failures while the rest are scored. Anchor embeddings are
computed once per anchor version and model and reused across batches. Anchors and responses must
come from the same pinned model, and a mismatch is refused. An empty response is a failure, not
a distribution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from simcore.schemas import ElicitationFailure, SsrOutcome, SsrResult

from ._anchors import anchor_hash, resolve_anchors
from ._compute import aggregate, per_set_distribution, similarities
from ._question import is_numeric_answer

DEFAULT_CHUNK_SIZE = 64

# Anchor embeddings computed once per run for an anchor version and model, reused across batches:
# digest -> (model, stacked array of shape (sets, 5, dim)). A second model asking for the same
# version is refused: similarities across embedding spaces are not comparable.
_ANCHOR_CACHE: dict[str, tuple[str, "np.ndarray"]] = {}


def rescore_from_similarities(
    per_set_similarities: Sequence[Sequence[float]], epsilon: float, temperature: float
) -> tuple[tuple[tuple[float, ...], ...], tuple[float, ...]]:
    """Recompute per-set distributions and the headline from recorded similarities.

    Changing epsilon or temperature later is arithmetic on the trace, not a re-embedding: this
    reproduces a fresh scoring exactly.
    """
    per_set = tuple(per_set_distribution(tuple(gammas), epsilon=epsilon) for gammas in per_set_similarities)
    return per_set, aggregate(per_set, temperature=temperature)


def _anchor_vectors(
    anchor_sets: Sequence[Sequence[str]], embed, model_id: str, digest: str
) -> "np.ndarray":
    """The stacked anchor embeddings for one version and model, computed once and reused."""
    cached = _ANCHOR_CACHE.get(digest)
    if cached is not None:
        cached_model, stacked = cached
        _check_model_match(cached_model, model_id)
        return stacked
    flat = [statement for anchor_set in anchor_sets for statement in anchor_set]
    result = embed.embed(flat)
    vectors = np.asarray(result.vectors, dtype=np.float32)
    stacked = vectors.reshape(len(anchor_sets), 5, -1)
    _ANCHOR_CACHE[digest] = (model_id, stacked)
    return stacked


def _check_model_match(anchor_model_id: str, response_model_id: str) -> None:
    if anchor_model_id != response_model_id:
        raise ValueError(
            f"anchors embedded by {anchor_model_id!r} but responses by {response_model_id!r}: "
            "similarities across embedding spaces are not comparable, refusing"
        )


def score(
    responses: Sequence[str],
    construct: str,
    *,
    category: str,
    anchor_set_id: str,
    anchor_version: str,
    embed,
    anchors_dir="anchors",
    pinned_hashes: Mapping[str, str] | None = None,
    temperature: float = 1.0,
    epsilon: float = 0.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> tuple[SsrOutcome, ...]:
    """One outcome per response in request order: an `SsrResult` or a recorded elicitation failure."""
    version = resolve_anchors(anchor_set_id, construct, anchor_version, pinned_hashes or {}, anchors_dir)
    digest = anchor_hash(version)
    anchor_model_id = embed.model_id
    anchors = _anchor_vectors(version.sets, embed, anchor_model_id, digest)

    outcomes: list[SsrOutcome | None] = [None] * len(responses)
    cap = max(1, chunk_size)
    for start in range(0, len(responses), cap):
        chunk = list(responses[start : start + cap])
        indices: list[int] = []
        for index, text in enumerate(chunk, start=start):
            if not text.strip():
                outcomes[index] = ElicitationFailure(
                    kind="empty_response",
                    detail="the response is empty, so there is nothing to score",
                    response_text=text,
                    construct_id=construct,
                )
            elif is_numeric_answer(text):
                # No code path scores a model-emitted rating: a numeric answer is a failure.
                outcomes[index] = ElicitationFailure(
                    kind="numeric_answer",
                    detail="the response carries a rating-like number, so it is never scored as prose",
                    response_text=text,
                    construct_id=construct,
                )
            else:
                indices.append(index)
        if not indices:
            continue
        try:
            result = embed.embed([responses[index] for index in indices])
        except Exception as error:
            detail = str(getattr(error, "failure", error))
            for index in indices:
                outcomes[index] = ElicitationFailure(
                    kind="embedding_failure",
                    detail=f"the embedding call for this chunk failed: {detail}",
                    response_text=responses[index],
                    construct_id=construct,
                )
            continue
        response_model_id = result.model_id
        _check_model_match(anchor_model_id, response_model_id)
        vectors = np.asarray(result.vectors, dtype=np.float32)
        for row, index in enumerate(indices):
            gammas = tuple(
                similarities(vectors[row], anchors[set_index]) for set_index in range(len(version.sets))
            )
            per_set, _ = rescore_from_similarities(gammas, epsilon, temperature)
            outcomes[index] = SsrResult.model_validate(
                {
                    "response_text": responses[index],
                    "per_set_pmfs": [list(mass) for mass in per_set],
                    "per_set_similarities": [list(gamma) for gamma in gammas],
                    "construct_id": construct,
                    "category": category,
                    "anchor_set_id": anchor_set_id,
                    "anchor_version": anchor_version,
                    "embed_model_id": response_model_id,
                    "temperature": temperature,
                    "epsilon": epsilon,
                }
            )
    return tuple(outcomes)  # type: ignore[return-value]


def clear_anchor_cache() -> None:
    """Forget cached anchor embeddings; tests use this to isolate model-mismatch cases."""
    _ANCHOR_CACHE.clear()
