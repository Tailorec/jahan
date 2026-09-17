"""Derived randomness for the world module.

Every draw — activation, recsys tie-breaks, exposure selection, word-of-mouth
targets — comes from a seed derived from the world seed, the tick and a named
purpose, so adding a later draw cannot shift an earlier one.
"""

import hashlib
from random import Random


def derive_int(world_seed: int, tick: int, purpose: str, index: int = 0) -> int:
    """One 64-bit draw identifier from (world seed, tick, purpose, index).

    `hashlib` digests are stable across processes, unlike the builtin `hash`,
    so two processes draw identically from the same inputs.
    """
    material = f"{int(world_seed)}:{int(tick)}:{purpose}:{int(index)}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def derive_int128(world_seed: int, tick: int, purpose: str, index: int = 0) -> int:
    """128 bits from the same inputs, for minting ULID-shaped identifiers."""
    material = f"{int(world_seed)}:{int(tick)}:{purpose}:{int(index)}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest(), "big")


def rng_for(world_seed: int, tick: int, purpose: str, index: int = 0) -> Random:
    """A `random.Random` fixed by (world seed, tick, purpose, index).

    `Random` seeded with an int is deterministic across processes, so deltas
    built from these streams are bit-identical wherever they run.
    """
    return Random(derive_int(world_seed, tick, purpose, index))
