"""The `EmbedPort` protocol: the one way a core module turns text into vectors.

Embeddings are an optional secondary signal a study may enable; the default path opens no embedding
call and carries no array. The array itself never enters a contract — `schemas` is a leaf — so a built
population carries `EmbeddingRef` positions and the array travels beside it."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbedPort(Protocol):
    model_id: str

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...
