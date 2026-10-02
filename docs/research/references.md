# References

Every paper, dataset and codebase the documentation cites, with where it is used.

## Methods Jahan implements

| Reference | Used for | Page |
|---|---|---|
| B. F. Maier et al. (2025). "LLMs Reproduce Human Purchase Intent via Semantic Similarity Elicitation of Likert Ratings." arXiv:[2510.08338](https://arxiv.org/abs/2510.08338). Code: [pymc-labs/semantic-similarity-rating](https://github.com/pymc-labs/semantic-similarity-rating) (Apache-2.0) | SSR: free text to a five-point distribution | [Measuring intent](../concepts/measuring-intent.md) |
| J. S. Park, J. C. O'Brien, C. J. Cai, M. R. Morris, P. Liang, M. S. Bernstein (2023). "Generative Agents: Interactive Simulacra of Human Behavior." *UIST 2023*. arXiv:[2304.03442](https://arxiv.org/abs/2304.03442) | memory retrieval, importance, reflection | [Beliefs and memory](../concepts/beliefs-and-memory.md) |
| Z. Yang et al. (2024). "OASIS: Open Agent Social Interaction Simulations with One Million Agents." arXiv:[2411.11581](https://arxiv.org/abs/2411.11581). Code: [camel-ai/oasis](https://github.com/camel-ai/oasis) (Apache-2.0) | platforms, X refresh, Reddit hot score, clock | [Channels](../concepts/channels.md) |
| X. Zhang et al. (2023). "TwHIN-BERT: A Socially-Enriched Pre-trained Language Model for Multilingual Tweet Representations at Twitter." *KDD 2023*. arXiv:[2209.07562](https://arxiv.org/abs/2209.07562) | feed ranking embeddings | [Channels](../concepts/channels.md) |
| V. A. Traag, L. Waltman, N. J. van Eck (2019). "From Louvain to Leiden: guaranteeing well-connected communities." *Scientific Reports*, 9, 5233 | community detection | [Social network](../concepts/social-network.md) |

## Synthetic respondents

| Reference | Used for |
|---|---|
| L. P. Argyle et al. (2023). "Out of One, Many: Using Language Models to Simulate Human Samples." *Political Analysis*, 31(3), 337–351 | context: conditioning models on respondents |
| S. Santurkar et al. (2023). "Whose Opinions Do Language Models Reflect?" *ICML 2023*. arXiv:[2303.17548](https://arxiv.org/abs/2303.17548) | context: whose views a model holds by default |

## Networks

| Reference | Used for |
|---|---|
| D. J. Watts, S. H. Strogatz (1998). "Collective dynamics of 'small-world' networks." *Nature*, 393, 440–442 | ring lattice: clustering |
| A.-L. Barabási, R. Albert (1999). "Emergence of scaling in random networks." *Science*, 286(5439), 509–512 | preferential attachment: hubs |
| M. McPherson, L. Smith-Lovin, J. M. Cook (2001). "Birds of a feather: homophily in social networks." *Annual Review of Sociology*, 27, 415–444 | homophily rewiring |
| M. E. J. Newman, M. Girvan (2004). "Finding and evaluating community structure in networks." *Physical Review E*, 69, 026113 | modularity |
| J. Reichardt, S. Bornholdt (2006). "Statistical mechanics of community detection." *Physical Review E*, 74, 016110 | the resolution parameter γ |
| M. E. J. Newman (2003). "Mixing patterns in networks." *Physical Review E*, 67, 026126 | attribute assortativity |

## Statistics

| Reference | Used for |
|---|---|
| K. Pearson (1900). "On the criterion that a given system of deviations…" *Philosophical Magazine*, 50(302), 157–175 | χ² distribution gates |
| S. Holm (1979). "A simple sequentially rejective multiple test procedure." *Scandinavian Journal of Statistics*, 6(2), 65–70 | correcting many gates at once |
| A. Kolmogorov (1933); N. Smirnov (1948). *Annals of Mathematical Statistics*, 19(2), 279–281 | KS similarity on ordinal gates |
| C. Spearman (1904). "The proof and measurement of association between two things." *American Journal of Psychology*, 15(1), 72–101 | anchor rank stability |
| J. Lin (1991). "Divergence measures based on the Shannon entropy." *IEEE Transactions on Information Theory*, 37(1), 145–151 | polarization (Jensen–Shannon divergence) |
| G. W. Brier (1950). "Verification of forecasts expressed in terms of probability." *Monthly Weather Review*, 78(1), 1–3 | holdout scoring |
| T. Gneiting, A. E. Raftery (2007). "Strictly proper scoring rules, prediction, and estimation." *JASA*, 102(477), 359–378 | proper scoring rules |
| A. M. Law (2015). *Simulation Modeling and Analysis*, 5th ed. McGraw-Hill | common random numbers |

## Data and code

| Reference | License | Used for |
|---|---|---|
| MatrAIx Persona 1M, Hugging Face `MatrAIx2026/MatrAIx_Persona_1M` | `matraix-research-only` | the default persona corpus (not bundled) |
| [MatrAIx-Persona-8B](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B) | MIT | corpus decoding contract, prompt renderer |
| [OASIS](https://github.com/camel-ai/oasis) | Apache-2.0 | world module |
| [ASAL](https://github.com/SakanaAI/asal) | Apache-2.0 | sweep pattern (no code copied) |
| [semantic-similarity-rating](https://github.com/pymc-labs/semantic-similarity-rating) | Apache-2.0 | SSR computation, ported |

What was taken from each, file by file, is in the [salvage inventory](../SALVAGE.md).
