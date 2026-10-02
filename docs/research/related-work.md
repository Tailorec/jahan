# Related work

Jahan combines four lines of work. What it takes from each, and where it departs:

## Measuring intent without asking for a number

**Semantic similarity rating (SSR)**, Maier et al. (2025)[^ssr], showed that language models asked directly for a
Likert rating give unrealistic distributions, while free-text answers mapped to a scale by embedding similarity
to anchor statements reproduce human purchase-intent distributions. Jahan ports the computation exactly
([details](../concepts/measuring-intent.md)) and adds what a reusable instrument needs: anchors frozen before they
are tested, a rank-stability gate, detection of numeric answers, and the raw similarities kept so ε and
temperature can be changed afterwards.

**Where Jahan departs:** the paper's anchors are not published, so Jahan writes its own and gates them; and
Jahan places SSR inside a social simulation, where the paper elicited one-shot responses.

## Simulating social platforms with language-model agents

**OASIS**, Yang et al. (2024)[^oasis], simulates up to a million agents on X- and Reddit-like platforms, with
recommendation systems, follows, likes and reposts. Jahan's world module is adapted from OASIS (Apache-2.0),
keeping its file structure and the Reddit hot-score and X-refresh ranking verbatim, so upstream fixes can be
diffed in.

**Where Jahan departs:** OASIS agents are generated; Jahan's are sampled from real respondents and graded field by
field. Jahan replaces OASIS's agent framework with its own turn, so every call is pinned, batched, recorded and
replayable, and adds survey waves, word of mouth along a generated network, and a budget.

## Believable agents with memory

**Generative Agents**, Park et al. (2023)[^ga], gave agents a memory stream scored by recency, importance and
relevance, and periodic reflection that consolidates experience. Jahan uses the method (no code) for
[beliefs and memory](../concepts/beliefs-and-memory.md), with importance computed by rule on the cheaper
model, and adds explicit belief dimensions and per-claim credence so a change of mind is measurable.

## Personas grounded in real data

**MatrAIx Persona 1M and Persona-8B**[^matraix] provide a million personas with up to 1,290 attributes drawn from
surveys and text, and a model tuned to role-play them. Jahan uses the corpus's decoding contract and prompt
renderer (MIT), reads the corpus only from a user's own download, and adds evidence tiers so a survey answer, a
model's reading of a biography, and a completed field are never confused.

## Networks and communities

The [social network](../concepts/social-network.md) combines a ring lattice for clustering (Watts and Strogatz
1998), preferential attachment for hubs (Barabási and Albert 1999), and rewiring toward similar people
(homophily; McPherson et al. 2001), and finds communities with Leiden (Traag et al. 2019). Full citations are on
the [references](references.md) page.

## Synthetic respondents in market research

A growing body of work asks whether language models can stand in for survey respondents. Argyle et al.
(2023)[^argyle] found that conditioning a model on respondents' backstories reproduces many subgroup patterns
in political surveys; Santurkar et al. (2023)[^santurkar] found that models' default opinions match some
demographic groups far better than others. Jahan's own holdout found both sides for filled-in attitudes:
differences between groups were largely kept, but the overall level was wrong ([results](results.md#holdout)). Jahan's
position is that this is an empirical question to be answered per instrument, model and category, which is why
it reports a trust level and refuses to raise it without a benchmark.

[^ssr]: B. F. Maier et al. (2025). "LLMs Reproduce Human Purchase Intent via Semantic Similarity Elicitation of
    Likert Ratings." arXiv:2510.08338.
[^oasis]: Z. Yang et al. (2024). "OASIS: Open Agent Social Interaction Simulations with One Million Agents."
    arXiv:2411.11581.
[^ga]: J. S. Park et al. (2023). "Generative Agents: Interactive Simulacra of Human Behavior." *UIST 2023*.
    arXiv:2304.03442.
[^argyle]: L. P. Argyle, E. C. Busby, N. Fulda, J. R. Gubler, C. Rytting, D. Wingate (2023). "Out of One, Many:
    Using Language Models to Simulate Human Samples." *Political Analysis*, 31(3), 337–351.
[^santurkar]: S. Santurkar, E. Durmus, F. Ladhak, C. Lee, P. Liang, T. Hashimoto (2023). "Whose Opinions Do
    Language Models Reflect?" *ICML 2023*. arXiv:2303.17548.
[^matraix]: MatrAIx. *MatrAIx Persona 1M* (Hugging Face `MatrAIx2026/MatrAIx_Persona_1M`) and
    *MatrAIx-Persona-8B* (<https://github.com/MatrAIx-ai/MatrAIx-Persona-8B>).
