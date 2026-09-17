"""The graph channel: one persona telling another about a stimulus.

After a reaction, `wants_to_talk` gates on sentiment strength and tie
strength, and a delivery creates a next-tick exposure with `reason=wom` whose
view records the tie strength between the two personas — teller and told —
rather than the tie to the stimulus author. A cap per teller per tick keeps
one strongly-felt reaction from crossing a dense community in a single tick.
Both gates and the cap are configurable, with documented defaults.
"""

from collections.abc import Mapping

from simcore.schemas import Reaction

from ._seeds import rng_for

# Defaults from the PRD: a reaction felt past 0.6 toward a peer tied past 0.3
# starts a conversation, and one persona tells at most two peers per tick.
DEFAULT_SENTIMENT_THRESHOLD = 0.6
DEFAULT_TIE_THRESHOLD = 0.3
DEFAULT_CAP_PER_TICK = 2


def sentiment_strength(reaction: Reaction) -> float:
    """How strongly a reaction was felt: the largest belief move it records.

    The maximum absolute move across belief dimensions and claim credences,
    or the extremeness of its elicited intent when it carries one — a persona
    that answers 1 or 5 felt more than one that answers 3.
    """
    moves = [abs(change) for change in reaction.belief_change.dimensions.values()]
    moves += [abs(change) for change in reaction.belief_change.claim_credence.values()]
    if reaction.intent is not None:
        expected = sum((point + 1) * mass for point, mass in enumerate(reaction.intent.pmf))
        moves.append(abs(expected - 3.0) / 2.0)
    return max(moves, default=0.0)


def wants_to_talk(
    reaction: Reaction,
    tie_strength: float,
    *,
    sentiment_threshold: float = DEFAULT_SENTIMENT_THRESHOLD,
    tie_threshold: float = DEFAULT_TIE_THRESHOLD,
) -> bool:
    """Whether a reaction reaches a peer: felt strongly, and the two are close."""
    return sentiment_strength(reaction) >= sentiment_threshold and tie_strength >= tie_threshold


def select_targets(
    teller: str,
    ties: Mapping[str, float],
    sentiment: float,
    *,
    world_seed: int,
    tick: int,
    sentiment_threshold: float = DEFAULT_SENTIMENT_THRESHOLD,
    tie_threshold: float = DEFAULT_TIE_THRESHOLD,
    cap: int = DEFAULT_CAP_PER_TICK,
) -> list[str]:
    """Who a teller tells this tick: qualifying peers, capped, drawn from a derived seed.

    Peers the teller is close enough to all qualify when the reaction was
    felt strongly enough; past the cap, targets are a seeded shuffle, so
    deliveries reproduce exactly under the same seed.
    """
    if sentiment < sentiment_threshold:
        return []
    qualifying = sorted(peer for peer, strength in ties.items() if strength >= tie_threshold and peer != teller)
    rng = rng_for(world_seed, tick, f"wom:{teller}")
    rng.shuffle(qualifying)
    return qualifying[: max(0, cap)]


__all__ = [
    "DEFAULT_CAP_PER_TICK",
    "DEFAULT_SENTIMENT_THRESHOLD",
    "DEFAULT_TIE_THRESHOLD",
    "select_targets",
    "sentiment_strength",
    "wants_to_talk",
]
