# Elicitation computes the published SSR formula, not a softmax over cosines

Semantic Similarity Rating turns a persona's free-text answer into a distribution over a five-point scale by
comparing its embedding with anchor statements for each point. The architecture specified that comparison as
`softmax(cosine / τ)` inside each anchor set, averaged across sets. The method's own implementation
(`pymc-labs/semantic-similarity-rating`, Apache-2.0, from the authors of arXiv 2510.08338) computes something
else, and it is that computation the paper validated:

1. similarity to each anchor, `γ = (1 + cosine) / 2`;
2. per anchor set, subtract the least similar anchor's similarity and normalise:
   `p_i = (γ_i − γ_min + ε·[i is the least similar]) / (Σγ − 5·γ_min + ε)`;
3. average the per-set distributions across sets;
4. then apply temperature once, `p^(1/T)`, renormalised.

The engine computes exactly this, with ε and T as recorded study parameters defaulting to the paper's ε = 0 and
T = 1. The computation is ported from the reference `compute.py` with attribution and checked against its
known-answer tests, not taken as a dependency: the package runs its own `sentence-transformers` model, which
would bypass the single pinned embedding endpoint (ADR 0021).

## Considered options

Keeping the softmax was rejected: embedding cosines bunch within a few hundredths of each other, so a softmax is
nearly flat unless τ is tiny and then sensitive to it, while subtracting the minimum stretches those gaps first —
and whatever its merits, it is not the method whose results the engine would cite. Depending on the reference
package was rejected for the embedding bypass above.

## Consequences

The paper's evidence attaches to the computation, not to the name; computing it exactly is the precondition for
citing it at all, and it is not sufficient, because the anchors and embedding model differ (ADR 0027, ADR 0028).
With ε = 0 the least similar anchor receives exactly zero within each set, which averaging over at least six sets
softens. `SsrResult` renames `tau` to `temperature`, gains `epsilon`, records each set's raw similarity vector so a
change of ε or T is arithmetic on the trace rather than a re-embedding, and computes its headline distribution as
temperature applied to the mean of the per-set distributions.
