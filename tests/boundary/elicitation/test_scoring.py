"""Phase 5: scoring batches end to end."""

from pathlib import Path

import pytest

from simcore.elicitation import anchor_hash, clear_anchor_cache, load_anchor_version, rescore_from_similarities, score
from simcore.inference import EmbeddingFailure
from simcore.ports.fake import FakeEmbed
from simcore.schemas import CallFailure, ElicitationFailure, SsrResult

ANCHORS_DIR = Path(__file__).resolve().parents[3] / "anchors"
PINNED = {
    "purchase-intent-v1": anchor_hash(load_anchor_version(ANCHORS_DIR / "purchase_intent" / "v1.json")),
}

BASE = dict(
    construct="purchase_intent",
    category="beverage_protein",
    anchor_set_id="purchase-intent-v1",
    anchor_version="v1",
    anchors_dir=ANCHORS_DIR,
    pinned_hashes=PINNED,
)


class CountingEmbed(FakeEmbed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(list(texts))
        return super().embed(texts)


class ChunkFailingEmbed(FakeEmbed):
    """Fails the chunk containing the marked text, scores everything else."""

    def __init__(self, marker: str, failure: EmbeddingFailure, **kwargs):
        super().__init__(**kwargs)
        self.marker = marker
        self.failure = failure

    def embed(self, texts):
        if any(self.marker in text for text in texts):
            raise self.failure
        return super().embed(texts)


def _failure() -> EmbeddingFailure:
    return EmbeddingFailure(
        CallFailure(kind="timed_out", detail="the endpoint timed out", attempts=2, route="primary")
    )


def test_a_batch_returns_one_outcome_per_response_in_request_order():
    clear_anchor_cache()
    responses = ["I would definitely buy this.", "", "I would never buy this."]
    outcomes = score(responses, **BASE, embed=FakeEmbed(dim=8))
    assert len(outcomes) == 3
    assert isinstance(outcomes[0], SsrResult) and isinstance(outcomes[2], SsrResult)
    assert isinstance(outcomes[1], ElicitationFailure)
    assert outcomes[0].response_text == responses[0] and outcomes[2].response_text == responses[2]


def test_a_failed_chunk_fails_only_its_own_responses():
    clear_anchor_cache()
    embed = ChunkFailingEmbed("POISON", _failure(), dim=8)
    responses = ["I love it.", "POISONED chunk here.", "I hate it.", "Another fine answer."]
    outcomes = score(responses, **BASE, embed=embed, chunk_size=1)
    assert isinstance(outcomes[0], SsrResult)
    assert isinstance(outcomes[1], ElicitationFailure) and outcomes[1].kind.value == "embedding_failure"
    assert isinstance(outcomes[2], SsrResult) and isinstance(outcomes[3], SsrResult)


def test_anchor_embeddings_are_computed_once_per_run_and_reused():
    clear_anchor_cache()
    embed = CountingEmbed(dim=8)
    score(["First answer.", "Second answer."], **BASE, embed=embed)
    first_calls = list(embed.texts)
    assert len(first_calls) == 30 + 2  # six sets of five anchors, then the responses
    score(["Third answer."], **BASE, embed=embed)
    anchor_texts = first_calls[:30]
    assert embed.texts[30 + 2 :] == ["Third answer."]
    assert embed.texts.count(anchor_texts[0]) == 1


def test_anchors_and_responses_from_different_models_are_refused():
    clear_anchor_cache()
    score(["An answer."], **BASE, embed=FakeEmbed(dim=8, model_id="model-a"))
    with pytest.raises(ValueError, match="not comparable"):
        score(["An answer."], **BASE, embed=FakeEmbed(dim=8, model_id="model-b"))


def test_an_empty_response_is_a_failure_not_a_distribution():
    clear_anchor_cache()
    (outcome,) = score(["   "], **BASE, embed=FakeEmbed(dim=8))
    assert isinstance(outcome, ElicitationFailure) and outcome.kind.value == "empty_response"
    assert not hasattr(outcome, "pmf")


def test_rescoring_recorded_similarities_reproduces_a_fresh_scoring_exactly():
    clear_anchor_cache()
    embed = FakeEmbed(dim=8)
    (first,) = score(["I would definitely buy this."], **BASE, embed=embed)
    assert isinstance(first, SsrResult)
    assert first.temperature == 1.0 and first.epsilon == 0.0
    per_set, headline = rescore_from_similarities(first.per_set_similarities, epsilon=0.5, temperature=2.0)
    clear_anchor_cache()
    (second,) = score(["I would definitely buy this."], **BASE, embed=FakeEmbed(dim=8), epsilon=0.5, temperature=2.0)
    assert isinstance(second, SsrResult)
    for fresh, rescored in zip(second.per_set_pmfs, per_set):
        assert tuple(fresh) == pytest.approx(tuple(rescored))
    assert tuple(second.pmf) == pytest.approx(tuple(headline))
