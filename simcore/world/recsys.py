# Adapted from OASIS (https://github.com/camel-ai/oasis, Apache-2.0):
# `recsys.py` + `process_recsys_posts.py`. The hot-score math is copied
# verbatim — its value is fidelity, not our improvement of it — and the
# embedder is swapped to vectors the study carries in, never recomputed per
# tick. This file keeps the upstream ranking shape so quarterly diffs stay
# mechanical; the modes land in order: `random` first as the control arm,
# then `reddit_hot`, then `twitter`, then `twhin`.

"""Who sees what, and the baseline every ranking mode is measured against.

`random` is the control arm: blind to engagement, deterministic under a seed.
`reddit_hot` copies the upstream score verbatim. `twitter` ports X's refresh:
in-network posts first, then interest × recency against profile vectors the
world embeds once and refreshes only when a persona posts. `twhin` reads degree
centralities from the generated graph, computed once when the world is built.
Neither recomputes its signal per tick.
"""

from math import log, log10
from collections.abc import Mapping, Sequence

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


def hot_score(ups: int, downs: int, published_seconds: int) -> float:
    """Reddit's hot ranking, copied verbatim from upstream — fidelity, not improvement.

    The time argument is *when the post was published*, not how old it is: the
    formula rewards later publication, so a newer post outranks an older one at
    equal votes. Only the clock is ours — a world passes the publication tick
    times the tick unit's seconds, because time here is declared in ticks and
    never in wall-clock time. Feeding it an age inverts the ranking: it made a
    five-day-old unvoted post beat a fresh one with ten upvotes.
    """
    score = ups - downs
    order = log10(max(abs(score), 1))
    if score > 0:
        sign = 1
    elif score < 0:
        sign = -1
    else:
        sign = 0
    seconds = published_seconds - 1134028003
    return round(sign * order + seconds / 45000, 7)


def hot_order(
    candidate_ids: list[str],
    ups: Mapping[str, int],
    downs: Mapping[str, int],
    published_ticks: Mapping[str, int],
    world_seed: int,
    tick: int,
    unit_seconds: int,
) -> list[str]:
    """Highest hot score first; ties break from a derived seed, so ordering reproduces.

    `published_ticks` is the tick each stimulus was published at, which is what the
    upstream score expects — an age in its place ranks the oldest stimulus first.

    The tie-break stream derives from (world seed, tick, "recsys:hot") — one
    stream per tick, shared by every persona, because hot ranking is global.
    Votes reach the order only through the upstream score: no other weighting.
    """
    rng = rng_for(world_seed, tick, "recsys:hot")
    tiebreak = {stimulus_id: rng.random() for stimulus_id in sorted(candidate_ids)}
    return sorted(
        candidate_ids,
        key=lambda stimulus_id: (
            -hot_score(ups.get(stimulus_id, 0), downs.get(stimulus_id, 0), published_ticks.get(stimulus_id, 0) * unit_seconds),
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


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors; a zero vector matches nothing."""
    if len(left) != len(right):
        raise ValueError(f"interest match needs one space: {len(left)} dimensions against {len(right)}")
    denom = sum(v * v for v in left) ** 0.5 * sum(v * v for v in right) ** 0.5
    if denom == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denom


def recency_score(age_ticks: int) -> float:
    """OASIS's recency weight, verbatim but for its clock: `log((271.8 − age) / 100)`.

    Upstream counts age in its own time steps and notes the formula holds for at most ~170
    of them; a post older than that can no longer be recommended, so it scores minus infinity.
    """
    remaining = 271.8 - age_ticks
    if remaining <= 0:
        return float("-inf")
    return log(remaining / 100)


def x_order(
    candidate_ids: list[str],
    network: frozenset[str],
    likes: Mapping[str, int],
    profile_vector: Sequence[float] | None,
    stimulus_vectors: Mapping[str, Sequence[float]],
    age_ticks: Mapping[str, int],
    world_seed: int,
    tick: int,
    persona_id: str,
) -> list[str]:
    """The `twitter` mode, ported from OASIS's X refresh (`rec_sys_personalized_twh` + `refresh`).

    In-network first — posts by the persona's ties and follows, most liked first, as upstream
    prepends following posts ordered by `num_likes`. Then everything else, ordered by
    `cosine(profile, post) × log((271.8 − age) / 100)`. Vectors arrive cached, so ranking never
    embeds; a missing vector matches nothing. Ties break from a derived per-persona seed.
    Departures (stated in the report): upstream samples its refresh at random from the top of
    the rec table and pre-filters to 4,000 posts; a study's feed is small, so it is ordered whole.
    """
    rng = rng_for(world_seed, tick, f"recsys:twitter:{persona_id}")
    tiebreak = {stimulus_id: rng.random() for stimulus_id in sorted(candidate_ids)}
    inside = [stimulus_id for stimulus_id in candidate_ids if stimulus_id in network]
    outside = [stimulus_id for stimulus_id in candidate_ids if stimulus_id not in network]

    def interest(stimulus_id: str) -> float:
        vector = stimulus_vectors.get(stimulus_id)
        if profile_vector is None or vector is None:
            return 0.0
        return cosine(profile_vector, vector) * recency_score(age_ticks.get(stimulus_id, 0))

    return sorted(inside, key=lambda sid: (-likes.get(sid, 0), tiebreak[sid])) + sorted(
        outside, key=lambda sid: (-interest(sid), tiebreak[sid])
    )


def hub_order(
    candidate_ids: list[str],
    centralities: Mapping[str, float],
    authors: Mapping[str, str | None],
    age_ticks: Mapping[str, int],
    world_seed: int,
    tick: int,
) -> list[str]:
    """The `twhin` mode: graph-aware ranking by the author's degree centrality.

    Centralities come from the generated graph, computed once when the world
    is built — ranking reads them, never recomputes them. Study-authored
    stimuli carry no author and score zero; recency breaks centrality ties,
    then a derived seed.
    """
    rng = rng_for(world_seed, tick, "recsys:twhin")
    tiebreak = {stimulus_id: rng.random() for stimulus_id in sorted(candidate_ids)}
    return sorted(
        candidate_ids,
        key=lambda stimulus_id: (
            -centralities.get(authors.get(stimulus_id) or "", 0.0),
            age_ticks.get(stimulus_id, 0),
            tiebreak[stimulus_id],
        ),
    )


__all__ = [
    "REASON_FOR_MODE",
    "UNIT_SECONDS",
    "cosine",
    "exposure_concentration",
    "hot_order",
    "hot_score",
    "hub_order",
    "random_order",
    "reason_for",
    "recency_score",
    "scoped_order",
    "x_order",
]
