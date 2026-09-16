# Anchor statements are frozen before they are validated, and never tuned on the data that judges them

SSR's output is only as good as its anchor statements, and the paper's are not public. Its authors describe them
— six hand-written sets of five short, generic, domain-independent statements — and report that they were
"manually optimized for the 57 surveys subject to this study": tuned on the data they were then evaluated on.
The reported agreement with human data is partly a fit to its own test set, and it transfers to no other anchors.

The engine writes its own anchors to the paper's description — one domain-independent family per construct, six
sets with deliberately varied wording rather than paraphrases of one set — and freezes them before any validation
runs. An anchor version is immutable JSON identified by its content hash and pinned by the run; a changed statement
is a new version. No anchor, temperature or ε is ever adjusted using data it is evaluated against; a revision is a
new version, judged on data it was not fitted to.

Before a version may be pinned, a check that needs no human data must pass against the real embedding model: a
frozen ladder of responses from certainly-not to certainly-yes scores in increasing order, rank order is stable
across the six sets (Spearman above 0.8), and varied responses do not collapse to one distribution.

## Considered options

Generating anchors with a model and reviewing them was rejected: a model's phrasing habits carry into the anchors,
and embeddings of model-written text sit nearer model-written responses — a bias inside exactly the similarity SSR
measures. Copying anchors from community reimplementations was rejected for unknown provenance and validation.
Tuning anchors on the validation data, as the paper did, was rejected because it makes the validation number
meaningless.

## Consequences

Whatever agreement with human data the engine eventually reports is honest, at the cost of likely being lower than
a tuned figure. Categories share one purchase-intent anchor family; an ontology still names the set it uses, so a
category may override it with its own frozen, checked version later.
