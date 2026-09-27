# A study's description drafts its audiences, never its category's conditioning set

A study author can describe who they want to study in words, and the interface drafts the audiences and the category
ontology from that description. The draft decides audience filters for the study; it does not decide the conditioning
set for the category. The conditioning set is a per-category invariant (ADR 0004): a brand-new category defaults to the
cross-survey core — the attributes at least half of every survey source answered, today age, region, education and
employment — and a later study of an existing category reuses its ontology, adding declared attributes as a new
version (ADR 0044) but never changing what it requires. A trait every group in one description shares ("all in North
America") is a filter in each audience, not a requirement.

The obvious design derives the conditioning set from the description, and the first mockup did. It failed twice. It
collapsed audiences drawn from different surveys: requiring the General Social Survey's children count, because the
parents group used it, removed every Stack Overflow respondent and took the early-career group from 8,743 people to 92.
And it made the category churn: two studies of one category, described differently, wrote different conditioning sets,
so their personas were drawn under different rules and their results stopped being comparable.

## Considered options

Letting each description rewrite the conditioning set was rejected for the two failures above. Giving every study its
own ontology was rejected because it abandons cross-study comparability outright. Drafting the first category's
conditioning set from its first study was rejected because that study binds every later one: the
`education_savings_app` 1.0.0 ontology requires `life_stage`, which only 19% of GSS respondents answered.

## Consequences

The category is confirmed before anything is drafted: the model matches the product against existing categories, and
the person answers "same kind of product as *X*?". Everything drafted is a proposal a person confirms (ADR 0014): an
audience the draft changed to make it drawable, and a phrase the drafter matched inconsistently across wordings, each
blocks Continue until accepted, changed or undone. The floor an audience must reach is its quota at the study's size,
not a fixed number. Caveats are recorded, not only shown: audiences drawn mostly from different surveys, and any text
source a study admits, are written into the brief's assumption ledger and travel into every report.
