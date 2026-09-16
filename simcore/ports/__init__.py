"""Ports: the seams through which the engine reaches the outside world.

A port is a protocol; its adapters live beside it, one production and one in-memory that every
boundary test runs against. Core modules import the protocol only, so no core module can reach a
concrete adapter (FINAL_ARCH §4).
"""

from .catalog import AttributeCoverage, CoresetCatalog
from .chat import ChatPort
from .coreset import CoresetSource
from .embed import EmbedPort
from .evidence import EvidencePort
from .index_catalog import IndexCoresetCatalog, cached_hf_index, from_hf_source, from_source
from .patch import NullPatchSource, PersonaPatchSource

__all__ = [
    "AttributeCoverage",
    "ChatPort",
    "CoresetCatalog",
    "CoresetSource",
    "EmbedPort",
    "EvidencePort",
    "IndexCoresetCatalog",
    "NullPatchSource",
    "PersonaPatchSource",
    "cached_hf_index",
    "from_hf_source",
    "from_source",
]
