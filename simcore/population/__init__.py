"""The population module: who is in a study.

`assess` answers "can this study be sampled, and is the sample sound?" with no model and no cost.
`build` answers it and produces the population. Nothing else is public (M3 plan).
"""

from ._assess import assess
from ._audience_sets import list_audience_sets, load_audience_set, save_audience_set
from ._audiences import TEXT_LABEL, TEXT_SOURCES, AudienceHeadCount, assumption_entries, preview_audiences
from ._build import BuiltPopulation, build
from ._describe import Group, Reading, describe, list_categories, match_category, read_description, sanitise
from ._draft import Draft, DraftQuestion, apply_followup, cross_survey_core, draft, resolve, settle
from ._fit import continue_blockers, fit_to_quotas
from ._launch import prepare_launch
from ._search import search_attributes
from ._interpret import interpret_audience
from ._pool import CandidatePool, RequirementCost, alternatives, describe_pool, value_counts
from ._preview import PreviewRequest, preview

__all__ = ["AudienceHeadCount", "BuiltPopulation", "CandidatePool", "Draft", "DraftQuestion", "Group", "PreviewRequest", "Reading", "RequirementCost", "TEXT_LABEL", "TEXT_SOURCES", "alternatives", "assess", "assumption_entries", "apply_followup", "build", "continue_blockers", "cross_survey_core", "describe", "describe_pool", "draft", "fit_to_quotas", "interpret_audience", "list_audience_sets", "list_categories", "load_audience_set", "match_category", "prepare_launch", "preview", "preview_audiences", "read_description", "resolve", "sanitise", "save_audience_set", "search_attributes", "settle", "value_counts"]
