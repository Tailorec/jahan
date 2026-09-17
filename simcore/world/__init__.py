"""The world module: environments, and who sees what.

One port outward — `reset(header) -> WorldDelta` and `step(tick, turns) ->
WorldDelta`, or the `World` class binding both to its header — with
upstream-diffable structure inward (`env.py`, `platform.py`, `recsys.py`,
`clock.py` keep their OASIS file shapes and licence headers).
"""

from .clock import (
    DAY_RHYTHM,
    HOUR_RHYTHM,
    WEEK_RHYTHM,
    activated_personas,
    activation_probability,
    rhythm_at,
    straggler_tick,
)
from .env import ForumPreset, RecsysMode, World, WorldConfig, forget, reset, step
from .platform import AFFORDANCES, Forum, is_supported
from .recsys import UNIT_SECONDS, exposure_concentration, hot_order, hot_score, random_order, reason_for, scoped_order
from .recsys import cosine as cosine_similarity
from .recsys import hub_order, interest_order
from .replay import ReplayDivergence, check_replay, resume
from .replay import run as replay_run

__all__ = [
    "AFFORDANCES",
    "DAY_RHYTHM",
    "HOUR_RHYTHM",
    "UNIT_SECONDS",
    "WEEK_RHYTHM",
    "Forum",
    "ForumPreset",
    "RecsysMode",
    "ReplayDivergence",
    "World",
    "WorldConfig",
    "activated_personas",
    "activation_probability",
    "check_replay",
    "cosine_similarity",
    "forget",
    "hot_order",
    "hot_score",
    "hub_order",
    "is_supported",
    "interest_order",
    "exposure_concentration",
    "random_order",
    "reason_for",
    "replay_run",
    "reset",
    "resume",
    "rhythm_at",
    "scoped_order",
    "straggler_tick",
    "step",
]
