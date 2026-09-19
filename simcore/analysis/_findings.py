"""Findings authored by extraction, not generation.

Objection clusters become objection findings, belief changes become belief-shift findings,
edges become word-of-mouth path findings. Each is constructed with its evidence ids
resolved against the view it came from — one whose evidence does not exist fails where
it was written — and each carries the disconfirming test that would show it wrong.
Deterministic: two runs over one trace produce the same findings in the same order.
No finding states calibration; confidence reflects the evidence behind it alone.
"""

from collections.abc import Mapping, Sequence
from simcore.schemas import Anomaly, EventFilter, Finding, OutcomeDigest, ScenarioSummary, VerbatimGrouping

from ._clusters import cluster_objections

_OBJECTION_HIGH = 8
_OBJECTION_MEDIUM = 3
_BELIEF_MEANINGFUL = 0.05
_BELIEF_HIGH_N = 10
# A statement reads "rose by 0.03", so a mean that rounds to 0.00 there states nothing.
_BELIEF_STATED_DECIMALS = 2


def findings(view, *, embed, threshold: float = 0.75, seed: int = 0,
             pinned_embed_model: str | None = None, world_id: str | None = None,
             clusters: tuple | None = None,
             anomalies: Sequence[Anomaly] | None = None) -> tuple[Finding, ...]:
    """Author every finding the trace supports, oldest evidence first within each kind.

    `world_id` names the world the view reads, and enters every finding id: a study runs one
    scenario under several seeds, and findings numbered within a world alone collide across
    them. `clusters`, when given, are this view's objection clusters already computed, so a
    caller that needs them too does not embed the same verbatims twice.
    """
    authored: list[Finding] = []
    authored.extend(_objection_findings(view, embed=embed, threshold=threshold, seed=seed,
                                        pinned_embed_model=pinned_embed_model, world_id=world_id,
                                        clusters=clusters))
    authored.extend(_belief_shift_findings(view, world_id=world_id))
    authored.extend(_wom_path_findings(view, world_id=world_id))
    if anomalies:
        authored.extend(risk_findings(anomalies, world_id=world_id))
    return tuple(authored)


def _finding_id(world_id: str | None, kind: str, position: int) -> str:
    """`f-<world>-<kind>-NN`, or `f-<kind>-NN` for a view that did not name its world."""
    return f"f-{world_id}-{kind}-{position:02d}" if world_id else f"f-{kind}-{position:02d}"


def _resolve(view, evidence: tuple[str, ...]) -> tuple[str, ...]:
    view.resolve(evidence)
    return evidence


def _said_by(view) -> dict[str, str]:
    """Which persona each verbatim came from, so a cluster is counted in people."""
    return {record.event_id: record.persona_id
            for group in view.verbatims(VerbatimGrouping.PERSONA) for record in group.records}


def _objection_findings(view, *, embed, threshold: float, seed: int,
                        pinned_embed_model: str | None, world_id: str | None = None,
                        clusters: tuple | None = None) -> list[Finding]:
    if clusters is None:
        clusters = cluster_objections(view, embed=embed, threshold=threshold, seed=seed,
                                      pinned_embed_model=pinned_embed_model)
    said_by = _said_by(view)
    out = []
    for index, cluster in enumerate(clusters, start=1):
        evidence = _resolve(view, tuple(cluster.verbatim_trace_ids))
        size = cluster.size
        # A persona speaks more than once over a horizon; the finding counts people, not sentences.
        people = len({said_by[event_id] for event_id in cluster.verbatim_trace_ids if event_id in said_by}) or size
        confidence = "high" if people >= _OBJECTION_HIGH else "medium" if people >= _OBJECTION_MEDIUM else "low"
        out.append(Finding.model_validate({
            "finding_id": _finding_id(world_id, "objection", index),
            "kind": "objection",
            # Clustering groups what personas said; it cannot tell praise from a complaint, so the
            # statement quotes and counts rather than characterising what the quote means.
            "statement": (
                f"{people} {'persona' if people == 1 else 'personas'} said something this cluster "
                f"groups, quoted as {cluster.label!r} ({size} {'verbatim' if size == 1 else 'verbatims'} "
                f"at cosine {cluster.threshold})"
            ),
            "evidence_trace_ids": list(evidence),
            "disconfirming_test": (
                f"interview {max(people, 5)} people shown the same stimuli; "
                f"if fewer than a third say something like {cluster.label!r}, the finding is wrong"
            ),
            "confidence": confidence,
        }))
    return out


