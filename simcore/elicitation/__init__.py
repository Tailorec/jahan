"""`elicitation`: free text to a Likert-5 mass via Semantic Similarity Rating.

Batch-first: `score(responses, construct) -> outcomes`, one per response in request order.
The computation is the paper's (ADR 0026), ported with attribution from the reference
`compute.py` — never a dependency, never `sentence-transformers`."""

from ._anchors import AnchorVersion, anchor_hash, anchor_path, load_anchor_version, resolve_anchors
from ._check import (
    LADDER,
    VARIED,
    AnchorCheckResult,
    assert_pinnable,
    check_anchors,
    check_record_path,
    expected_rating,
    ladder_for,
    read_check_record,
    spearman,
    varied_for,
)
from ._compute import aggregate, per_set_distribution, similarities
from ._question import is_numeric_answer, question_hash, question_text, question_version
from ._score import DEFAULT_CHUNK_SIZE, clear_anchor_cache, rescore_from_similarities, score
from ._validate import reviews_from_jsonl, synthetic_reviews, validate_mapping

__all__ = [
    "AnchorVersion",
    "AnchorCheckResult",
    "DEFAULT_CHUNK_SIZE",
    "LADDER",
    "VARIED",
    "aggregate",
    "anchor_hash",
    "anchor_path",
    "assert_pinnable",
    "check_anchors",
    "check_record_path",
    "clear_anchor_cache",
    "expected_rating",
    "is_numeric_answer",
    "ladder_for",
    "load_anchor_version",
    "per_set_distribution",
    "question_hash",
    "question_text",
    "question_version",
    "read_check_record",
    "rescore_from_similarities",
    "resolve_anchors",
    "reviews_from_jsonl",
    "score",
    "similarities",
    "spearman",
    "synthetic_reviews",
    "validate_mapping",
    "varied_for",
]
