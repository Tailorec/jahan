# Objection clusters are deterministic, and labelled by a verbatim rather than a summary

Objections are grouped by embedding the verbatims through the run's pinned embedding model and clustering by
cosine similarity at a fixed threshold, with ties broken by a derived seed. Nothing here initialises randomly,
so `analysis` run twice over the same trace produces the same clusters — which is what lets a finding cite a
cluster and a reader reproduce it.

A cluster is labelled by its medoid: the verbatim nearest the centre, quoted as the persona wrote it. No model
is asked to name the theme. A generated label is a claim about what a group of people meant, produced by the
same kind of system whose output is under study, and it would sit in a report looking exactly like a measured
finding. A quoted verbatim cannot overstate itself — a reader sees a real sentence and judges the grouping.

## Considered options

k-means was rejected for its random initialisation: two runs over one trace would produce different clusters
and different findings, which makes a report unciteable. Asking a model to name each cluster was rejected as
above; asking one to do the grouping itself was rejected for both reasons at once. Grouping by keyword was
rejected as too brittle across the wording a real model produces — "another black-box tool" and "algorithmic
gatekeeping" are the same objection in different words, which is precisely what embeddings capture.

## Consequences

The clustering threshold is a recorded parameter, not a tuned one: it is stated wherever clusters are reported,
and changing it is a visible change to a study rather than a silent one. Clustering costs one embedding per
verbatim, which is small beside the call that produced the verbatim. A cluster's label is sometimes blunter
than a summary would be, and that is the trade: a reader gets a real sentence rather than a tidy paraphrase
nobody said.