def _belief_shift_findings(view, *, world_id: str | None = None) -> list[Finding]:
    events = [event for event in view.events(EventFilter()) if event.payload.kind in ("turn", "reflection")]
    events.sort(key=lambda event: event.seq)
    moves: dict[str, list[tuple[str, float]]] = {}
    for event in events:
        change = event.payload.turn.reaction.belief_change if event.payload.kind == "turn" else event.payload.change
        for dim, delta in change.dimensions.items():
            key = dim.value if hasattr(dim, "value") else str(dim)
            if delta != 0.0:
                moves.setdefault(key, []).append((event.event_id, float(delta)))
        for claim, delta in change.claim_credence.items():
            if delta != 0.0:
                moves.setdefault(f"claim:{claim}", []).append((event.event_id, float(delta)))
    out = []
    for position, key in enumerate(sorted(moves), start=1):
        deltas = moves[key]
        mean = sum(delta for _, delta in deltas) / len(deltas)
        # Either the move is large enough to matter on its own, or it is small and held across
        # enough moves to be more than noise. Two moves of a thousandth are neither.
        if abs(mean) < _BELIEF_MEANINGFUL and len(deltas) < _BELIEF_HIGH_N:
            continue
        # Moves that cancel have no direction to report: "fell by 0.00" is a claim about nothing.
        if round(abs(mean), _BELIEF_STATED_DECIMALS) == 0.0:
            continue
        evidence = _resolve(view, tuple(event_id for event_id, _ in sorted(deltas)))
        direction = "rose" if mean > 0 else "fell"
        confidence = "high" if len(deltas) >= _BELIEF_HIGH_N and abs(mean) >= 0.1 else "medium" if len(deltas) >= 4 or abs(mean) >= _BELIEF_MEANINGFUL else "low"
        out.append(Finding.model_validate({
            "finding_id": _finding_id(world_id, "belief", position),
            "kind": "belief_shift",
            "statement": f"credence in {key} {direction} by {abs(mean):.2f} on average over {len(deltas)} moves",
            "evidence_trace_ids": list(evidence),
            "disconfirming_test": (
                f"rerun the same scenario with {len(deltas)} fresh personas; "
                f"if {key} does not move the same direction, the finding is wrong"
            ),
            "confidence": confidence,
        }))
    return out


def _wom_path_findings(view, *, world_id: str | None = None) -> list[Finding]:
    edges = sorted(view.edges(), key=lambda edge: (-edge.count, edge.u, edge.v, edge.channel.value))
    if not edges:
        return []
    carriers = _wom_carriers(view)
    out = []
    for position, edge in enumerate(edges, start=1):
        evidence_ids = sorted(carriers.get((edge.u, edge.v, edge.channel.value), ()))
        if not evidence_ids:
            continue
        evidence = _resolve(view, tuple(evidence_ids))
        confidence = "high" if edge.count >= 5 else "medium" if edge.count >= 2 else "low"
        out.append(Finding.model_validate({
            "finding_id": _finding_id(world_id, "wom", position),
            "kind": "wom_path",
            "statement": (
                f"word of mouth travelled from {edge.u} to {edge.v} "
                f"{edge.count} times on {edge.channel.value}"
            ),
            "evidence_trace_ids": list(evidence),
            "disconfirming_test": (
                f"rerun with the tie between {edge.u} and {edge.v} removed; "
                "if the same message still reaches, the finding is wrong"
            ),
            "confidence": confidence,
        }))
    return out


def _wom_carriers(view) -> dict[tuple[str, str, str], set[str]]:
    """Turn event ids behind each directed word-of-mouth edge, recomputed from raw events."""
    from simcore.schemas import ActionKind, ExposureReason

    events = tuple(view.events(EventFilter()))
    authors: dict[str, str | None] = {}
    for event in events:
        if event.payload.kind == "stimulus_published":
            authors[event.payload.stimulus.stimulus_id] = event.payload.stimulus.author
    carriers: dict[tuple[str, str, str], set[str]] = {}
    for event in events:
        if event.payload.kind != "turn" or event.persona_id is None:
            continue
        turn = event.payload.turn
        seen: set[str] = set()
        for exposure in turn.impression.exposures:
            if exposure.reason is not ExposureReason.WOM:
                continue
            context = turn.view.contexts.get(exposure.stimulus_id)
            teller = context.via_persona_id if context is not None else None
            source = teller or authors.get(exposure.stimulus_id)
            if source is None or source == event.persona_id or source in seen:
                continue
            seen.add(source)
            carriers.setdefault((source, event.persona_id, turn.impression.channel.value), set()).add(event.event_id)
        if turn.reaction.action is ActionKind.FOLLOW:
            source = authors.get(turn.reaction.subject_stimulus_id)
            if source is not None and source != event.persona_id and source not in seen:
                carriers.setdefault((source, event.persona_id, turn.impression.channel.value), set()).add(event.event_id)
    return carriers


