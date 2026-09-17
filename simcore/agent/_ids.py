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


def reaction_id(persona_id: str, tick: int, impression_id: str) -> str:
    """One reaction per persona, per impression: what the persona did with what it was shown.

    Derived from the impression rather than the prompt hash, because two prompts can be
    identical — the same persona reacting on two channels in one tick with the same text —
    and two turns would then share an identifier.
    """
    return f"rc-{ulid_from('reaction', persona_id, str(tick), impression_id)}"


def memory_id(persona_id: str, tick: int, impression_id: str, index: int) -> str:
    """One memory per turn and position, named by the impression the turn answered."""
    return f"me-{ulid_from('memory', persona_id, str(tick), impression_id, str(index))}"
