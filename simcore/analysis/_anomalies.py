"""Anomalies as rules over what was measured — deterministic arithmetic, no judge model.

Herding reads belief movement against the replicate spread: a trailing window whose mean
move exceeds twice that spread. Backlash reads a split in the sign of belief moves past
a threshold. Flop needs adoption, so until intent exists it reports as not measurable
with its reason, rather than as absent. Thresholds are configuration with documented
defaults, and the applied values travel on every anomaly reported.
"""

from dataclasses import dataclass

from simcore.schemas import Anomaly, EventFilter, OutcomeDigest, UnmeasuredAnomaly


@dataclass(frozen=True)
class AnomalyThresholds:
    """Configuration with documented defaults; the applied values travel with each anomaly."""

    # How many trailing ticks a herding window covers.
    window: int = 3
    # A window herds when its mean move exceeds this multiple of the replicate spread.
    herding_multiplier: float = 2.0
    # A window splits when the smaller sign's share of its moves reaches this.
    backlash_min_share: float = 0.30
    # ... and the window holds at least this many nonzero moves.
    backlash_min_moves: int = 4
    # Adoption below this floor, once measured, is a flop.
    flop_adoption_floor: float = 0.25


@dataclass(frozen=True)
class AnomalyReport:
    anomalies: tuple[Anomaly, ...]
    unmeasured: tuple[UnmeasuredAnomaly, ...]


def detect_anomalies(
    view,
    *,
    scenario_hash: str,
    digest: OutcomeDigest,
    replicate_spread: float | None,
    thresholds: AnomalyThresholds = AnomalyThresholds(),
) -> AnomalyReport:
    """Run the three rules over one world's recorded numbers.

    `replicate_spread` is the spread between that scenario's worlds — never within-world
    variation — so an anomaly threshold is measured against what replicates disagreed on.
    """
    moves = _moves(view)
    anomalies: list[Anomaly] = []
    anomalies.extend(_herding(moves, scenario_hash=scenario_hash, spread=replicate_spread, thresholds=thresholds))
    anomalies.extend(_backlash(moves, scenario_hash=scenario_hash, thresholds=thresholds))
    flop, unmeasured = _flop(view, scenario_hash=scenario_hash, digest=digest, thresholds=thresholds)
    anomalies.extend(flop)
    return AnomalyReport(anomalies=tuple(sorted(anomalies, key=lambda a: (a.tick, a.kind.value))), unmeasured=unmeasured)


def _moves(view) -> list[tuple[int, str, float]]:
    """`(tick, event_id, signed move)` per turn and reflection, oldest first.

    A move is the mean signed belief delta the record states — across dimensions and
    claim credences alike — so the rule reads what personas said changed, recomputable
    by hand from the same events.
    """
    records: list[tuple[int, str, float]] = []
    for event in view.events(EventFilter()):
        kind = event.payload.kind
        if kind == "turn":
            change = event.payload.turn.reaction.belief_change
        elif kind == "reflection":
            change = event.payload.change
        else:
            continue
        deltas = [float(delta) for delta in change.dimensions.values()] + [float(delta) for delta in change.claim_credence.values()]
        if not deltas:
            continue
        records.append((event.tick, event.event_id, sum(deltas) / len(deltas)))
    return sorted(records)


def _windows(moves: list[tuple[int, str, float]], window: int) -> dict[int, list[tuple[int, str, float]]]:
    by_tick: dict[int, list[tuple[int, str, float]]] = {}
    for tick, event_id, move in moves:
        by_tick.setdefault(tick, []).append((tick, event_id, move))
    ticks = sorted(by_tick)
    out: dict[int, list[tuple[int, str, float]]] = {}
    for end in ticks:
        members = [move for tick in ticks if end - window < tick <= end for move in by_tick[tick]]
        out[end] = members
    return out


def _herding(
    moves: list[tuple[int, str, float]], *, scenario_hash: str, spread: float | None, thresholds: AnomalyThresholds
) -> list[Anomaly]:
    if spread is None or spread < 0:
        return []
    limit = thresholds.herding_multiplier * spread
    out = []
    for end in sorted(_windows(moves, thresholds.window)):
        members = _windows(moves, thresholds.window)[end]
        if not members:
            continue
        mean = sum(move for _, _, move in members) / len(members)
        if abs(mean) > limit:
            out.append(Anomaly.model_validate({
                "kind": "herding",
                "scenario_hash": scenario_hash,
                "tick": end,
                "evidence_trace_ids": sorted(event_id for _, event_id, _ in members),
                "threshold": limit,
                "observed": mean,
            }))
    return out


def _backlash(moves: list[tuple[int, str, float]], *, scenario_hash: str, thresholds: AnomalyThresholds) -> list[Anomaly]:
    out = []
    for end in sorted(_windows(moves, thresholds.window)):
        members = _windows(moves, thresholds.window)[end]
        nonzero = [(event_id, move) for _, event_id, move in members if move != 0.0]
        if len(nonzero) < thresholds.backlash_min_moves:
            continue
        positive = sum(1 for _, move in nonzero if move > 0.0)
        share = min(positive, len(nonzero) - positive) / len(nonzero)
        if share >= thresholds.backlash_min_share:
            out.append(Anomaly.model_validate({
                "kind": "backlash",
                "scenario_hash": scenario_hash,
                "tick": end,
                "evidence_trace_ids": sorted(event_id for event_id, _ in nonzero),
                "threshold": thresholds.backlash_min_share,
                "observed": share,
            }))
    return out


def _flop(view, *, scenario_hash: str, digest: OutcomeDigest, thresholds: AnomalyThresholds):
    if digest.adoption is None:
        return [], (UnmeasuredAnomaly.model_validate({
            "kind": "flop",
            "scenario_hash": scenario_hash,
            "reason": "flop needs adoption and this run scored no intent",
            "threshold": thresholds.flop_adoption_floor,
        }),)
    if digest.adoption >= thresholds.flop_adoption_floor:
        return [], ()
    scored = sorted(
        event.event_id for event in view.events(EventFilter())
        if event.payload.kind == "turn" and event.payload.turn.reaction.intent is not None
    )
    ticks = [event.tick for event in view.events(EventFilter()) if event.payload.kind == "turn"]
    return [Anomaly.model_validate({
        "kind": "flop",
        "scenario_hash": scenario_hash,
        "tick": max(ticks) if ticks else 0,
        "evidence_trace_ids": scored or [event.event_id for event in view.events(EventFilter())[:1]],
        "threshold": thresholds.flop_adoption_floor,
        "observed": digest.adoption,
    })], ()
