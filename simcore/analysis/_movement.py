"""The signed belief move a record states — one computation, read by the digest and the rules.

A move is the mean signed delta a turn or a reflection recorded, across belief dimensions and
claim credences alike. The digest reports its mean over a world; the herding rule reads the same
quantity per record and compares a trailing window's mean against the spread of that mean between
a scenario's worlds. Both come from here, so a threshold and the value it is measured against
cannot drift apart.
"""

from collections.abc import Sequence


def signed_moves(events: Sequence) -> list[tuple[int, str, float]]:
    """`(tick, event_id, signed move)` per turn and reflection, oldest first."""
    records: list[tuple[int, str, float]] = []
    for event in events:
        kind = event.payload.kind
        if kind == "turn":
            change = event.payload.turn.reaction.belief_change
        elif kind == "reflection":
            change = event.payload.change
        else:
            continue
        deltas = ([float(delta) for delta in change.dimensions.values()]
                  + [float(delta) for delta in change.claim_credence.values()])
        if not deltas:
            continue
        records.append((event.tick, event.event_id, sum(deltas) / len(deltas)))
    return sorted(records)
