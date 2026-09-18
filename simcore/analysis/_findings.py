"""Findings authored by extraction, not generation.

Objection clusters become objection findings, belief changes become belief-shift findings,
edges become word-of-mouth path findings. Each is constructed with its evidence ids
resolved against the view it came from — one whose evidence does not exist fails where
it was written — and each carries the disconfirming test that would show it wrong.
Deterministic: two runs over one trace produce the same findings in the same order.
No finding states calibration; confidence reflects the evidence behind it alone.
"""

from simcore.schemas import EventFilter, Finding, VerbatimGrouping

from ._clusters import cluster_objections

_OBJECTION_HIGH = 8
_OBJECTION_MEDIUM = 3
_BELIEF_MEANINGFUL = 0.05
_BELIEF_HIGH_N = 10
# A statement reads "rose by 0.03", so a mean that rounds to 0.00 there states nothing.
_BELIEF_STATED_DECIMALS = 2


def findings(view, *, embed, threshold: float = 0.75, seed: int = 0,
             pinned_embed_model: str | None = None) -> tuple[Finding, ...]:
    """Author every finding the trace supports, oldest evidence first within each kind."""
    authored: list[Finding] = []
    authored.extend(_objection_findings(view, embed=embed, threshold=threshold, seed=seed,
                                        pinned_embed_model=pinned_embed_model))
    authored.extend(_belief_shift_findings(view))
    authored.extend(_wom_path_findings(view))
    return tuple(authored)


def _resolve(view, evidence: tuple[str, ...]) -> tuple[str, ...]:
    view.resolve(evidence)
    return evidence


def _said_by(view) -> dict[str, str]:
    """Which persona each verbatim came from, so a cluster is counted in people."""
    return {record.event_id: record.persona_id
            for group in view.verbatims(VerbatimGrouping.PERSONA) for record in group.records}


def _objection_findings(view, *, embed, threshold: float, seed: int,
                        pinned_embed_model: str | None) -> list[Finding]:
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
            "finding_id": f"f-objection-{index:02d}",
            "kind": "objection",
            # Clustering groups what personas said; it cannot tell praise from a complaint, so the
            # statement quotes and counts rather than characterising what the quote means.
            "statement": (
                f"{people} {'persona' if people == 1 else 'personas'} said something this cluster "
                f"groups, quoted as {cluster.label!r} ({size} {'verbatim' if size == 1 else 'verbatims'} "
                f"at cosine {threshold})"
            ),
            "evidence_trace_ids": list(evidence),
            "disconfirming_test": (
                f"interview {max(people, 5)} people shown the same stimuli; "
                f"if fewer than a third say something like {cluster.label!r}, the finding is wrong"
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
