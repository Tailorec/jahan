"""Nothing changed behind your back: fit audiences to quotas in the open.

When a drafted audience falls below its quota, the costliest filter moves to
a description until it fits, and each move is flagged with its counts for the
person to accept or undo. Shares the person stated are kept; a group without
one waits for it. Continue lists exactly what still stands in the way — and an
audience still below its quota cannot reach launch, so the engine's relaxation
ladder never drops a filter the person did not see dropped.
"""

from __future__ import annotations

import math


def fit_to_quotas(matrix, sources, required, audiences, study_size: int) -> list[dict]:
    """Move each below-quota audience's costliest filter to a description
    until it fits, flagging every move with the counts before and after."""
    if study_size < 1:
        raise ValueError(f"a study size counts at least one persona, got {study_size}")
    base = matrix.pool_mask(tuple(sources), tuple(required))
    positions = {attribute: position for position, attribute in enumerate(matrix.attributes)}
    counts = len(audiences) or 1
    fitted = []
    for audience in audiences:
        name = audience.get("name") or "audience"
        share = audience.get("share")
        quota = math.ceil((share if isinstance(share, (int, float)) and share > 0 else 1 / counts) * study_size)
        filters = dict(audience.get("filters") or {})
        descriptions = list(audience.get("descriptions") or [])
        changes = []
        while len(filters) > 1:
            now = int(_apply(matrix, positions, base, filters).sum())
            if now >= quota:
                break
            gains = {
                attribute: int(_apply(matrix, positions, base, {k: v for k, v in filters.items() if k != attribute}).sum())
                for attribute in filters
            }
            worst = max(gains, key=gains.get)
            changes.append({
                "attribute": worst,
                "values": filters[worst],
                "before": now,
                "after": gains[worst],
                "accepted": False,
            })
            descriptions = [*descriptions, worst]
            filters = {k: v for k, v in filters.items() if k != worst}
        head_count = int(_apply(matrix, positions, base, filters).sum())
        fitted.append({
            "name": name, "share": share, "quota": quota, "head_count": head_count,
            "filters": filters, "descriptions": descriptions, "changes": changes,
            "below_quota": head_count < quota,
        })
    return fitted


def _apply(matrix, positions, base, filters):
    import numpy as np

    mask = base
    for attribute, values in filters.items():
        vocabulary = list(matrix.vocabulary[attribute])
        codes = {vocabulary.index(value) for value in values}
        mask = mask & np.isin(matrix.codes[positions[attribute]], list(codes))
    return mask


def continue_blockers(category, questions, changes, audiences, previews) -> list[str]:
    """Exactly what still stands in the way of Continue: an unconfirmed
    category, an unanswered question, an unaccepted change, shares missing or
    not summing to 100%, an audience below its quota."""
    blockers = []
    if not isinstance(category, dict) or not category.get("id"):
        blockers.append("confirm the category — reuse an ontology or start a new one")
    unanswered = [question["phrase"] for question in questions or []]
    if unanswered:
        by_audience: dict[str, list[str]] = {}
        for question in questions or []:
            for name in question.get("applies_to") or []:
                by_audience.setdefault(name, []).append(question["phrase"])
        blockers.append("answer what was asked: " + "; ".join(
            f"{name} — {', '.join(phrases)}" for name, phrases in by_audience.items()
        ) if by_audience else "answer what was asked: " + ", ".join(unanswered))
    pending = [change["attribute"] for change in changes or [] if not change.get("accepted")]
    if pending:
        blockers.append("accept or undo what changed to fit the data: " + ", ".join(pending))
    shares = [audience.get("share") for audience in audiences or []]
    if any(not isinstance(share, (int, float)) for share in shares):
        missing = [audience.get("name") or "audience" for audience in audiences or [] if not isinstance(audience.get("share"), (int, float))]
        blockers.append("give every group a share: " + ", ".join(missing))
    elif abs(sum(shares) - 1.0) > 0.001:
        blockers.append(f"shares add to {round(sum(shares) * 100)}%, not 100%")
    for audience, preview in zip(audiences or [], previews or []):
        quota = preview.get("quota")
        head_count = preview.get("head_count")
        if isinstance(quota, int) and isinstance(head_count, int) and head_count < quota:
            blockers.append(f"{audience.get('name') or 'an audience'} is below its quota ({head_count} of {quota})")
    return blockers
