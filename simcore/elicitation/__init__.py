"""`elicitation`: free text to a Likert-5 mass via Semantic Similarity Rating.

Batch-first: `score(responses, construct) -> outcomes`, one per response in request order.
The computation is the paper's (ADR 0026), ported with attribution from the reference
`compute.py` — never a dependency, never `sentence-transformers`."""

from ._anchors import AnchorVersion, anchor_hash, anchor_path, load_anchor_version, resolve_anchors
from ._compute import aggregate, per_set_distribution, similarities
from ._question import is_numeric_answer, question_hash, question_text, question_version
from ._score import DEFAULT_CHUNK_SIZE, clear_anchor_cache, rescore_from_similarities, score

__all__ = [
    "AnchorVersion",
    "DEFAULT_CHUNK_SIZE",
    "aggregate",
    "anchor_hash",
    "anchor_path",
    "clear_anchor_cache",
    "is_numeric_answer",
    "load_anchor_version",
    "per_set_distribution",
    "question_hash",
    "question_text",
    "question_version",
    "rescore_from_similarities",
    "resolve_anchors",
    "score",
    "similarities",
]
