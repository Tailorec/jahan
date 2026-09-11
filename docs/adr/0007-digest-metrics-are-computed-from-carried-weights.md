# Digest metrics are computed from the weights they carry

An outcome digest carries each audience's share and each community's size alongside the response masses, and computes adoption, polarization and audience divergence from them. When those numbers were stored independently, a digest could report no polarization beside communities with opposite responses, and nothing could check it.

Adoption is share-weighted **top-two-box** purchase intent: the probability of answering 4 or 5 on the five-point scale — the conventional concept-test headline, and naturally a proportion. Polarization and audience divergence are the weighted generalized Jensen–Shannon divergence between the groups' masses, base 2, divided by its ceiling log2(n) so they lie in [0, 1]; a single group has none. Groups are combined in sorted order, so equal digests compute identical numbers and identical hashes.

## Considered options

Mean Likert score was the alternative headline; it is not a proportion and hides whether respondents are enthusiastic or merely neutral. Unnormalized divergence was rejected because its ceiling grows with the number of groups, making studies with different community counts incomparable.
