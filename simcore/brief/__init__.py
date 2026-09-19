"""The brief domain: turning an authored study into the structures the engine consumes.

Loading is a pure function of two files — the brief and the category ontology it names —
so the same files always produce the same study, and therefore the same brief hash, on any
machine. Nothing here opens a socket or reads a clock (ADR 0013).
"""

from ._codebook import suggest_attributes, validate_against_codebook
from ._fetch import fetch_evidence
from ._intake import load_brief
from ._ledger import assumptions_of

__all__ = ["assumptions_of", "fetch_evidence", "load_brief", "suggest_attributes", "validate_against_codebook"]
