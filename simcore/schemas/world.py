"""The world domain: what one world step produces, expressed in the trace's own record types."""

from collections import Counter
from typing import Self

from pydantic import model_validator

from .base import NonNegativeInt, PersonaId, SimBaseModel
from .enums import InterventionKind
from .sim import Presentation, Stimulus
from .trace import ExposureDropped


class DroppedExposure(SimBaseModel):
    """A stimulus that could have reached a persona on a channel this tick, and did not."""

    persona_id: PersonaId
    drop: ExposureDropped


class WorldDelta(SimBaseModel):
    """What one world step produced for its tick: the stimuli it published, the interventions it applied, the
    exposures it dropped, and one presentation for each persona it activated on each channel.

    A delta uses the trace's own record types, so the runner writes it without translation, and it carries
    no event ids or sequence numbers — the runner is the partition's only writer. No world state crosses the
    boundary: the opening delta is the delta for tick zero, and a world resumes by replaying its trace."""

    tick: NonNegativeInt
    published: tuple[Stimulus, ...] = ()
    interventions: tuple[InterventionKind, ...] = ()
    dropped: tuple[DroppedExposure, ...] = ()
    presentations: tuple[Presentation, ...] = ()

    @model_validator(mode="after")
    def _everything_dated_at_its_tick(self) -> Self:
        misdated = sorted(
            [stimulus.stimulus_id for stimulus in self.published if stimulus.tick != self.tick]
            + [p.impression.impression_id for p in self.presentations if p.impression.tick != self.tick]
        )
        if misdated:
            raise ValueError(f"a delta for tick {self.tick} holds records dated at other ticks: {misdated}")
        return self

    @model_validator(mode="after")
    def _each_record_once(self) -> Self:
        stimuli = Counter(stimulus.stimulus_id for stimulus in self.published)
        impressions = Counter(p.impression.impression_id for p in self.presentations)
        repeated = sorted(name for counts in (stimuli, impressions) for name, count in counts.items() if count > 1)
        if repeated:
            raise ValueError(f"a delta records these more than once: {repeated}")
        return self

    @model_validator(mode="after")
    def _one_presentation_per_persona_and_channel(self) -> Self:
        placements = Counter((p.impression.persona_id, p.impression.channel) for p in self.presentations)
        crowded = sorted(f"{persona} on {channel.value}" for (persona, channel), count in placements.items() if count > 1)
        if crowded:
            raise ValueError(f"a persona is presented at most once per channel per tick: {crowded}")
        return self

    @model_validator(mode="after")
    def _dropped_stimuli_are_not_also_shown(self) -> Self:
        drops = Counter((d.persona_id, d.drop.channel, d.drop.stimulus_id) for d in self.dropped)
        if any(count > 1 for count in drops.values()):
            raise ValueError("a delta drops the same stimulus for the same persona and channel more than once")
        shown = {
            (p.impression.persona_id, p.impression.channel, stimulus_id)
            for p in self.presentations
            for stimulus_id in p.impression.stimulus_ids
        }
        both = sorted(f"{stimulus} for {persona}" for persona, _, stimulus in set(drops) & shown)
        if both:
            raise ValueError(f"a stimulus cannot be both dropped and shown on the same channel: {both}")
        return self
