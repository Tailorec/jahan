# The interface is a single-operator local application

The mockups describe a hosted product — a workspace, a spend budget, reports shipped to customers — and
ADR 0016 rules that out on this corpus: a brand running a study is commercial use, which
`matraix-research-only` does not permit and whose upstream rights its authors say are not theirs to grant.
The interface therefore ships with the engine and is run by the person who downloaded the corpus and
accepted its terms. There are no accounts, no tenancy and no quotas, and the API key it uses is the
operator's own, set in the server's environment.

## Considered options

A hosted service on Persona 1M was rejected as the thing ADR 0016 already rejected, with the added
problem that it takes the corpus's terms away from the person bound by them. A hosted service on a
different corpus stays open — the engine reaches any corpus through `CoresetSource`, and ADR 0016
anticipates it — but it is a different product, and the grounding claim travels with the corpus rather
than with the engine.

## Consequences

Everything the mockups show still works, addressed to one person: the workspace is the operator's, the
spend is their own bill, and "reports shipped" counts their own studies. Nothing in the interface needs
authentication, which removes a whole category of work and a whole category of mistake. If this ever
becomes a business, the honest sequence is to swap the corpus first and amend ADR 0016 deliberately,
rather than to contradict it quietly by adding a login screen.
