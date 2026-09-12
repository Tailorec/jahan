"""The assumption ledger: what a study takes on faith, gathered from the pack rather than stored.

Reading only the brief's `assumptions:` block hides the claims the brief itself marks assumed and
the structure it left unstated — most importantly an undeclared target market, which means the
whole population was assumed to be the audience. The ledger is derived on demand so it cannot go
stale or disagree with the brief it describes (M2 phase 7)."""

from simcore.schemas import Assumption, BriefPack, ClaimSource


def assumptions_of(pack: BriefPack) -> tuple[Assumption, ...]:
    """Every assumption a study rests on: its stated assumptions, its assumed claims, and what it
    left unstated. Nothing is stored; the result is a pure function of the pack."""
    brief = pack.brief
    ledger = list(brief.assumptions)
    ledger.extend(
        Assumption(text=claim.text, source=ClaimSource.ASSUMED)
        for claim in brief.claims
        if claim.source is ClaimSource.ASSUMED
    )
    if not brief.audiences_declared:
        ledger.append(
            Assumption(
                text=f"Target market assumed to be the whole population: {brief.target_market}",
                source=ClaimSource.ASSUMED,
            )
        )
    return tuple(ledger)
