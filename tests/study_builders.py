"""Builders for valid study payloads, grounded in the representative brief and ontology fixtures.

Each returns plain JSON-shaped data so a test can break exactly one thing and assert the refusal.
"""

import copy
import functools
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ONTOLOGIES = Path(__file__).resolve().parents[1] / "ontologies"
PERSONA_IDS = ["p-000001", "p-000002", "p-000003", "p-000004"]


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def load_ontology(category: str = "beverage_protein", version: str = "1.0.0") -> dict:
    """A shipped category ontology, read from the repository's own ontology directory."""
    return json.loads((ONTOLOGIES / category / f"{version}.json").read_text())


def ontology_payload() -> dict:
    """The shipped ontology, extended with an economic attribute that completion may synthesize."""
    ontology = load_ontology()
    ontology["attribute_domains"]["spend_band"] = "economic"
    ontology["relevance_order"] = [*ontology["relevance_order"], "spend_band"]
    return ontology


def pack_payload(**brief_overrides) -> dict:
    brief = load_fixture("example_brief.json")
    brief.update(brief_overrides)
    return {"brief": brief, "ontology": ontology_payload()}


def beliefs_payload(**overrides) -> dict:
    """Baseline beliefs crediting every claim of the representative brief."""
    payload = {
        "dimensions": {"value": 0.6, "fit": 0.4, "trust": 0.7},
        "claim_credence": {"C1": 0.8, "C2": 0.3, "C3": 0.5},
    }
    payload.update(overrides)
    return payload


TIER_A_FALLBACK = "openrouter/qwen/qwen-2.5-7b-instruct"
TEMPLATE_HASHES = {"persona_turn": "ab" * 32, "reflection": "cd" * 32}
ANCHOR_SET_HASHES = {"pi-beverage-v1": "ef" * 32}


def persona_payload(index: int = 0, **overrides) -> dict:
    payload = {
        "persona_id": PERSONA_IDS[index],
        "source": ["gss", "gss", "amazon", "synthetic"][index],
        "conditioning": {"age": "25_34", "sex": "female", "exercise_frequency": "3_plus_weekly"},
        "attributes": {"diet_protein_focus": "high", "spend_band": "5_10"},
        "origins": {
            "age": "grounded",
            "sex": "grounded",
            "exercise_frequency": "grounded",
            "diet_protein_focus": "grounded",
            "spend_band": "synthesized",
        },
        "embedding": {"model_id": "text-embedding-3-small", "dim": 1536, "index": index},
        "baseline_beliefs": beliefs_payload(),
    }
    payload.update(overrides)
    return payload


def gate_report_payload(**overrides) -> dict:
    payload = {
        "results": [
            {"kind": "ordinal", "attribute": "exercise_frequency", "ks_statistic": 0.1, "ks_similarity": 0.9},
            {"kind": "categorical", "attribute": "age", "chi_square": 3.2, "degrees_of_freedom": 4, "p_value": 0.52},
        ],
        "source_mix": {"gss": 0.5, "amazon": 0.25, "synthetic": 0.25},
    }
    payload.update(overrides)
    return payload


def population_payload(**overrides) -> dict:
    payload = {
        "pack": pack_payload(),
        "manifest": {
            "population_hash": "00" * 32,
            "population_seed": 4021,
            "persona_ids": list(PERSONA_IDS),
            "achieved_mix": {"gym_regulars": 0.5, "protein_dieters": 0.5},
        },
        "personas": [persona_payload(index) for index in range(len(PERSONA_IDS))],
        "gate_report": gate_report_payload(),
        "graph": {
            "edges": [
                {"u": "p-000001", "v": "p-000002", "weight": 0.8},
                {"u": "p-000003", "v": "p-000004", "weight": 0.6},
                {"u": "p-000002", "v": "p-000003", "weight": 0.2},
            ],
        },
        "communities": [
            {"community_id": "community-1", "member_ids": ["p-000001", "p-000002"]},
            {"community_id": "community-2", "member_ids": ["p-000003", "p-000004"]},
        ],
    }
    payload.update(copy.deepcopy(overrides))
    return with_derived_hashes(payload)


