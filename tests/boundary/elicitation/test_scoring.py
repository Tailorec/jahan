"""Phase 5: scoring batches end to end."""

from pathlib import Path

import pytest

from simcore.elicitation import anchor_hash, clear_anchor_cache, load_anchor_version, rescore_from_similarities, score
from simcore.inference import EmbeddingFailure
from simcore.ports.fake import FakeEmbed
from simcore.schemas import CallFailure, ElicitationFailure, SsrResult

from tests.boundary.elicitation.staging import FAKE_MODEL, pinned, stage_passing


@pytest.fixture()
def base(tmp_path: Path) -> dict:
    staged = stage_passing(tmp_path)
    return dict(
        construct="purchase_intent",
        category="beverage_protein",
        anchor_set_id="purchase-intent-v1",
        anchor_version="v1",
        anchors_dir=staged,
        pinned_hashes=pinned(staged),
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


def test_a_batch_returns_one_outcome_per_response_in_request_order(base):
    clear_anchor_cache()
    responses = ["I would definitely buy this.", "", "I would never buy this."]
    outcomes = score(responses, **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    assert len(outcomes) == 3
    assert isinstance(outcomes[0], SsrResult) and isinstance(outcomes[2], SsrResult)
    assert isinstance(outcomes[1], ElicitationFailure)
    assert outcomes[0].response_text == responses[0] and outcomes[2].response_text == responses[2]


def test_a_failed_chunk_fails_only_its_own_responses(base):
    clear_anchor_cache()
    embed = ChunkFailingEmbed("POISON", _failure(), dim=8, model_id=FAKE_MODEL)
    responses = ["I love it.", "POISONED chunk here.", "I hate it.", "Another fine answer."]
    outcomes = score(responses, **base, embed=embed, chunk_size=1)
    assert isinstance(outcomes[0], SsrResult)
    assert isinstance(outcomes[1], ElicitationFailure) and outcomes[1].kind.value == "embedding_failure"
    assert isinstance(outcomes[2], SsrResult) and isinstance(outcomes[3], SsrResult)


def test_anchor_embeddings_are_computed_once_per_run_and_reused(base):
    clear_anchor_cache()
    embed = CountingEmbed(dim=8, model_id=FAKE_MODEL)
    score(["First answer.", "Second answer."], **base, embed=embed)
    first_calls = list(embed.texts)
    assert len(first_calls) == 30 + 2  # six sets of five anchors, then the responses
    score(["Third answer."], **base, embed=embed)
    anchor_texts = first_calls[:30]
    assert embed.texts[30 + 2 :] == ["Third answer."]
    assert embed.texts.count(anchor_texts[0]) == 1


def test_anchors_and_responses_from_different_models_are_refused(base):
    clear_anchor_cache()
    score(["An answer."], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    # A second model is refused twice over: its version never passed a check on that model, and anchors
    # already embedded by the first model are not comparable with its responses.
    with pytest.raises(ValueError, match="re-check on the new model|not comparable"):
        score(["An answer."], **base, embed=FakeEmbed(dim=8, model_id="fake/embed-v2"))


def test_an_empty_response_is_a_failure_not_a_distribution(base):
    clear_anchor_cache()
    (outcome,) = score(["   "], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
    assert isinstance(outcome, ElicitationFailure) and outcome.kind.value == "empty_response"
    assert not hasattr(outcome, "pmf")


def test_rescoring_recorded_similarities_reproduces_a_fresh_scoring_exactly(base):
    clear_anchor_cache()
    embed = FakeEmbed(dim=8, model_id=FAKE_MODEL)
    (first,) = score(["I would definitely buy this."], **base, embed=embed)
    assert isinstance(first, SsrResult)
    assert first.temperature == 1.0 and first.epsilon == 0.0
    per_set, headline = rescore_from_similarities(first.per_set_similarities, epsilon=0.5, temperature=2.0)
    clear_anchor_cache()
    (second,) = score(["I would definitely buy this."], **base, embed=FakeEmbed(dim=8, model_id=FAKE_MODEL), epsilon=0.5, temperature=2.0)
    assert isinstance(second, SsrResult)
    for fresh, rescored in zip(second.per_set_pmfs, per_set):
        assert tuple(fresh) == pytest.approx(tuple(rescored))
    assert tuple(second.pmf) == pytest.approx(tuple(headline))


def test_a_version_whose_check_failed_is_never_scored_even_when_the_run_pins_its_hash():
    """The repository's purchase-intent v1 failed its check on Titan, yet pinning its hash was once enough to score
    against it: nothing on the scoring path consulted the check."""
    clear_anchor_cache()
    repo = Path(__file__).resolve().parents[3] / "anchors"
    with pytest.raises(ValueError, match="failed its check"):
        score(["I would buy it."], construct="purchase_intent", category="beverage_protein", anchor_set_id="purchase-intent-v1",
              anchor_version="v1", anchors_dir=repo, pinned_hashes=pinned(repo), embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))


def test_a_version_with_no_check_record_is_never_scored(tmp_path):
    clear_anchor_cache()
    staged = stage_passing(tmp_path)
    (staged / "purchase_intent" / "v1.check.json").unlink()
    with pytest.raises(ValueError, match="no check result"):
        score(["I would buy it."], construct="purchase_intent", category="beverage_protein", anchor_set_id="purchase-intent-v1",
              anchor_version="v1", anchors_dir=staged, pinned_hashes=pinned(staged), embed=FakeEmbed(dim=8, model_id=FAKE_MODEL))
