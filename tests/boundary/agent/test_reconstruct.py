"""Phase 8: a turn's prompt, reconstructed from the record and verified.

The persona block re-renders from the population's own records, beliefs replay
from snapshots and turns, memories resolve by id, shown stimuli resolve by
published text — and the messages display only when their hash matches the
turn's recorded hash. Anything else says so and why.
"""

import json
from pathlib import Path

from simcore.agent import ReconstructedPrompt, Unreconstructible, reconstruct_turn
from simcore.agent._prompt import prompt_hash
from simcore.schemas import CategoryOntology, EventFilter, Persona
from simcore.trace import TraceStore


def _fake_run(tmp_path, monkeypatch, run_id="run-" + "0" * 24 + "78"):
    from tests.boundary.cli.support import fake_args, run_command

    monkeypatch.chdir(tmp_path)
    out = tmp_path / "runs"
    code, output = run_command(*fake_args(out, run_id, horizon=2))
    assert code == 0, output
    return out / run_id


def _materials(run_dir: Path, run_id: str, persona_id: str):
    store = TraceStore(run_dir / "trace")
    view = store.view(run_id)
    personas = {
        record["persona_id"]: Persona.model_validate(record)
        for record in json.loads((run_dir / "personas.json").read_text())["personas"]
    }
    ontology = CategoryOntology.model_validate(json.loads((run_dir / "ontology.json").read_text()))
    persona_events = view.events(EventFilter(persona_ids=(persona_id,)))
    texts = {}
    for event in view.events(EventFilter(kinds=("stimulus_published",))):
        texts[event.payload.stimulus.stimulus_id] = event.payload.stimulus.text
    return store, view, personas[persona_id], ontology, persona_events, texts


def test_a_real_turn_reconstructs_and_matches_its_recorded_hash(tmp_path, monkeypatch):
    run_dir = _fake_run(tmp_path, monkeypatch)
    run_id = run_dir.name
    store = TraceStore(run_dir / "trace")
    view = store.view(run_id)
    turn = next(
        event for event in view.events(EventFilter(kinds=("turn",)))
        if event.persona_id is not None
    )
    _, _, persona, ontology, persona_events, texts = _materials(run_dir, run_id, turn.persona_id)
    rebuilt = reconstruct_turn(
        turn.payload, turn, persona=persona, ontology=ontology,
        persona_events=persona_events, stimulus_texts=texts,
    )
    assert isinstance(rebuilt, ReconstructedPrompt), rebuilt
    assert prompt_hash([dict(message) for message in rebuilt.messages]) == turn.payload.prompt_hash


def test_a_tampered_hash_is_never_shown(tmp_path, monkeypatch):
    run_dir = _fake_run(tmp_path, monkeypatch)
    run_id = run_dir.name
    store = TraceStore(run_dir / "trace")
    view = store.view(run_id)
    turn = next(
        event for event in view.events(EventFilter(kinds=("turn",)))
        if event.persona_id is not None
    )
    _, _, persona, ontology, persona_events, texts = _materials(run_dir, run_id, turn.persona_id)
    tampered = turn.payload.model_copy(update={"prompt_hash": "00" * 32})
    rebuilt = reconstruct_turn(
        tampered, turn, persona=persona, ontology=ontology,
        persona_events=persona_events, stimulus_texts=texts,
    )
    assert isinstance(rebuilt, Unreconstructible)
    assert "hash" in rebuilt.reason


def test_a_moved_persona_is_named_not_approximated(tmp_path, monkeypatch):
    run_dir = _fake_run(tmp_path, monkeypatch)
    run_id = run_dir.name
    store = TraceStore(run_dir / "trace")
    view = store.view(run_id)
    turn = next(
        event for event in view.events(EventFilter(kinds=("turn",)))
        if event.persona_id is not None
    )
    _, _, persona, ontology, persona_events, texts = _materials(run_dir, run_id, turn.persona_id)
    first_attr = next(iter(persona.attributes))
    moved = persona.model_copy(update={
        "attributes": {**dict(persona.attributes), first_attr: "moved-value"},
    })
    rebuilt = reconstruct_turn(
        turn.payload, turn, persona=moved, ontology=ontology,
        persona_events=persona_events, stimulus_texts=texts,
    )
    assert isinstance(rebuilt, Unreconstructible)
    assert "block" in rebuilt.reason


def test_a_missing_memory_or_stimulus_says_so_and_why(tmp_path, monkeypatch):
    run_dir = _fake_run(tmp_path, monkeypatch)
    run_id = run_dir.name
    store = TraceStore(run_dir / "trace")
    view = store.view(run_id)
    turn = next(
        event for event in view.events(EventFilter(kinds=("turn",)))
        if event.persona_id is not None
    )
    _, _, persona, ontology, persona_events, texts = _materials(run_dir, run_id, turn.persona_id)
    # A recalled id with no memory behind it is reported, not guessed.
    assert isinstance(reconstruct_turn(
        turn.payload.model_copy(update={"memory_ids": ("me-" + "0" * 25 + "1",)}),
        turn, persona=persona, ontology=ontology,
        persona_events=persona_events, stimulus_texts=texts,
    ), Unreconstructible)
    assert isinstance(reconstruct_turn(
        turn.payload, turn, persona=persona, ontology=ontology,
        persona_events=persona_events, stimulus_texts={},
    ), Unreconstructible)
