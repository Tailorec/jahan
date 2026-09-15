"""The `CoresetCatalog` protocol: coverage and counts answered from an index, never from rows.

Separate from `CoresetSource` on purpose. A source answers three questions from decoded rows; a catalog
answers two from a per-value index whose cost profile differs by four orders of magnitude and whose
failure mode is different. Typing `preview()` to the catalog is what stops it growing a row read: with a
source in hand it eventually would, and the pre-flight would stop being free.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from simcore.schemas import AttributeFilter, AttributeId, AttributeValue, FieldOrigin, PersonaSource, weakest_origin


@dataclass(frozen=True)
class AttributeCoverage:
    """How one attribute is populated in one source: how many rows exist, how many carry it at all, and
    how many carry it at each tier. A missing attribute and an unasked question are both zeros, so the
    totals travel beside every count rather than being reconstructed from one."""

    total: int
    present: int
    measured: int = 0
    extracted: int = 0
    synthesized: int = 0
    calibrated: int = 0

    @property
    def tier(self) -> FieldOrigin | None:
        """The weakest tier among the rows that carry the attribute, or nothing when nobody does."""
        carried = [
            (tier, count)
            for tier, count in (
                (FieldOrigin.MEASURED, self.measured),
                (FieldOrigin.CALIBRATED, self.calibrated),
                (FieldOrigin.EXTRACTED, self.extracted),
                (FieldOrigin.SYNTHESIZED, self.synthesized),
            )
            if count
        ]
        return weakest_origin(tier for tier, _ in carried) if carried else None


@runtime_checkable
class CoresetCatalog(Protocol):
    """What an index can answer: which sources and attributes exist, their value sets, coverage, and how
    many rows satisfy predicates. It never yields a row, and it never decodes one."""

    def sources(self) -> tuple[PersonaSource, ...]: ...

    def attributes(self) -> tuple[AttributeId, ...]: ...

    def values(self, attribute: AttributeId) -> tuple[AttributeValue, ...]: ...

    def coverage(
        self, attributes: Iterable[AttributeId], sources: Iterable[PersonaSource]
    ) -> Mapping[AttributeId, Mapping[PersonaSource, AttributeCoverage]]: ...

    def count(
        self,
        predicates: Mapping[AttributeId, AttributeFilter],
        present: Iterable[AttributeId],
        *,
        by_source: bool = True,
    ) -> Mapping[PersonaSource, int] | int: ...
