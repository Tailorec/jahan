"""Exit codes, from the exception class, mapped in one place.

A study's verdict is never mistaken for a defect: a failed gate exits 2, an exhausted
budget exits 3 with its partial results kept, a contract mismatch exits 5, anything
else the engine raises exits 1 — and an unexpected exception exits 1 rather than
something arbitrary.
"""

from __future__ import annotations

import sys
import traceback

from simcore.schemas.errors import BudgetExhausted, GateFailure, SchemaVersionError, SimError

EXIT_CODES: dict[type[BaseException], int] = {
    SimError: 1,
    GateFailure: 2,
    BudgetExhausted: 3,
    SchemaVersionError: 5,
}


def exit_code_for(error: BaseException) -> int:
    """The exit code for what happened, by class. A new exception class without its own
    mapping inherits its parent's — a new `SimError` exits 1."""
    for cls in type(error).__mro__:
        if cls in EXIT_CODES:
            return EXIT_CODES[cls]
    return 1


def report_error(error: BaseException) -> int:
    """Print what happened and answer its exit code."""
    code = exit_code_for(error)
    print(f"error: {error}", file=sys.stderr)
    if code == 1 and not isinstance(error, SimError):
        traceback.print_exc()
    return code
