"""`inference`: every model call, recorded as what it was.

One batch port (`complete`), one OpenAI-compatible endpoint, and the policies that change what the
trace must say: pin verification, cost sources, retries and the pinned fallback, the circuit breaker,
the replicate-safe cache, seeds and structured output, embedding batching, and OTLP telemetry that is
never the scientific record (ADR 0021, 0022, 0023, 0024, 0025)."""

from ._client import EmbeddingFailure, EmbeddingResult, InferenceClient, UnpinnedRoleError
from ._probe import probe_embeddings
from ._settings import ExecutionSettings
from ._wire import request_hash

__all__ = ["EmbeddingFailure", "EmbeddingResult", "ExecutionSettings", "InferenceClient", "UnpinnedRoleError", "probe_embeddings", "request_hash"]
