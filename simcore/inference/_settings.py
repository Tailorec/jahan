"""Execution settings: how a run talks to its endpoint, never what it measured.

Endpoint URL, API key, concurrency, rate limits, timeouts and retry counts live here. They are plain
values read from the environment, never contracts: they change how fast a study runs, not which world
it records, so no hashed identity includes them. Model pins, prices, temperatures and templates are the
hashed counterparts, on `RunConfig` and `PopulationParameters`."""

import os
from dataclasses import dataclass
from pathlib import Path


def _number(source, name: str, default: float) -> float:
    raw = source.get(name)
    return default if raw in (None, "") else float(raw)


def _integer(source, name: str, default: int) -> int:
    return int(_number(source, name, default))


def _optional(source, name: str) -> float | None:
    raw = source.get(name)
    return None if raw in (None, "") else float(raw)


@dataclass(frozen=True)
class ExecutionSettings:
    base_url: str = "http://127.0.0.1:4000/v1"
    api_key: str | None = None
    timeout_s: float = 90.0
    max_concurrency: int = 32
    queue_bound: int = 4096
    requests_per_minute: float | None = None
    tokens_per_minute: float | None = None
    max_retries: int = 3
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 20.0
    circuit_threshold: int = 5
    embeddings_batch_size: int = 64
    cache_dir: Path | None = None
    content_capture: bool = False

    @classmethod
    def from_environment(cls, env: dict[str, str] | None = None) -> "ExecutionSettings":
        source = dict(os.environ if env is None else env)
        cache = source.get("SIMCORE_CACHE_DIR") or source.get("XDG_CACHE_HOME")
        return cls(
            base_url=source.get("SIMCORE_INFERENCE_BASE_URL") or source.get("OPENAI_BASE_URL") or cls.base_url,
            api_key=source.get("SIMCORE_INFERENCE_API_KEY") or source.get("OPENAI_API_KEY"),
            timeout_s=_number(source, "SIMCORE_INFERENCE_TIMEOUT_S", cls.timeout_s),
            max_concurrency=_integer(source, "SIMCORE_INFERENCE_CONCURRENCY", cls.max_concurrency),
            queue_bound=_integer(source, "SIMCORE_INFERENCE_QUEUE_BOUND", cls.queue_bound),
            requests_per_minute=_optional(source, "SIMCORE_INFERENCE_REQUESTS_PER_MINUTE"),
            tokens_per_minute=_optional(source, "SIMCORE_INFERENCE_TOKENS_PER_MINUTE"),
            max_retries=_integer(source, "SIMCORE_INFERENCE_MAX_RETRIES", cls.max_retries),
            backoff_base_s=_number(source, "SIMCORE_INFERENCE_BACKOFF_BASE_S", cls.backoff_base_s),
            backoff_cap_s=_number(source, "SIMCORE_INFERENCE_BACKOFF_CAP_S", cls.backoff_cap_s),
            circuit_threshold=_integer(source, "SIMCORE_INFERENCE_CIRCUIT_THRESHOLD", cls.circuit_threshold),
            embeddings_batch_size=_integer(source, "SIMCORE_INFERENCE_EMBEDDINGS_BATCH_SIZE", cls.embeddings_batch_size),
            cache_dir=(Path(cache) / "simcore" / "inference") if cache else Path.home() / ".cache" / "simcore" / "inference",
            content_capture=source.get("SIMCORE_OTEL_CAPTURE_CONTENT", "").lower() in {"1", "true", "yes"},
        )
