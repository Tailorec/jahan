"""M9 phase 1: the questions that can be asked of a run's record.

`TraceView` is a closed set of five shapes returning frozen models (ADR 0034). The point of the
closed set is that a reader cannot reach past it: no path, no cursor, no frame, no `**kwargs`
filter. The registry pins what a resume must check (ADR 0036) and what a report must quote about
spend it does not know (ADR 0033).
"""

import inspect

import pytest
from pydantic import TypeAdapter, ValidationError

from simcore.ports.trace import RunRegistry, TraceSink, TraceView
from simcore.schemas import (
    BeliefHistory,
    BeliefPoint,
    EventFilter,
    RunRegistryEntry,
    SimBaseModel,
    TraceEdge,
    VerbatimGroup,
    VerbatimGrouping,
    VerbatimRecord,
)
from tests.study_builders import beliefs_payload, partition_run_config, stimulus_id, ulid

READ_SHAPES = ("events", "beliefs", "edges", "verbatims", "resolve")


def test_the_view_names_exactly_five_read_shapes():
    shapes = tuple(name for name in dir(TraceView) if not name.startswith("_"))
    assert sorted(shapes) == sorted(READ_SHAPES)


def test_no_read_shape_returns_storage():
    """A row, a mapping, a frame or a path would reopen the closed set.

    The port keeps its schema imports behind `TYPE_CHECKING`, like every other port, so the
    annotations are read as written rather than resolved.
    """
    rendered = " ".join(
        str(annotation)
        for name in READ_SHAPES
        for annotation in inspect.get_annotations(getattr(TraceView, name)).values()
    ).lower()
    assert rendered, "the read shapes carry no annotations at all"
    for leak in ("dataframe", "path", "cursor", "connection", "dict[", "mapping", "any", "sqlite", "parquet"):
        assert leak not in rendered, f"a read shape exposes {leak}"


def test_no_read_shape_takes_open_keyword_arguments():
    for name in READ_SHAPES:
        signature = inspect.signature(getattr(TraceView, name))
        kinds = {parameter.kind for parameter in signature.parameters.values()}
        assert inspect.Parameter.VAR_KEYWORD not in kinds, f"{name} takes **kwargs, so the set is not closed"
        assert inspect.Parameter.VAR_POSITIONAL not in kinds, f"{name} takes *args"


def test_the_filter_is_a_typed_object_with_a_closed_shape():
    asked = EventFilter(ticks=(2, 5), persona_ids=("p-000001",), kinds=("turn",))
    assert asked.ticks == (2, 5)
    with pytest.raises(ValidationError):
        EventFilter(ticks=(5, 2))  # a range that ends before it starts
    with pytest.raises(ValidationError):
        EventFilter(kinds=("not_a_kind",))
    with pytest.raises(ValidationError):
        EventFilter(persona_ids=("nope",))
    with pytest.raises(ValidationError):
        EventFilter(whatever="open")  # type: ignore[call-arg]


def test_an_empty_filter_asks_for_everything():
    everything = EventFilter()
    assert everything.ticks is None and everything.persona_ids == () and everything.kinds == ()


def test_a_belief_history_is_points_in_tick_order():
    history = BeliefHistory.model_validate(
        {
            "persona_id": "p-000001",
            "points": [
                {"tick": 0, "beliefs": beliefs_payload()},
                {"tick": 3, "beliefs": beliefs_payload(dimensions={"value": 0.7, "fit": 0.4, "trust": 0.7})},
            ],
        }
    )
    assert [point.tick for point in history.points] == [0, 3]
    assert isinstance(history.points[0], BeliefPoint)
    with pytest.raises(ValidationError, match="tick order"):
        BeliefHistory.model_validate(
            {
                "persona_id": "p-000001",
                "points": [
                    {"tick": 3, "beliefs": beliefs_payload()},
                    {"tick": 0, "beliefs": beliefs_payload()},
                ],
            }
        )


