# A population's categorical gates are judged as one family

The distribution gates compare each attribute the ontology declares, as drawn, against the population it was drawn
from. Each categorical attribute was tested with its own chi-squared test at the significance level (0.05), and the
population failed if any one of them did. The categorical gates of one report are now judged as one family: their
p-values are Holm-adjusted, and a gate passes when its adjusted p-value exceeds the level. The level is unchanged and
now bounds the chance that a fair sample fails *any* gate, not each one.

The uncorrected rule held only while ontologies were small. With seven attributes a fair sample failed about 30% of
the time; the first developer study's ontology declares 29, and at that size a fair sample fails at least one gate
about 77% of the time (1 − 0.95²⁹). Its 1,500-persona draw — a simple random sample of Stack Overflow rows — failed
on two attributes at p = 0.017 and p = 0.039, which is what chance produces across 29 tests.

## Considered options

- **Bonferroni** (each test at level / m) holds the same family-wide guarantee but is uniformly more conservative
  than Holm, which is a step-down refinement of it and rejects at least as often when a skew is real.
- **Benjamini–Hochberg** controls the false discovery rate, the expected share of failures that are false. A gate
  is a verdict on one sample, not a screen of many findings, so the guarantee wanted is on any false failure.
- **Redrawing with another seed until a sample passes** was rejected: it selects the draw that passes a test known to
  misfire, and every larger ontology would hit the same wall.
- **Lowering the number of declared attributes** was rejected: what a persona is shown is the study's choice, not
  the gate's.

## Consequences

Each categorical result carries both its raw and its adjusted p-value, so a report shows what was measured and
what decided. Ordinal gates judge a similarity floor rather than a p-value and are unchanged. A real skew still
fails: a raw p-value of one in a million stays far below the level after adjustment. Gate reports written before
this change carry no adjusted value and are judged by their raw p-value as they were. `PopulationParameters` is
unchanged, so no population, world or config hash moves.
