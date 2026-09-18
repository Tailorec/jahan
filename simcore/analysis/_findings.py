"""Findings authored by extraction, not generation.

Objection clusters become objection findings, belief changes become belief-shift findings,
edges become word-of-mouth path findings. Each is constructed with its evidence ids
resolved against the view it came from — one whose evidence does not exist fails where
it was written — and each carries the disconfirming test that would show it wrong.
Deterministic: two runs over one trace produce the same findings in the same order.
No finding states calibration; confidence reflects the evidence behind it alone.
"""

from collections import Counter

from simcore.schemas import EventFilter, Finding

from ._clusters import cluster_objections

_OBJECTION_HIGH = 8
_OBJECTION_MEDIUM = 3
_BELIEF_MEANINGFUL = 0.05
_BELIEF_HIGH_N = 10


def findings(view, *, embed, threshold: float = 0.75, seed: int = 0) -> tuple[Finding, ...]:
    """Author every finding the trace supports, oldest evidence first within each kind."""
    authored: list[Finding] = []
    authored.extend(_objection_findings(view, embed=embed, threshold=threshold, seed=seed))
    authored.extend(_belief_shift_findings(view))
    authored.extend(_wom_path_findings(view))
    return tuple(authored)


def _resolve(view, evidence: tuple[str, ...]) -> tuple[str, ...]:
    view.resolve(evidence)
    return evidence


def _objection_findings(view, *, embed, threshold: float, seed: int) -> list[Finding]:
    clusters = cluster_objections(view, embed=embed, threshold=threshold, seed=seed)
    out = []
    for index, cluster in enumerate(clusters, start=1):
        evidence = _resolve(view, tuple(cluster.verbatim_trace_ids))
        size = cluster.size
        confidence = "high" if size >= _OBJECTION_HIGH else "medium" if size >= _OBJECTION_MEDIUM else "low"
        out.append(Finding.model_validate({
            "finding_id": f"f-objection-{index:02d}",
            "kind": "objection",
            "statement": f"{size} personas raised the objection quoted as {cluster.label!r}",
            "evidence_trace_ids": list(evidence),
            "disconfirming_test": (
                f"interview {max(size, 5)} people shown the same stimuli; "
                f"if fewer than a third mention {cluster.label!r}, the finding is wrong"
            ),
            "confidence": confidence,
        }))
    return out


def _belief_shift_findings(view) -> list[Finding]:
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
        if abs(mean) < _BELIEF_MEANINGFUL and len(deltas) < 2:
            continue
        evidence = _resolve(view, tuple(event_id for event_id, _ in sorted(deltas)))
        direction = "rose" if mean > 0 else "fell"
        confidence = "high" if len(deltas) >= _BELIEF_HIGH_N and abs(mean) >= 0.1 else "medium" if len(deltas) >= 4 or abs(mean) >= _BELIEF_MEANINGFUL else "low"
        out.append(Finding.model_validate({
            "finding_id": f"f-belief-{position:02d}",
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


def _wom_path_findings(view) -> list[Finding]:
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
            "finding_id": f"f-wom-{position:02d}",
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

    authors: dict[str, str | None] = {}
    for event in view.events(EventFilter()):
        if event.payload.kind == "stimulus_published":
            authors[event.payload.stimulus.stimulus_id] = event.payload.stimulus.author
    carriers: dict[tuple[str, str, str], set[str]] = {}
    for event in view.events(EventFilter()):
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
