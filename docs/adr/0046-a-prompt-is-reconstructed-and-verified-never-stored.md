# A prompt is reconstructed and verified, never stored

The trace page shows the exact prompt behind a turn, and the trace deliberately has nowhere to put one:
context is never stored whole, only its parts plus `prompt_hash`. The interface therefore rebuilds the
prompt from what is recorded — the persona block, the stimuli shown, the frozen question and the template
version — and checks the result against the hash the turn carries before displaying it.

## Consequences

A reconstructed prompt that hashes correctly is stronger evidence than a stored copy, which could have been
written by anything at any time. The cost is that reconstruction needs the template source at the version
the run pinned, so an engine at a different commit may not manage it; the page says "cannot reconstruct:
templates moved" rather than showing a plausible approximation. Neither the trace nor the interface gains a
field a whole prompt fits in, which is what kept prompts out of the record in the first place.
