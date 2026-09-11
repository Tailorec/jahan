# Loading a brief touches no network; evidence is fetched by a separate command into a sidecar

`load_brief(path, ontology_dir)` is a pure function of two files: it reads the brief's YAML, resolves the category ontology by version, joins them into a brief pack, and returns it. It never fetches anything. Evidence is retrieved by a separate command, `fetch_evidence`, which hashes what it received and writes the result to a sidecar file beside the brief — `<brief>.evidence.json`, keyed by URL. The brief itself carries only the URL a claim cites; loading joins the two into the `Evidence` the contract requires, and a cited URL with no sidecar entry is a gate failure.

A study's inputs must be reproducible by anyone holding the files. Fetching at load time would make the brief hash depend on what a web server returned this morning, would make every boundary test either network-dependent or run a different code path from production, and would turn a dead link into a failed run rather than a fixable authoring error. Evidence identity is already the content hash rather than the URL — the contract excludes `fetched_at` from hashing — so the fetch is provenance capture, not part of what a brief *is*.

## Considered options

Fetching at ingest, as the architecture originally specified, keeps a brief to one file and one command. It was rejected because it makes intake non-deterministic and network-bound at exactly the point where reproducibility is established, and because the failure it produces — a URL that resolves differently, or not at all, months later — arrives during a run that is already spending money.

Rewriting the fetched hashes back into the author's YAML keeps the brief a single file. It was rejected because a safe-load/safe-dump cycle destroys the author's comments, key order and formatting, and preserving them means taking on a round-tripping YAML library for the sole purpose of writing a file the module otherwise only reads.

Letting authors write `content_hash` by hand needs no fetching at all, and was rejected as unusable.

## Consequences

A brief is two files, and the sidecar is committed alongside it. Evidence that was never fetched cannot be cited: a claim may carry no evidence, but a claim naming a URL is refused until that URL has been fetched. Re-fetching is explicit, so a changed hash appears as a reviewable diff rather than a silent substitution. Intake needs no port, and the only network code in the module lives behind `EvidencePort`, whose in-memory adapter is what every test runs against.
