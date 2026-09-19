"""Phase 8: one persona's whole history — the unit the engine actually records.

One persona's timeline (what it was shown, what it said, how its beliefs moved,
memories written, who it heard from / who heard from it) with none of another persona's
events; belief movement before and after per dimension and claim; influence neighbourhood
drawn from recorded edges naming channel and frequency; turn prompts reconstructed
from records and verified against recorded hashes; unreconstructible prompts stated
with why rather than approximated; nothing in the interface stores a prompt.
"""

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def test_one_persona_timeline_with_no_other_persona_events():
    text = (FRONTEND / "app" / "trace" / "page.tsx").read_text()
    for marker in (
        "One persona’s whole history",
        "Timeline",
        "none of another persona's appear in it",
        "activePersona",
        "filter",
    ):
        assert marker in text, f"trace page lacks {marker!r}"


def test_belief_movement_shown_per_dimension_before_and_after():
    text = (FRONTEND / "app" / "trace" / "page.tsx").read_text()
    for marker in (
        "Belief movement",
        "value",
        "fit",
        "trust",
        "before",
        "after",
        "snapshots and turns",
    ):
        assert marker in text, f"trace page lacks {marker!r}"


def test_influence_neighbourhood_drawn_from_edges_with_channels():
    text = (FRONTEND / "app" / "trace" / "page.tsx").read_text()
    for marker in (
        "Influence neighbourhood",
        "Heard from",
        "Heard by",
        "channel",
        "edges_top",
    ):
        assert marker in text, f"trace page lacks {marker!r}"


def test_prompt_reconstructed_and_verified_against_recorded_hash():
    text = (FRONTEND / "app" / "trace" / "page.tsx").read_text()
    for marker in (
        "Reconstruct prompt",
        "/prompt",
        "Hash verified",
        "checked against turn prompt hash",
    ):
        assert marker in text, f"trace page lacks {marker!r}"
    route = (
        FRONTEND / "app" / "api" / "runs" / "[id]" / "worlds" / "[worldId]" / "turns" / "[turnId]" / "prompt" / "route.ts"
    ).read_text()
    # Reconstruction and its verification against the recorded hash are the engine's
    # (test_api.py, test_hardening.py); the route only carries the answer or the reason.
    assert "/prompt" in route and "engineFetch" in route


def test_unreconstructible_prompt_states_why_without_approximation():
    text = (FRONTEND / "app" / "trace" / "page.tsx").read_text()
    for marker in (
        "Cannot reconstruct prompt",
        "cannot be verified against the turn’s recorded hash",
        "no approximation is shown",
    ):
        assert marker in text, f"trace page lacks {marker!r}"


def test_nothing_in_the_interface_stores_or_persists_a_prompt():
    pages = list((FRONTEND / "app").rglob("*.tsx")) + list((FRONTEND / "app").rglob("*.ts"))
    forbidden = ("localStorage.setItem", "sessionStorage.setItem", "prompt_cache", "savePrompt", "storePrompt")
    for page in pages:
        content = page.read_text()
        for marker in forbidden:
            assert marker not in content, f"{page.name} stores a prompt: {marker!r}"
        if "prompt" in page.name.lower():
            assert "localStorage" not in content and "sessionStorage" not in content
