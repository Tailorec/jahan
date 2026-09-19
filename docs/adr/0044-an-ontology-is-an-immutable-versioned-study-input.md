# An ontology is an immutable versioned study input, authored against the codebook

The interface lets a study author its own category ontology over the corpus's 1,290 attributes, and the
question is what happens when one is edited. An ontology is hashed into `RunConfig.ontology_hash`, feeds
every world id, and a resume refuses by name when it moves — so saving an edit creates a new version
rather than changing a file that recorded runs still point at. A draft is free to fiddle with and becomes
a version only when a run pins it.

Every attribute a draft names is checked against the dataset codebook before it can be saved. This is the
refusal the engine already learned to make: the first real draw read four shards and died on
`KeyError: 'age'`, because the release spells it `age_bracket`.

## Considered options

Editing in place was rejected because it silently breaks provenance: the reports from Monday's studies
survive, their ontology hash resolves to nothing on disk, and a resume refuses with no way to see what
changed. Snapshotting whatever a run happened to read was rejected because the snapshot has no name, so
two studies that look identical in the interface cannot be told apart afterwards.

## Consequences

Version lists grow under experimentation and will need pruning affordances; a user expecting a document
editor gets a versioned artifact instead, which drafts are there to soften. Authoring is allowed without
the corpus present, but a draft cannot become a pinned version until it validates against a codebook that
is actually there — a doomed study should still cost nothing.

The `conditioning_set` is the most consequential field the interface exposes. Measured over 150 personas
(`docs/evaluations/2026-09-19-conditioning-effect`), conditioning accounts for the entire spread of
answers and almost none of their mean: without it every persona returns the same sentence.
