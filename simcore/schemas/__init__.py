"""The engine's contracts: every type crossing a module boundary.

Leaf rule: this package imports nothing from the project, and only pydantic
plus the standard library from outside.
"""

from .base import (
    SCHEMA_VERSION,
    BriefHash,
    ConfigHash,
    GraphHash,
    HashDigest,
    Identifier,
    NonEmptyStr,
    NonNegativeInt,
    PersonaId,
    PopulationHash,
    PositiveInt,
    RunId,
    SignedUnitInterval,
    SimBaseModel,
    StimulusId,
    UnitInterval,
    canonical_hash,
    canonical_json,
    canonical_payload,
)
from .errors import BudgetExhausted, GateFailure, SchemaVersionError, SimError

__all__ = [
    "BudgetExhausted",
    "BriefHash",
    "ConfigHash",
    "GateFailure",
    "GraphHash",
    "HashDigest",
    "Identifier",
    "NonEmptyStr",
    "NonNegativeInt",
    "PersonaId",
    "PopulationHash",
    "PositiveInt",
    "RunId",
    "SCHEMA_VERSION",
    "SchemaVersionError",
    "SignedUnitInterval",
    "SimBaseModel",
    "SimError",
    "StimulusId",
    "UnitInterval",
    "canonical_hash",
    "canonical_json",
    "canonical_payload",
]
