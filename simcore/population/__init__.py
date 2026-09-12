"""The population module: who is in a study.

`assess` answers "can this study be sampled, and is the sample sound?" with no model and no cost.
`build` answers it and produces the population. Nothing else is public (M3 plan).
"""

from ._assess import assess

__all__ = ["assess"]
