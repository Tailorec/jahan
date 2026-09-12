# Category ontologies and audiences are drafted from the corpus and confirmed by a person

A study's two hardest inputs — the category ontology it is read against, and the audiences it samples — are drafted by a model from the corpus's own codebook, shown to the author with the numbers that make the choice real, and committed only once a person approves them. The approved artifact is what the engine reads: an ontology file under its category and version, and audiences written into the brief as explicit filters. No model resolves either at build time.

Hand-authoring them is not a workflow. It asks a study author to know a vocabulary they cannot inspect — 1,290 attributes whose names, value sets and populated counts live inside a packed dataset — and to guess a conditioning set whose cost in eligible rows is invisible until a population is built. The first ontology in this repository declares four attributes because it began life as a test fixture, which is the clearest evidence available that nobody hand-authors these well.

Resolving them at run time instead, from natural language, would remove the friction and the auditability together: the sampling frame would become a prompt, and "who was in this study" would stop being answerable from the files.

## Considered options

Hand-authored ontologies and filters are what the architecture originally assumed. They remain supported — `ontology_dir` is a parameter, so an organisation can maintain its own library — but as the only path they put the engine's expressiveness behind a wall of unreadable vocabulary.

Model-resolved audiences, where a description like "urban adults who train regularly" is turned into rows during `build()`, were rejected. The selection criteria would be unrecorded, two builds could disagree, and the population hash would pin a sampling frame nobody can read.

## Consequences

Drafting is grounded: the model selects from the codebook's real attributes and values and may not invent names, because an invented attribute matches no rows and fails silently. Review shows the eligible-row count for each conditioning choice, since that is the decision that most affects a population and the one an author cannot intuit. Field domains default conservatively — anything uncertain is assigned a domain that is never synthesized — because a misclassification in the other direction lets a model fabricate exactly the fields the engine promises never to fabricate.

Comparability survives: where an ontology already exists for a category it is reused, and a drafted change publishes a new version with a diff rather than mutating what earlier studies pinned (ADR 0004). Each ontology records which model drafted it, from which codebook, and when — hash-excluded, like evidence's fetch time, so provenance never moves an ontology's identity.

Drafting is blocked until the corpus codebook can be read, which requires the packed decoder and real shards. Until then, ontologies are hand-authored and the engine's audience vocabulary stays as narrow as whatever has been declared by hand.