def with_derived_hashes(payload: dict) -> dict:
    """State the manifest's population and graph hashes as derived from the payload's own parts, so a test
    that changes one thing is refused for that thing rather than for a stale identity. Parts that do not
    validate on their own are left as they are, and their own refusal surfaces."""
    from pydantic import ValidationError

    from simcore.schemas import BriefPack, Community, Persona, SocialGraph, derive_population_hash

    try:
        pack = BriefPack.model_validate(payload["pack"])
        personas = [Persona.model_validate(persona) for persona in payload["personas"]]
        graph = SocialGraph.model_validate(payload["graph"]) if payload.get("graph") is not None else None
        communities = [Community.model_validate(community) for community in payload.get("communities") or []]
    except (ValidationError, KeyError, TypeError):
        return payload
    manifest = payload["manifest"]
    if manifest.get("population_hash") == "00" * 32:
        manifest["population_hash"] = derive_population_hash(pack, manifest["population_seed"], personas, graph, communities)
    manifest.setdefault("graph_hash", graph.graph_hash if graph is not None else None)
    return payload


@functools.cache
def _representative_manifest() -> str:
    return json.dumps(population_payload()["manifest"])


def population_manifest_payload() -> dict:
    """The representative population's manifest, with its derived hashes."""
    return json.loads(_representative_manifest())


# --- runs, turns and traces ------------------------------------------------------------------

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
POPULATION_HASH = "ab12" * 16


def ulid(n: int) -> str:
    """A valid lowercase ULID body, distinct for each n."""
    digits = []
    for _ in range(26):
        n, remainder = divmod(n, 32)
        digits.append(_CROCKFORD[remainder])
    return "".join(reversed(digits))


def scenario_payload(**overrides) -> dict:
    payload = {
        "variant": {
            "variant_id": "v1baseline",
            "name": "Baseline",
            "description": "Baseline concept at the brief price",
            "emphasized_claims": ["C1"],
        },
        "price": {"amount": 2.49, "currency": "USD"},
        "audience_weights": {"gym_regulars": 0.6, "protein_dieters": 0.4},
        "tick_unit": "day",
        "horizon_ticks": 30,
        "interventions": [{"tick": 3, "kind": "launch"}],
    }
    payload.update(overrides)
    return payload


def run_config_payload(**overrides) -> dict:
    payload = {
        "run_id": f"run-{ulid(1)}",
        "pins": {
            "tier_a": "openrouter/camel-ai/persona-8b",
            "tier_b": "anthropic/claude-sonnet-4-5-20250929",
            "embed": "openai/text-embedding-3-small",
            "fallbacks": {"tier_a": TIER_A_FALLBACK},
        },
        "budget": {"max_cost": 20.0, "currency": "USD"},
        "brief_hash": "aa11" * 16,
        "ontology_hash": "bb22" * 16,
        "population_hash": POPULATION_HASH,
        "scenarios": [scenario_payload()],
        "seeds": [4021, 917731],
        "template_hashes": TEMPLATE_HASHES,
        "anchor_set_hashes": ANCHOR_SET_HASHES,
    }
    payload.update(overrides)
    return payload


def ssr_payload(**overrides) -> dict:
    sets = [
        (0.05, 0.10, 0.20, 0.30, 0.35),
        (0.06, 0.10, 0.19, 0.30, 0.35),
        (0.04, 0.11, 0.20, 0.30, 0.35),
        (0.05, 0.09, 0.21, 0.30, 0.35),
        (0.05, 0.10, 0.20, 0.31, 0.34),
        (0.05, 0.10, 0.20, 0.29, 0.36),
    ]
    payload = {
        "response_text": "I would probably try it after training.",
        "per_set_pmfs": sets,
        "construct_id": "purchase_intent",
        "category": "beverage_protein",
        "anchor_set_id": "pi-beverage-v1",
        "anchor_version": "1.0.0",
        "embed_model_id": "openai/text-embedding-3-small",
        "tau": 0.42,
    }
    payload.update(overrides)
    return payload


