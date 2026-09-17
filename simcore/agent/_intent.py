"""Purchase intent: scored when it can be, recorded honestly when it cannot.

A purchase-intent turn is scored through `elicitation` when a passing anchor version is
pinned; when none is, the verbatim is kept and the recorded elicitation failure stands
in place of the distribution, so a run without intent data is visibly that (ADR 0032).
No code path asks a model for a number — the question is the frozen free-text template.
"""

from __future__ import annotations

from simcore.elicitation import score as elicitation_score
from simcore.schemas import ElicitationFailure, ElicitationFailureKind, SsrOutcome, TurnTask

from ._config import AgentConfig

PURCHASE_CONSTRUCT = "purchase_intent"


def wants_intent(task: TurnTask) -> bool:
    """Whether a turn's text is purchase intent to be scored."""
    return task is TurnTask.PURCHASE


def score_intents(
    verbatims: dict[int, str], cfg: AgentConfig, embed
) -> dict[int, SsrOutcome]:
    """One elicitation outcome per position, in a single scoring batch.

    Positions without a pinned anchor version never reach the scorer: they keep the
    recorded unpinned failure instead.
    """
    outcomes: dict[int, SsrOutcome] = {}
    scorable = {position: text for position, text in verbatims.items() if _pinned(cfg)}
    for position, text in verbatims.items():
        if position not in scorable:
            outcomes[position] = ElicitationFailure(
                kind=ElicitationFailureKind.UNPINNED_ANCHORS,
                detail="no anchor version is pinned for purchase_intent, so the verbatim is kept and no distribution is recorded",
                response_text=text,
                construct_id=PURCHASE_CONSTRUCT,
            )
    if not scorable:
        return outcomes
    params = cfg.elicitation_params.get(PURCHASE_CONSTRUCT)
    set_id = cfg.anchor_set_ids[PURCHASE_CONSTRUCT]
    try:
        scored = elicitation_score(
            [scorable[position] for position in sorted(scorable)],
            PURCHASE_CONSTRUCT,
            category=cfg.category,
            anchor_set_id=set_id,
            anchor_version=cfg.anchor_versions[PURCHASE_CONSTRUCT],
            embed=embed,
            anchors_dir=cfg.anchors_dir,
            pinned_hashes=cfg.anchor_hashes,
            temperature=params.temperature if params is not None else 1.0,
            epsilon=params.epsilon if params is not None else 0.0,
        )
    except ValueError as error:
        # A refusal about the anchors themselves — no passing check, no pin, an edited file —
        # is a decision about the instrument, not a failure of the embedding model (ADR 0032).
        for position, text in scorable.items():
            outcomes[position] = ElicitationFailure(
                kind=ElicitationFailureKind.UNPINNED_ANCHORS,
                detail=f"the anchors could not be used to score this response: {error}",
                response_text=text,
                construct_id=PURCHASE_CONSTRUCT,
            )
        return outcomes
    except Exception as error:
        for position, text in scorable.items():
            outcomes[position] = ElicitationFailure(
                kind=ElicitationFailureKind.EMBEDDING_FAILURE,
                detail=f"the pinned anchors could not score this response: {error}",
                response_text=text,
                construct_id=PURCHASE_CONSTRUCT,
            )
        return outcomes
    for position, outcome in zip(sorted(scorable), scored):
        outcomes[position] = outcome
    return outcomes


def _pinned(cfg: AgentConfig) -> bool:
    set_id = cfg.anchor_set_ids.get(PURCHASE_CONSTRUCT)
    version = cfg.anchor_versions.get(PURCHASE_CONSTRUCT)
    return bool(set_id and version and cfg.category and set_id in cfg.anchor_hashes and cfg.anchors_dir)
