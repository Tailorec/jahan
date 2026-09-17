"""The world module: environments, and who sees what.

One port outward — `reset(header) -> WorldDelta` and `step(tick, turns) ->
WorldDelta`, or the `World` class binding both to its header — with
upstream-diffable structure inward (`env.py`, `platform.py`, `recsys.py`,
`clock.py` keep their OASIS file shapes and licence headers).
"""

from .env import ForumPreset, RecsysMode, World, WorldConfig, forget, reset, step
from .replay import ReplayDivergence, check_replay, resume
from .replay import run as replay_run

__all__ = [
    "ForumPreset",
    "RecsysMode",
    "ReplayDivergence",
    "World",
    "WorldConfig",
    "check_replay",
    "forget",
    "replay_run",
    "reset",
    "resume",
    "step",
]
