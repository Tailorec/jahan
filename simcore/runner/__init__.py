"""`runner`: executing a study within a budget.

One interface — `run(config, ...) -> RunResult`: one outcome per world, and
the run's status computed from them, never asserted. One writer — the runner
assigns every `event_id` and `seq`, buffers a tick, and writes it with its
`tick_closed` in one call.
"""

from ._ladder import last_recorded_rung, plan_for, recorded_rungs, rung_for
from ._ledger import ledger_sum, mean_tick_cost, pessimistic_figure
from ._plans import LadderConfig, TickPlan, agent_routing_for
from ._refusal import ResumeRefused, check_resume_inputs
from ._resume import last_closed_tick, next_seq, rebuild_persona_states, turns_by_tick, validate_checkpoint
from ._run import WorldFailed, run, run_world
from ._trace import InMemoryRegistry, InMemoryTraceSink
from ._version import ENGINE_VERSION

__all__ = [
    "ENGINE_VERSION",
    "InMemoryRegistry",
    "InMemoryTraceSink",
    "LadderConfig",
    "ResumeRefused",
    "TickPlan",
    "WorldFailed",
    "agent_routing_for",
    "check_resume_inputs",
    "last_closed_tick",
    "last_recorded_rung",
    "ledger_sum",
    "mean_tick_cost",
    "next_seq",
    "pessimistic_figure",
    "plan_for",
    "rebuild_persona_states",
    "recorded_rungs",
    "run",
    "run_world",
    "rung_for",
    "turns_by_tick",
    "validate_checkpoint",
]
