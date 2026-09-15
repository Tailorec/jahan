"""The population module: who is in a study.

`assess` answers "can this study be sampled, and is the sample sound?" with no model and no cost.
`build` answers it and produces the population. Nothing else is public (M3 plan).
"""

from ._assess import assess
from ._build import BuiltPopulation, build
from ._interpret import interpret_audience
from ._preview import PreviewRequest, preview

__all__ = ["BuiltPopulation", "PreviewRequest", "assess", "build", "interpret_audience", "preview"]