def stimulus_id(n: int) -> str:
    return f"st-{ulid(100 + n)}"


def turn_payload(
    persona: str, tick: int, shown: list[tuple[int, str, float]], reaction: dict, contexts: dict | None = None, n: int = 0
) -> dict:
    """A whole turn: the impression (stimulus number, reason, attention), the view beside it, and the
    reaction. Contexts key stimulus numbers and override fields of the default (empty) context."""
    entries = {}
    for stimulus, _, _ in shown:
        entry = {"likes": 0, "reposts": 0, "replies": 0, "upvotes": 0, "downvotes": 0, "ancestry": []}
        entry.update((contexts or {}).get(stimulus, {}))
        entries[stimulus_id(stimulus)] = entry
    return {
        "impression": {
            "impression_id": f"im-{ulid(200 + n)}",
            "persona_id": persona,
            "channel": "social_feed",
            "tick": tick,
            "exposures": [{"stimulus_id": stimulus_id(s), "reason": reason, "attention": attention} for s, reason, attention in shown],
        },
        "view": {"impression_id": f"im-{ulid(200 + n)}", "contexts": entries},
        "reaction": {"reaction_id": f"rc-{ulid(300 + n)}", **reaction},
    }


def world_id_for(scenario: dict | None = None, seed: int = 4021) -> str:
    from simcore.schemas import Scenario, derive_world_id

    population_hash = population_manifest_payload()["population_hash"]
    return derive_world_id(Scenario.model_validate(scenario or scenario_payload()), seed, population_hash)


def partition_run_config(scenario: dict | None = None, **overrides) -> dict:
    """A run configuration pinning exactly what the representative partition carries."""
    from simcore.schemas import BriefPack, canonical_hash

    pack = BriefPack.model_validate(pack_payload())
    manifest = population_manifest_payload()
    config = run_config_payload(
        brief_hash=canonical_hash(pack.brief),
        ontology_hash=canonical_hash(pack.ontology),
        population_hash=manifest["population_hash"],
        graph_hash=manifest["graph_hash"],
        scenarios=[scenario or scenario_payload()],
    )
    config.update(overrides)
    return config


def registry_payload(**overrides) -> dict:
    """A registry entry for the representative run configuration."""
    from simcore.schemas import SCHEMA_VERSION

    payload = {"config": run_config_payload(), "contract_version": SCHEMA_VERSION, "status": "running"}
    payload.update(overrides)
    return payload


def run_result_payload(**overrides) -> dict:
    """A finished run: both worlds of the representative configuration reached their horizon, the second
    after degrading twice."""
    from simcore.schemas import RunRegistryEntry

    registry = registry_payload(status="completed")
    final = scenario_payload()["horizon_ticks"] - 1
    first, second = RunRegistryEntry.model_validate(registry).world_ids
    payload = {
        "registry": registry,
        "outcomes": [
            {"world_id": first, "status": "completed", "last_closed_tick": final},
            {"world_id": second, "status": "completed", "last_closed_tick": final,
             "rungs": ["warn", "freeze_optional_tier_b"]},
        ],
    }
    payload.update(overrides)
    return payload


def event(seq: int, tick: int, payload: dict, persona: str | None = None, world: str | None = None) -> dict:
    return {"event_id": f"ev-{ulid(1000 + seq)}", "world_id": world or world_id_for(), "tick": tick, "seq": seq,
            "persona_id": persona, "payload": payload}


def retried(record: dict, rejected: str = "56" * 32) -> dict:
    """A turn event accepted on its guardrail retry, naming the prompt it rejected."""
    record["payload"]["rejected_prompt_hashes"] = [rejected]
    return record


def turn_event(seq: int, tick: int, turn: dict, persona: str) -> dict:
    return event(seq, tick, {"kind": "turn", "turn": turn, "template_id": "persona_turn",
                             "prompt_hash": "12" * 32, "persona_block_hash": "34" * 32}, persona)


