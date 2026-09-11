"""The brief domain: turning an authored study into the structures the engine consumes.

Loading is a pure function of two files — the brief and the category ontology it names —
so the same files always produce the same study, and therefore the same brief hash, on any
machine. Nothing here opens a socket or reads a clock (ADR 0013).
"""

from ._intake import load_brief

__all__ = ["load_brief"]
