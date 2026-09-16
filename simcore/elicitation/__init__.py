"""`elicitation`: free text to a Likert-5 mass via Semantic Similarity Rating.

Batch-first: `score(responses, construct) -> outcomes`, one per response in request order.
The computation is the paper's (ADR 0026), ported with attribution from the reference
`compute.py` — never a dependency, never `sentence-transformers`."""

from ._compute import aggregate, per_set_distribution, similarities

__all__ = ["aggregate", "per_set_distribution", "similarities"]
