"""The `PersonaPatchSource` seam: externally-derived corrections applied to projected personas.

No adapter in this repository derives a correction yet, but the signature is published here because
adding the parameter later would break every caller. The null adapter is the shipped default, so the
common path applies a seam and changes nothing."""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from simcore.schemas import AttributeId, AttributeValue, Persona, PersonaId


@runtime_checkable
class PersonaPatchSource(Protocol):
    def patches(self, personas: Sequence[Persona]) -> Mapping[PersonaId, Mapping[AttributeId, AttributeValue]]: ...


class NullPatchSource:
    """Corrects nothing: the default seam that keeps the build signature stable until patches exist."""

    def patches(self, personas: Sequence[Persona]) -> Mapping[PersonaId, Mapping[AttributeId, AttributeValue]]:
        return {}
