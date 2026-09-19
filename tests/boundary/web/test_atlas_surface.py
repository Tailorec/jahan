"""Phase 9: the atlas — a study's shape rather than one persona's.

Adoption against polarization across a scenario's worlds; per-tick trajectories for
audiences and, separately, for communities; replicate spread that says whether an
ordering survives; ranking and risk findings authored by extraction; cells with differing
degradation rungs marked; unmeasured quantities stating their reason where the number
would have been; nothing generated appears as a finding.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_per_tick_trajectories_for_audiences_and_communities_separately():
    text = (FRONTEND / "app" / "atlas" / "page.tsx").read_text()
    for marker in (
        "Per-tick trajectories: Audiences",
        "Per-tick trajectories: Communities",
        "separately presented",
    ):
        assert marker in text, f"atlas lacks {marker!r}"


def test_ranking_and_risk_findings_rendered_with_disconfirming_tests():
    text = (FRONTEND / "app" / "atlas" / "page.tsx").read_text()
    for marker in (
        "Ranking findings",
        "Risk findings",
        "authored by extraction",
        "ordering survives",
        "Disconfirming test:",
    ):
        assert marker in text, f"atlas lacks {marker!r}"


def test_cell_with_different_degradation_rungs_is_marked():
    text = (FRONTEND / "app" / "atlas" / "page.tsx").read_text()
    for marker in (
        "degraded rung",
        "different degradation rungs",
        "marked rather than silently compared",
    ):
        assert marker in text, f"atlas lacks {marker!r}"


def test_unmeasured_quantity_states_reason_never_drawn_as_zero():
    text = (FRONTEND / "app" / "atlas" / "page.tsx").read_text()
    for marker in (
        "unmeasured_reason",
        "polarization_reason",
        "unmeasured:",
    ):
        assert marker in text, f"atlas lacks {marker!r}"
    assert "adoption ?? 0" not in text
    assert "polarization ?? 0" not in text


def test_nothing_generated_appears_as_a_finding():
    """ADR 0041 / PRD M13/M14: 'mitigations (simulated)' or AI advice is banned from findings."""
    text = (FRONTEND / "app" / "atlas" / "page.tsx").read_text()
    forbidden = (
        "mitigation",
        "simulated finding",
        "ai advice",
        "generated finding",
        "generate_finding",
    )
    lowered = text.lower()
    for marker in forbidden:
        assert marker not in lowered, f"atlas renders generated finding marker: {marker!r}"