def violation_event(seq: int, tick: int, shown: list[tuple[int, str, float]], persona: str, contexts: dict | None = None, n: int = 0) -> dict:
    """A guardrail violation: what the persona was presented, with no reaction, after both attempts were rejected."""
    presented = turn_payload(persona, tick, shown, {}, contexts, n)
    return event(seq, tick, {"kind": "guardrail_violation", "impression": presented["impression"], "view": presented["view"],
                             "prompt_hashes": ["9a" * 32, "9b" * 32],
                             "rule": "references_unshown_stimulus"}, persona)


def resequence(data: dict) -> dict:
    """Renumber a partition's events by their list order, for tests that insert or remove events."""
    for seq, record in enumerate(data["events"]):
        record["seq"] = seq
        record["event_id"] = f"ev-{ulid(1000 + seq)}"
    return data


def partition_header_payload(scenario: dict | None = None, persona_ids: list[str] | None = None) -> dict:
    """A header whose run configuration pins exactly the pack, population and scenario it carries. Given persona
    ids, it describes a stand-in population of those personas instead of the representative one."""
    scenario = scenario or scenario_payload()
    manifest = population_manifest_payload()
    if persona_ids is not None:
        manifest = {**manifest, "persona_ids": list(persona_ids), "population_hash": "99" * 32, "graph_hash": None}
    config = partition_run_config(scenario, population_hash=manifest["population_hash"], graph_hash=manifest["graph_hash"])
    return {"contract_version": "1.0.0", "config": config, "pack": pack_payload(), "population": manifest,
            "scenario": scenario, "replicate_seed": 4021}


# Events of the representative partition, in sequence order. Tests address them by role, so inserting an
# event changes this list and nothing else.
PARTITION_ROLES = (
    "started",
    "concept",
    "claim_post",
    "close_0",
    "first_turn",
    "first_turn_cost",
    "drop",
    "close_1",
    "peer_post",
    "peer_reply",
    "close_2",
    "warned",
    "launch",
    "reflection",
    "second_turn",
    "second_turn_cost",
    "close_3",
    "third_turn",
    "violation",
    "close_4",
    "completed",
)
R = {name: seq for seq, name in enumerate(PARTITION_ROLES)}