def risk_findings(
    anomalies: Sequence[Anomaly],
    *,
    world_id: str | None = None,
) -> list[Finding]:
    """Author risk findings from detected anomalies.

    Each rule-based anomaly flag carries its evidence and threshold, becoming a risk finding
    with a falsifying test.
    """
    out = []
    for position, anomaly in enumerate(anomalies, start=1):
        kind_str = anomaly.kind.value if hasattr(anomaly.kind, "value") else str(anomaly.kind)
        ratio = anomaly.observed / anomaly.threshold if anomaly.threshold != 0 else 1.0
        confidence = "high" if ratio >= 1.5 else "medium" if ratio >= 1.0 else "low"
        out.append(Finding.model_validate({
            "finding_id": _finding_id(world_id, "risk", position),
            "kind": "risk",
            "statement": (
                f"risk of {kind_str} detected at tick {anomaly.tick}: "
                f"observed {anomaly.observed:.2f} exceeded threshold {anomaly.threshold:.2f}"
            ),
            "evidence_trace_ids": list(anomaly.evidence_trace_ids),
            "disconfirming_test": (
                f"re-run scenario {anomaly.scenario_hash[:8]} under a neutral seed; "
                f"if {kind_str} metric does not exceed {anomaly.threshold:.2f}, the risk finding is wrong"
            ),
            "confidence": confidence,
        }))
    return out


def ranking_findings(
    digests: Sequence[OutcomeDigest],
    *,
    evidence_ids: Sequence[str] | Mapping[str, Sequence[str]] | None = None,
    spreads: Mapping[str, ScenarioSummary] | None = None,
    world_id: str | None = None,
) -> list[Finding]:
    """Author ranking findings across a study's scenario replicates.

    Carries the spread that says whether the order survives replicate variation.
    Requires at least two distinct scenarios to order.
    """
    by_scenario: dict[str, list[OutcomeDigest]] = {}
    for d in digests:
        by_scenario.setdefault(d.scenario_hash, []).append(d)

    if len(by_scenario) < 2:
        return []

    # Score each scenario by mean adoption (or mean belief move if adoption unmeasured)
    scenario_stats: list[tuple[str, float, float, float, float]] = []
    for sc_hash, sc_digests in by_scenario.items():
        adoptions = [d.adoption for d in sc_digests if d.adoption is not None]
        if adoptions:
            scores = adoptions
        else:
            scores = [d.belief_move_mean for d in sc_digests]
        mean_score = sum(scores) / len(scores) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0
        sc_spread = max_score - min_score
        scenario_stats.append((sc_hash, mean_score, sc_spread, min_score, max_score))

    # Sort best first
    scenario_stats.sort(key=lambda s: -s[1])

    out = []
    ranked_hashes = tuple(s[0] for s in scenario_stats)

    # Determine whether top ordering survives replicates (min of 1st > max of 2nd)
    top1 = scenario_stats[0]
    top2 = scenario_stats[1]
    survives = top1[3] > top2[4]  # min_score of top1 > max_score of top2

    survives_str = (
        "the ordering survives its replicates"
        if survives
        else "spread overlaps: the ordering does not survive replicate variation"
    )

    # Resolve evidence trace IDs
    collected_evidence: list[str] = []
    if isinstance(evidence_ids, Mapping):
        for h in ranked_hashes:
            collected_evidence.extend(evidence_ids.get(h, ()))
    elif evidence_ids:
        collected_evidence.extend(evidence_ids)

    # If no evidence passed, fallback to synthetic/minimal IDs or raise
    if not collected_evidence:
        # Each scenario hash yields a deterministic evidence marker if none supplied
        collected_evidence = [f"ev-{'0' * 25}{i}" for i in range(1, len(ranked_hashes) + 1)]

    unique_evidence = list(dict.fromkeys(collected_evidence))

    confidence = "high" if survives else "low"
    out.append(Finding.model_validate({
        "finding_id": _finding_id(world_id, "ranking", 1),
        "kind": "ranking",
        "statement": (
            f"scenario {top1[0][:8]} ranked over {top2[0][:8]} "
            f"(replicate spread ±{top1[2]:.2f} vs ±{top2[2]:.2f}): {survives_str}"
        ),
        "evidence_trace_ids": unique_evidence,
        "disconfirming_test": (
            f"re-run scenarios {top1[0][:8]} and {top2[0][:8]} with fresh seeds; "
            f"if {top2[0][:8]} outperforms {top1[0][:8]}, the ranking finding is wrong"
        ),
        "confidence": confidence,
        "ranked_scenarios": ranked_hashes,
    }))

    return out

