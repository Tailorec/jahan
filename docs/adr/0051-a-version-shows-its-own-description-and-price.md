# A version shows its personas its own description and price

A scenario names the version under test — its variant (name, description, emphasised claims) and its price — and
a sweep runs several to compare them. But the concept a persona was shown was built from the brief's product
description alone. Neither the scenario's variant description nor its price reached any persona, so every version
of a sweep showed one identical concept, and a model at temperature zero answered them identically. The first
price sweep (2026-10-03: $9, $19 and $29 over one population, two seeds) returned the same adoption at every
price to four decimals; only the world ids differed.

The concept a world publishes is now the scenario's variant description followed by its price
("…\nPrice: 19.00 USD"). A study run from one brief has a single version whose description is the brief's, so it
gains only the price line.

## Consequences

Prompts change, so turns recorded before this are not comparable with turns after it, and the replicate-safe
cache does not reuse them. Every earlier study showed no price: results that discussed price sensitivity read a
reaction to something else (the code-review benchmark is corrected). World and config hashes do not move — the
scenario already carried its price and description; only what a persona is shown changes.

Which claims a world posts is unchanged: every brief claim is still posted, whatever a variant emphasises. Making
`emphasized_claims` select the posted claims is a separate decision, not taken here.
