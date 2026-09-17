# Adapted from OASIS (https://github.com/camel-ai/oasis, Apache-2.0):
# `recsys.py` + `process_recsys_posts.py`. The hot-score math is copied
# verbatim — its value is fidelity, not our improvement of it — and the
# embedder is swapped to vectors the study carries in, never recomputed per
# tick. This file keeps the upstream ranking shape so quarterly diffs stay
# mechanical; the modes land in order: `random` first as the control arm,
# then `reddit_hot`, then `twitter`, then `twhin`.

"""Who sees what, and the baseline every ranking mode is measured against.

`random` selects without reference to engagement, deterministically under a
seed — the control arm that separates filter-driven effects from organic
ones. Every later mode must beat it measurably on the same fixture, which is
why it exists before any ranking mode.
"""

from simcore.schemas import ExposureReason

from ._seeds import rng_for

# The reason each mode's exposures carry: why the stimulus got through.
REASON_FOR_MODE = {
    "random": ExposureReason.RANDOM,
    "reddit_hot": ExposureReason.SOCIAL_PROOF,
    "twitter": ExposureReason.INTEREST,
    "twhin": ExposureReason.SOCIAL_PROOF,
}


def reason_for(mode: str) -> ExposureReason:
    """Why a stimulus selected under `mode` got through to its persona."""
    return REASON_FOR_MODE[mode]


def random_order(candidate_ids: list[str], world_seed: int, tick: int, persona_id: str) -> list[str]:
    """The control arm: a seeded shuffle of the candidates, blind to engagement.

    The stream derives from (world seed, tick, persona, "recsys:random"), so
    adding a later draw cannot shift it, and engagement cannot — the function
    never receives it.
    """
    rng = rng_for(world_seed, tick, f"recsys:random:{persona_id}")
    ordered = list(candidate_ids)
    rng.shuffle(ordered)
    return ordered


def exposure_concentration(deltas) -> float:
    """Top-one share of feed exposures across deltas: the baseline later modes move.

    1.0 means every exposure showed the same stimulus; 1/k means attention
    spread evenly over k stimuli. Measured on one fixture, it is the number
    that separates filter-driven concentration from organic reach.
    """
    counts: dict[str, int] = {}
    total = 0
    for delta in deltas:
        for presentation in delta.presentations:
            for exposure in presentation.impression.exposures:
                counts[exposure.stimulus_id] = counts.get(exposure.stimulus_id, 0) + 1
                total += 1
    if not total:
        return 0.0
    return max(counts.values()) / total


__all__ = ["REASON_FOR_MODE", "exposure_concentration", "random_order", "reason_for"]