def partition_payload(**header_overrides) -> dict:
    """A small but complete world: study stimuli, whole turns, a drop, a reply thread, an intervention,
    a reflection and lifecycle bookends — every reference resolving within the partition."""
    events = [
        event(R["started"], 0, {"kind": "lifecycle", "phase": "started"}),
        event(R["concept"], 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(1), "tick": 0, "kind": "concept", "text": "Clear protein water"}}),
        event(R["claim_post"], 0, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(2), "tick": 0, "kind": "claim_post", "text": "20g protein, zero sugar", "claim_id": "C1"}}),
        event(R["close_0"], 0, {"kind": "tick_closed"}),
        # The first turn was accepted on its guardrail retry.
        retried(turn_event(R["first_turn"], 1, turn_payload("p-000001", 1, [(1, "interest", 0.8), (2, "social_proof", 0.0)], {
            "subject_stimulus_id": stimulus_id(1), "action": "comment", "verbatim": "the protein claim would get me",
            "belief_change": {"dimensions": {"value": 0.1}, "claim_credence": {"C1": 0.2}}, "intent": ssr_payload()}, n=1), "p-000001")),
        event(R["first_turn_cost"], 1, {"kind": "cost", "role": "tier_b", "model_id": "anthropic/claude-sonnet-4-5-20250929",
                     "route": "primary", "input_tokens": 812, "output_tokens": 96, "cost": 0.004}, "p-000001"),
        event(R["drop"], 1, {"kind": "exposure_dropped", "stimulus_id": stimulus_id(2), "channel": "social_feed", "reason": "budget_exhausted"}, "p-000002"),
        event(R["close_1"], 1, {"kind": "tick_closed"}),
        event(R["peer_post"], 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(3), "tick": 2, "author": "p-000001", "kind": "peer_post", "text": "tried it after the gym"}}),
        event(R["peer_reply"], 2, {"kind": "stimulus_published", "stimulus": {"stimulus_id": stimulus_id(4), "tick": 2, "author": "p-000002", "kind": "peer_reply", "text": "how was the taste?", "in_reply_to": stimulus_id(3)}}),
        event(R["close_2"], 2, {"kind": "tick_closed"}),
        event(R["warned"], 3, {"kind": "degraded", "rung": "warn", "activation_rate": 0.62, "tier_b_frozen": False}),
        event(R["launch"], 3, {"kind": "intervention", "intervention_kind": "launch"}),
        event(R["reflection"], 3, {"kind": "reflection", "trigger": "tick_cadence", "change": {"claim_credence": {"C2": -0.1}}}, "p-000001"),
        # Views count only engagement from earlier ticks: st4's reply (tick 2) is visible here, and this
        # turn's like is visible to the third turn. Ties follow the representative graph and communities.
        turn_event(R["second_turn"], 3, turn_payload("p-000002", 3, [(3, "wom", 0.6), (4, "forum", 0.4)], {
            "subject_stimulus_id": stimulus_id(3), "action": "like"},
            contexts={3: {"replies": 1, "tie_strength": 0.8, "shared_community": True}, 4: {"ancestry": [stimulus_id(3)]}},
            n=2), "p-000002"),
        # The second turn was served by tier A's pinned fallback.
        event(R["second_turn_cost"], 3, {"kind": "cost", "role": "tier_a", "model_id": TIER_A_FALLBACK,
                                         "route": "fallback", "input_tokens": 540, "output_tokens": 41, "cost": 0.0002}, "p-000002"),
        event(R["close_3"], 3, {"kind": "tick_closed"}),
        turn_event(R["third_turn"], 4, turn_payload("p-000003", 4, [(3, "wom", 0.5), (4, "forum", 0.3)], {
            "subject_stimulus_id": stimulus_id(4), "action": "upvote"},
            contexts={3: {"likes": 1, "replies": 1, "tie_strength": 0.0, "shared_community": False},
                      4: {"ancestry": [stimulus_id(3)], "tie_strength": 0.2, "shared_community": False}},
            n=3), "p-000003"),
        # The fourth persona's response referred to something it was never shown, twice, so it did not react.
        # Its view is verified like a turn's: the third turn's upvote, from this same tick, is not yet visible.
        violation_event(R["violation"], 4, [(3, "wom", 0.4), (4, "forum", 0.4)], "p-000004",
                        contexts={3: {"likes": 1, "replies": 1, "tie_strength": 0.0, "shared_community": False},
                                  4: {"ancestry": [stimulus_id(3)], "tie_strength": 0.0, "shared_community": False}},
                        n=5),
        event(R["close_4"], 4, {"kind": "tick_closed"}),
        event(R["completed"], 4, {"kind": "lifecycle", "phase": "completed"}),
    ]
    header = partition_header_payload(header_overrides.get("scenario"))
    header.update(header_overrides)
    return {"header": header, "events": events}


def digest_payload(scenario: dict | None = None, **overrides) -> dict:
    from simcore.schemas import Scenario, canonical_hash

    payload = {
        "scenario_hash": canonical_hash(Scenario.model_validate(scenario or scenario_payload())),
        "tick_unit": "day",
        "audience_pmfs": {"gym_regulars": (0.05, 0.10, 0.20, 0.30, 0.35), "protein_dieters": (0.10, 0.20, 0.30, 0.25, 0.15)},
        "audience_shares": {"gym_regulars": 0.6, "protein_dieters": 0.4},
        "community_pmfs": {"community-1": (0.04, 0.10, 0.21, 0.30, 0.35), "community-2": (0.30, 0.25, 0.20, 0.15, 0.10)},
        "community_sizes": {"community-1": 120, "community-2": 80},
    }
    payload.update(overrides)
    return payload


def events_of_representative_cost() -> dict:
    """The representative partition's first billed call."""
    return copy.deepcopy(partition_payload()["events"][R["first_turn_cost"]]["payload"])
