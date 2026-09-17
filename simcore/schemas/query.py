"""What can be asked of a run's record, and the shapes the answers come back in.

`TraceView` is a closed set of five questions (ADR 0034), and these are its vocabulary: the filter
one of them takes, and the frozen models the others return. Nothing here exposes storage — no path,
no cursor, no frame — because a reader that can reach past the set is how derivation leaked into two
consumers in the design this one replaces.
"""

from typing import Annotated, Self

from pydantic import Field, model_validator

from .base import EventId, Identifier, NonEmptyStr, NonNegativeInt, PersonaId, PositiveInt, SimBaseModel, StimulusId
from .run import WorldId
from .brief import ClaimId
from .enums import ActionKind, Channel, VerbatimGrouping
from .sim import Beliefs

# The payload kinds a filter may name; the trace's own discriminated union is the authority on
# what exists, and a filter naming something else is a question about nothing.
EventKind = Annotated[
    str,
    Field(pattern=r"^(stimulus_published|exposure_dropped|turn|guardrail_violation|reflection|memory"
                  r"|belief_snapshot|probe|cost|intervention|degraded|tick_closed|lifecycle)$"),
]


class EventFilter(SimBaseModel):
    """Which events a read is asking for. An empty filter asks for everything.

    A closed object rather than keyword arguments: `**kwargs` would let a caller ask a question the
    module never agreed to answer, which is the same as having no interface.
    """

    # Inclusive tick range, first to last.
    ticks: tuple[NonNegativeInt, NonNegativeInt] | None = None
    persona_ids: tuple[PersonaId, ...] = ()
    kinds: tuple[EventKind, ...] = ()
    # Which worlds of the run to read. A sweep's cells are separate studies of one budget, and
    # a digest names one scenario, so they have to be readable apart.
    world_ids: tuple[WorldId, ...] = ()

    @model_validator(mode="after")
    def _a_range_ends_where_it_starts_or_later(self) -> Self:
        if self.ticks is not None and self.ticks[0] > self.ticks[1]:
            raise ValueError(f"a tick range runs forward: {self.ticks[0]} to {self.ticks[1]}")
        return self


class BeliefPoint(SimBaseModel):
    """What a persona believed at one tick."""

    tick: NonNegativeInt
    beliefs: Beliefs


class BeliefHistory(SimBaseModel):
    """One persona's beliefs over a run, oldest first — derived from snapshots and the turns between."""

    persona_id: PersonaId
    points: tuple[BeliefPoint, ...] = ()

    @model_validator(mode="after")
    def _points_run_forward(self) -> Self:
        ticks = [point.tick for point in self.points]
        if ticks != sorted(ticks):
            raise ValueError(f"a belief history is returned in tick order, got {ticks}")
        if len(set(ticks)) != len(ticks):
            raise ValueError(f"a persona holds one set of beliefs per tick, got {ticks}")
        return self


class TraceEdge(SimBaseModel):
    """How often something travelled between two personas on one channel, and when it last did."""

    u: PersonaId
    v: PersonaId
    channel: Channel
    count: PositiveInt
    last_tick: NonNegativeInt

    @model_validator(mode="after")
    def _an_edge_joins_two_personas(self) -> Self:
        if self.u == self.v:
            raise ValueError("an edge joins two personas, never one to itself")
        return self


class VerbatimRecord(SimBaseModel):
    """Something a persona said, with what it was about and the event it can be resolved back to."""

    event_id: EventId
    persona_id: PersonaId
    tick: NonNegativeInt
    subject_stimulus_id: StimulusId
    action: ActionKind
    text: NonEmptyStr
    claim_id: ClaimId | None = None


class VerbatimGroup(SimBaseModel):
    """Verbatims gathered under one key of the grouping that was asked for."""

    grouping: VerbatimGrouping
    key: Identifier
    records: tuple[VerbatimRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _every_record_belongs_under_this_key(self) -> Self:
        if self.grouping is VerbatimGrouping.PERSONA:
            strangers = sorted({record.persona_id for record in self.records} - {self.key})
            if strangers:
                raise ValueError(f"grouped by persona under {self.key!r}, but holds records of {strangers}")
        if self.grouping is VerbatimGrouping.TICK:
            strangers = sorted({str(record.tick) for record in self.records} - {self.key})
            if strangers:
                raise ValueError(f"grouped by tick under {self.key!r}, but holds records from ticks {strangers}")
        if self.grouping is VerbatimGrouping.SUBJECT:
            strangers = sorted({record.subject_stimulus_id for record in self.records} - {self.key})
            if strangers:
                raise ValueError(f"grouped by subject under {self.key!r}, but holds records about {strangers}")
        if self.grouping is VerbatimGrouping.CLAIM:
            strangers = sorted({record.claim_id for record in self.records if record.claim_id is not None} - {self.key})
            if strangers or any(record.claim_id is None for record in self.records):
                raise ValueError(f"grouped by claim under {self.key!r}, but holds records about {strangers or 'no claim'}")
        return self
