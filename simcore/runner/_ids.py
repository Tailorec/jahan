"""Deterministic event identifiers for the runner.

The runner is a partition's only writer: it assigns every `event_id` and
`seq`. Identifiers are ULID-shaped (`ev-` plus a 26-character lowercase
Crockford body) and derived from (world id, seq) so two processes agree
without coordination.
"""

import hashlib

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def ulid_body(seed_int: int) -> str:
    value = int(seed_int) & ((1 << 128) - 1)
    chars = []
    for pos in range(26):
        chunk = (value >> (125 - 5 * pos)) & 0x1F
        if pos == 0:
            chunk &= 0x07
        chars.append(_CROCKFORD[chunk])
    return "".join(chars)


def event_id(world_id: str, seq: int) -> str:
    digest = hashlib.sha256(f"{world_id}:{int(seq)}".encode("utf-8")).digest()
    return f"ev-{ulid_body(int.from_bytes(digest, 'big'))}"
