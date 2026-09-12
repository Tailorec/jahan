"""The `EvidencePort` protocol: the whole surface through which the engine reaches a URL."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EvidencePort(Protocol):
    """Retrieve the bytes a cited URL serves.

    Nothing more: hashing, timestamping and writing the sidecar live in the caller, so there is
    exactly one implementation of what gets hashed and the in-memory adapter exercises it."""

    def fetch(self, url: str) -> bytes: ...
