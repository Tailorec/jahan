"""Where the real corpus is cached, for the tests that run against it and skip without it.

One lookup for every real-data test, so they agree on what "cached" means, and one place the report
header reads — a whole class of tests skipping must be announced, not discovered by reading `-rs`."""

import os
from pathlib import Path

import pytest

from simcore.ports.hf import default_cache_dir

ENVIRONMENT_VARIABLE = "CONSUMERSIM_CORESET_CACHE"


def real_cache() -> Path | None:
    """The first candidate holding a manifest and at least one shard: the variable, then the default."""
    candidates = [Path(os.environ[ENVIRONMENT_VARIABLE])] if os.environ.get(ENVIRONMENT_VARIABLE) else []
    candidates.append(default_cache_dir())
    for cache in candidates:
        if (cache / "manifest.json").is_file() and any((cache / "data").glob("persona-1m-*.parquet")):
            return cache
    return None


REAL_CACHE = real_cache()

real_corpus = pytest.mark.skipif(
    REAL_CACHE is None,
    reason=f"no cached corpus shards; set {ENVIRONMENT_VARIABLE}=/path/to/persona_1m to run real-data tests",
)


def report_line() -> str:
    if REAL_CACHE is None:
        return (
            f"real-corpus tests: SKIPPED — no cached shards at {default_cache_dir()}; "
            f"set {ENVIRONMENT_VARIABLE}=/path/to/persona_1m to run them"
        )
    shards = sorted(path.stem for path in (REAL_CACHE / "data").glob("persona-1m-*.parquet"))
    return f"real-corpus tests: running against {REAL_CACHE} ({len(shards)} shards: {', '.join(shards)})"