def test_an_edge_carries_the_pair_the_channel_and_when_it_last_carried_something():
    edge = TraceEdge.model_validate(
        {"u": "p-000001", "v": "p-000002", "channel": "wom", "count": 3, "last_tick": 7}
    )
    assert edge.count == 3 and edge.last_tick == 7
    with pytest.raises(ValidationError, match="itself"):
        TraceEdge.model_validate({"u": "p-000001", "v": "p-000001", "channel": "wom", "count": 1, "last_tick": 1})
    with pytest.raises(ValidationError):
        TraceEdge.model_validate({"u": "p-000001", "v": "p-000002", "channel": "wom", "count": 0, "last_tick": 1})


def test_a_verbatim_carries_what_was_said_and_what_it_was_about():
    record = VerbatimRecord.model_validate(
        {
            "event_id": f"ev-{ulid(1)}",
            "persona_id": "p-000001",
            "tick": 3,
            "subject_stimulus_id": stimulus_id(1),
            "action": "comment",
            "text": "the protein claim would get me",
        }
    )
    assert record.claim_id is None
    assert "text" in VerbatimRecord.model_fields
    # A verbatim is always resolvable: it names the event it came from.
    assert record.event_id.startswith("ev-")


def test_verbatims_are_grouped_by_a_closed_set_of_keys():
    assert {grouping.value for grouping in VerbatimGrouping} == {"persona", "tick", "subject", "claim"}
    group = VerbatimGroup.model_validate(
        {
            "grouping": "claim",
            "key": "C1",
            "records": [
                {
                    "event_id": f"ev-{ulid(2)}",
                    "persona_id": "p-000001",
                    "tick": 3,
                    "subject_stimulus_id": stimulus_id(1),
                    "action": "comment",
                    "text": "twenty grams is plenty",
                    "claim_id": "C1",
                }
            ],
        }
    )
    assert group.key == "C1" and len(group.records) == 1
    # The same records under the wrong grouping do not belong under that key.
    with pytest.raises(ValidationError, match="grouped by persona"):
        VerbatimGroup.model_validate({**group.model_dump(mode="json"), "grouping": "persona"})
    with pytest.raises(ValidationError, match="grouped by claim"):
        VerbatimGroup.model_validate({**group.model_dump(mode="json"), "key": "C2"})


def test_the_registry_pins_the_engine_and_what_it_does_not_know_about_spend():
    entry = RunRegistryEntry.model_validate(
        {
            "config": partition_run_config(),
            "contract_version": "1.0.0",
            "status": "running",
            "engine_version": "0a35555",
            "recorded_cost": 1.25,
            "discarded_ticks": 2,
        }
    )
    assert entry.engine_version == "0a35555"
    assert entry.recorded_cost == 1.25 and entry.discarded_ticks == 2
    assert RunRegistryEntry.model_validate_json(entry.model_dump_json()) == entry


def test_a_registry_entry_must_say_which_engine_recorded_it():
    payload = {
        "config": partition_run_config(),
        "contract_version": "1.0.0",
        "status": "running",
        "recorded_cost": 0.0,
        "discarded_ticks": 0,
    }
    with pytest.raises(ValidationError):
        RunRegistryEntry.model_validate(payload)


def test_discarded_ticks_are_never_negative_and_default_to_none_lost():
    entry = RunRegistryEntry.model_validate(
        {"config": partition_run_config(), "contract_version": "1.0.0", "status": "running", "engine_version": "abc1234"}
    )
    assert entry.discarded_ticks == 0 and entry.recorded_cost == 0.0
    with pytest.raises(ValidationError):
        RunRegistryEntry.model_validate(
            {"config": partition_run_config(), "contract_version": "1.0.0", "status": "running",
             "engine_version": "abc1234", "discarded_ticks": -1}
        )


def test_the_sink_and_the_registry_are_protocols_a_fake_can_satisfy():
    for protocol, methods in ((TraceSink, ("write", "finalize")), (RunRegistry, ("record", "entry"))):
        for method in methods:
            assert hasattr(protocol, method), f"{protocol.__name__} is missing {method}"
        signature = inspect.signature(getattr(protocol, methods[0]))
        assert inspect.Parameter.VAR_KEYWORD not in {p.kind for p in signature.parameters.values()}


def test_query_models_are_frozen_like_every_other_contract():
    for model in (EventFilter, BeliefHistory, BeliefPoint, TraceEdge, VerbatimRecord, VerbatimGroup):
        assert issubclass(model, SimBaseModel)
        built = TypeAdapter(model)
        assert built is not None
