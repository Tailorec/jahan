"""The population module: who is in a study.

`assess` answers "can this study be sampled, and is the sample sound?" with no model and no cost.
`build` answers it and produces the population. Nothing else is public (M3 plan).
"""

from ._assess import assess
from ._audiences import TEXT_LABEL, TEXT_SOURCES, AudienceHeadCount, assumption_entries, preview_audiences
from ._build import BuiltPopulation, build
from ._interpret import interpret_audience
from ._pool import CandidatePool, RequirementCost, alternatives, describe_pool, value_counts
from ._preview import PreviewRequest, preview

__all__ = ["AudienceHeadCount", "BuiltPopulation", "CandidatePool", "PreviewRequest", "RequirementCost", "TEXT_LABEL", "TEXT_SOURCES", "alternatives", "assess", "assumption_entries", "build", "describe_pool", "interpret_audience", "preview", "preview_audiences", "value_counts"]
