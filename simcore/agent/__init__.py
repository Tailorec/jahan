"""`agent`: one persona's reaction to what it was shown.

Batch-first like `inference` and `elicitation`: `turns(jobs) -> outcomes` returns one
outcome per job in request order — a completed turn or a recorded turn failure, never an
exception for one persona and never a silent gap (ADR 0031). A single turn is
`turns([job])[0]`; there is no separate code path behind it.

The agent stores nothing: `PersonaState` travels in and out with each job, the trace is
the only store, and the runner is its only writer (ADR 0030). The persona block is
assembled here and nowhere else, and a turn cannot proceed unconditioned.
"""

from ._beliefs import (
    advance_state,
    apply_change,
    combine,
    enforce_cap,
    max_abs_change,
    reflection_due,
    reflection_interval_for,
    split_summary,
)
from ._config import AgentConfig, DEFAULT_TIER_ROUTING
from ._context import ContextBudgetExceeded, estimate_tokens
from ._memory import append_memories, importance_of, retrieve, score_memory, write_memory
from ._render import PersonaBlockCache, render_block, selected_attributes
from ._turns import turns

__all__ = [
    "AgentConfig",
    "ContextBudgetExceeded",
    "DEFAULT_TIER_ROUTING",
    "PersonaBlockCache",
    "advance_state",
    "append_memories",
    "apply_change",
    "combine",
    "enforce_cap",
    "estimate_tokens",
    "importance_of",
    "max_abs_change",
    "reflection_due",
    "reflection_interval_for",
    "render_block",
    "retrieve",
    "score_memory",
    "selected_attributes",
    "split_summary",
    "turns",
    "write_memory",
]
