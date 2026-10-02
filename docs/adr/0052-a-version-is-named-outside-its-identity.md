# A version is named outside its identity

A run that compares versions — prices, wordings, channel mixes — has worlds named only by derived ids
(`898d5c50c499`), and a variant's `name` is part of the variant itself: one `variant_id` must always carry one name,
so two prices of the same variant cannot be told apart by it. People need to say "Budget $9 · seed 2".

A scenario now carries an optional `label` (1–60 characters). It is presentation: `Scenario` excludes it from its
canonical payload, so it reaches no scenario hash, world id or config hash. Naming a version, or launching the same
grid with different names, makes no different world. A run's summary serves each scenario with its hash and its
name; a rename after launch is recorded beside the run in `labels.json`, keyed by scenario hash, and served over
the launch name. The configuration a run was launched under is never rewritten.

## Considered options

Naming each world (scenario × seed) separately was rejected: replicate seeds are not meant to differ in meaning,
and a world's name is its version's name and its seed. Labels kept only by the interface were rejected: the report
and the command line would still show ids. Putting the name inside the hash was rejected: renaming would make a
"different" world and refuse a resume.
