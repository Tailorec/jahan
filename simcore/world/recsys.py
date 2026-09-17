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

from math import log10
from collections.abc import Mapping

from simcore.schemas import ExposureReason

from ._seeds import rng_for

# The reason each mode's exposures carry: why the stimulus got through.
REASON_FOR_MODE = {
    "random": ExposureReason.RANDOM,
    "reddit_hot": ExposureReason.SOCIAL_PROOF,
    "twitter": ExposureReason.INTEREST,
    "twhin": ExposureReason.SOCIAL_PROOF,
}

# Seconds each tick unit stands for when hot-score ages are computed. Time in
# the world is declared in ticks, never wall-clock, so a hot age is ticks
# since publication times the unit's seconds — the formula below is verbatim,
# only its time base ticks.
UNIT_SECONDS = {"hour": 3600, "day": 86400, "week": 604800}


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


def hot_score(ups: int, downs: int, age_seconds: int) -> float:
    """Reddit's hot ranking, copied verbatim from upstream — fidelity, not improvement.

    Only the time base is ours: upstream passes seconds since the Reddit epoch
    for a wall-clock post, while a world passes ticks since publication times
    the tick unit's seconds, because interventions and ages are expressed in
    ticks, never wall-clock time.
    """
    score = ups - downs
    order = log10(max(abs(score), 1))
    if score > 0:
        sign = 1
    elif score < 0:
        sign = -1
    else:
        sign = 0
    seconds = age_seconds - 1134028003
    return round(sign * order + seconds / 45000, 7)


def hot_order(
    candidate_ids: list[str],
    ups: Mapping[str, int],
    downs: Mapping[str, int],
    age_ticks: Mapping[str, int],
    world_seed: int,
    tick: int,
    unit_seconds: int,
) -> list[str]:
    """Highest hot score first; ties break from a derived seed, so ordering reproduces.

    The tie-break stream derives from (world seed, tick, "recsys:hot") — one
    stream per tick, shared by every persona, because hot ranking is global.
    Votes reach the order only through the upstream score: no other weighting.
    """
    rng = rng_for(world_seed, tick, "recsys:hot")
    tiebreak = {stimulus_id: rng.random() for stimulus_id in sorted(candidate_ids)}
    return sorted(
        candidate_ids,
        key=lambda stimulus_id: (
            -hot_score(ups.get(stimulus_id, 0), downs.get(stimulus_id, 0), age_ticks.get(stimulus_id, 0) * unit_seconds),
            tiebreak[stimulus_id],
        ),
    )


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


def scoped_order(
    candidate_ids: list[str],
    ups: Mapping[str, int],
    downs: Mapping[str, int],
    age_ticks: Mapping[str, int],
    world_seed: int,
    tick: int,
) -> list[str]:
    """Recency-and-agreement ranking for the community-scoped preset: no hot score.

    A thread scores its agreement (upvotes minus downvotes) minus one point
    per tick of age, so consensus hardens slowly instead of herding quickly.
    Ties break from a derived seed, so ordering reproduces.
    """
    rng = rng_for(world_seed, tick, "recsys:scoped")
    tiebreak = {stimulus_id: rng.random() for stimulus_id in sorted(candidate_ids)}
    return sorted(
        candidate_ids,
        key=lambda stimulus_id: (
            -(ups.get(stimulus_id, 0) - downs.get(stimulus_id, 0)) + age_ticks.get(stimulus_id, 0),
            tiebreak[stimulus_id],
        ),
    )


__all__ = [
    "REASON_FOR_MODE",
    "UNIT_SECONDS",
    "exposure_concentration",
    "hot_order",
    "hot_score",
    "random_order",
    "reason_for",
    "scoped_order",
]
