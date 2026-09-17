"""Deterministic identifiers for stimuli and impressions the world publishes.

Schema identifiers are ULID-shaped (`st-`, `im-`, `rc-` plus a 26-character
lowercase Crockford body). Real ULIDs carry wall-clock time and randomness,
both of which would break cross-process determinism, so the world mints
ULID-shaped bodies from its derived seeds instead: same (world seed, tick,
purpose, index) mints the same identifier in every process.
"""

from ._seeds import derive_int128

# Lowercase Crockford base32 without i, l, o, u — exactly the schema's ULID body alphabet.
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def ulid_body(seed_int: int) -> str:
    """A 26-character ULID body from 128 bits of seed: first char holds 3 bits (<= 7)."""
    value = int(seed_int) & ((1 << 128) - 1)
    chars = []
    for pos in range(26):
        chunk = (value >> (125 - 5 * pos)) & 0x1F
        if pos == 0:
            chunk &= 0x07
        chars.append(_CROCKFORD[chunk])
    return "".join(chars)


def stimulus_id(world_seed: int, tick: int, purpose: str, index: int) -> str:
    """A deterministic `st-` identifier for a stimulus published at `tick`."""
    return f"st-{ulid_body(derive_int128(world_seed, tick, f'stimulus:{purpose}', index))}"


def impression_id(world_seed: int, tick: int, persona_id: str, channel: str) -> str:
    """A deterministic `im-` identifier: one per persona, channel and tick."""
    seed = derive_int128(world_seed, tick, f"impression:{channel}:{persona_id}")
    return f"im-{ulid_body(seed)}"
