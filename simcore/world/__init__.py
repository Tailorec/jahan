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
from .platform import AFFORDANCES, is_supported
from .replay import ReplayDivergence, check_replay, resume
from .replay import run as replay_run

__all__ = [
    "AFFORDANCES",
    "DAY_RHYTHM",
    "HOUR_RHYTHM",
    "WEEK_RHYTHM",
    "ForumPreset",
    "RecsysMode",
    "ReplayDivergence",
    "World",
    "WorldConfig",
    "activated_personas",
    "activation_probability",
    "check_replay",
    "forget",
    "is_supported",
    "replay_run",
    "reset",
    "resume",
    "rhythm_at",
    "straggler_tick",
    "step",
]
