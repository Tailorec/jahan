"""Deterministic identifiers: derived from what they name, so two processes agree."""

from __future__ import annotations

import hashlib

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def ulid_from(*parts: str) -> str:
    """A valid lowercase ULID body deterministically derived from the given parts."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    first = str(digest[0] % 8)
    body = [first]
    stream = digest[1:]
    while len(body) < 26:
        if not stream:
            digest = hashlib.sha256(digest).digest()
            stream = digest
        body.append(_CROCKFORD[stream[0] % 32])
        stream = stream[1:]
    return "".join(body)


def reaction_id(prompt_hash: str, persona_id: str, index: int) -> str:
    return f"rc-{ulid_from('reaction', prompt_hash, persona_id, str(index))}"


def memory_id(persona_id: str, tick: int, index: int, seed: int) -> str:
    return f"me-{ulid_from('memory', persona_id, str(tick), str(index), str(seed))}"
