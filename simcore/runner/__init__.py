"""`runner`: executing a study within a budget.

One interface — `run(config, ...) -> RunResult`: one outcome per world, and
the run's status computed from them, never asserted. One writer — the runner
assigns every `event_id` and `seq`, buffers a tick, and writes it with its
`tick_closed` in one call.
"""

from ._plans import LadderConfig, TickPlan, agent_routing_for
from ._run import run, run_world
from ._trace import InMemoryRegistry, InMemoryTraceSink
from ._version import ENGINE_VERSION

__all__ = [
    "ENGINE_VERSION",
    "InMemoryRegistry",
    "InMemoryTraceSink",
    "LadderConfig",
    "TickPlan",
    "agent_routing_for",
    "run",
    "run_world",
]
