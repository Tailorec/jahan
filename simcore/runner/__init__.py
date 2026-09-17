"""`runner`: executing a study within a budget.

One interface — `run(config, ...) -> RunResult`: one outcome per world, and
the run's status computed from them, never asserted. One writer — the runner
assigns every `event_id` and `seq`, buffers a tick, and writes it with its
`tick_closed` in one call.
"""

from ._ledger import ledger_sum, mean_tick_cost, pessimistic_figure
from ._plans import LadderConfig, TickPlan, agent_routing_for
from ._refusal import ResumeRefused, check_resume_inputs
from ._resume import last_closed_tick, next_seq, rebuild_persona_states, turns_by_tick, validate_checkpoint
from ._run import run, run_world
from ._trace import InMemoryRegistry, InMemoryTraceSink
from ._version import ENGINE_VERSION

__all__ = [
    "ENGINE_VERSION",
    "InMemoryRegistry",
    "InMemoryTraceSink",
    "LadderConfig",
    "ResumeRefused",
    "TickPlan",
    "agent_routing_for",
    "check_resume_inputs",
    "last_closed_tick",
    "ledger_sum",
    "mean_tick_cost",
    "next_seq",
    "pessimistic_figure",
    "rebuild_persona_states",
    "run",
    "run_world",
    "turns_by_tick",
    "validate_checkpoint",
]
