"""`agent`: one persona's reaction to what it was shown.

Batch-first like `inference` and `elicitation`: `turns(jobs) -> outcomes` returns one
outcome per job in request order — a completed turn or a recorded turn failure, never an
exception for one persona and never a silent gap (ADR 0031). A single turn is
`turns([job])[0]`; there is no separate code path behind it.

The agent stores nothing: `PersonaState` travels in and out with each job, the trace is
the only store, and the runner is its only writer (ADR 0030). The persona block is
assembled here and nowhere else, and a turn cannot proceed unconditioned.
"""

from ._config import AgentConfig, DEFAULT_TIER_ROUTING
from ._turns import turns

__all__ = ["AgentConfig", "DEFAULT_TIER_ROUTING", "turns"]
