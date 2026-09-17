"""Failures of the record: refused writes, unknown runs, finalized worlds."""

from simcore.schemas.errors import SimError


class TraceError(SimError):
    """A refused trace operation, never a crash."""


class DuplicateSequenceError(TraceError):
    """A `(world_id, seq)` the partition already holds, carrying different content."""


class DuplicateEntryError(TraceError):
    """A registry entry for a run that already has one: refused, never replaced."""


class FinalizedError(TraceError):
    """A write to a finalized world, which is read-only."""


class UnknownRunError(TraceError):
    """A view over, or a write for, a run the registry never recorded."""


class UnknownWorldError(TraceError):
    """A finalization of a world the store never saw."""
