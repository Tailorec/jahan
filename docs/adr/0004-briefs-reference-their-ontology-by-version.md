# Briefs reference their category ontology by version rather than embedding it

A brief names the ontology version it is read against, takes its category from the product, and is joined with that ontology into a brief pack whose validation refuses any mismatch. The ontology is a shared artifact owned per category — because when every brief carried its own inline copy, two briefs could both claim the same category and version with different conditioning sets and nothing noticed, turning the conditioning set from a per-category invariant into per-study input.

## Considered options

Embedding the ontology keeps each brief self-contained and was the first implementation. It was rejected because `(category, version)` stopped identifying an ontology's content. Embedding a content hash alongside the version was also considered; it catches drift but still lets study authors hand-edit the attributes a study conditions on.

## Consequences

Editing an ontology moves the ontology's hash, not any brief's, so drift is caught where replay is checked: the run configuration pins the ontology hash alongside the brief hash. Audience filters are checked against the ontology at pack time — an undeclared attribute, or a value outside an ordinal attribute's bands, is refused.
