"""Run identifiers minted by the CLI: `run-` plus a 26-character ULID body."""

import secrets

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def _ulid_body(value: int) -> str:
    value &= (1 << 128) - 1
    chars = []
    for pos in range(26):
        chunk = (value >> (125 - 5 * pos)) & 0x1F
        if pos == 0:
            chunk &= 0x07
        chars.append(_CROCKFORD[chunk])
    return "".join(chars)


def mint_run_id() -> str:
    """A fresh run id, unpredictable and well-formed, for a run the user did not name."""
    return f"run-{_ulid_body(secrets.randbits(128))}"
