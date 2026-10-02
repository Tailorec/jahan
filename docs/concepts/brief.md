# The brief

The **brief** is the one file you write. It describes the product being studied and who you want to study,
and everything else in a study is checked against it.

## What a brief holds

```yaml
product:
  name: Protein water
  category: beverage_protein            # which category ontology to read it against
  description: Clear protein-infused water with 20g whey isolate

price:
  amount: 2.49
  currency: USD

claims:                                 # the atomic unit of stimulus: posts, cards and findings cite these
  - text: 20g protein with zero sugar
    source: user_asserted               # user_asserted | public_source | assumed
    evidence_url: https://example.com/nutrition-panel
  - text: Hydrates like water, not milk
    source: assumed

competitors:
  - name: Clear whey shooter
    price: { amount: 2.99, currency: USD }
    claims: [Shooter format, 25g protein]

target_market: US urban adults 25-40 who train at least weekly

audiences:                              # named slices of the market; shares sum to one
  - name: gym_regulars
    share: 0.6
    attribute_filters:
      exercise_frequency: 3_plus_weekly          # one value
  - name: protein_dieters
    share: 0.4
    attribute_filters:
      diet_protein_focus: high
      # other forms:  exercise_frequency: [weekly, 3_plus_weekly]        any of several values
      #               exercise_frequency: { range: [weekly, 3_plus_weekly] }   a run of ordinal bands

assumptions:
  - text: Respondents distinguish clear from milky protein formats
    source: user_asserted

ontology_version: 1.0.0                 # exact versions only
```

The parts:

**Claims.** Each claim is one assertion the product makes. Claims get identifiers `C1`, `C2`, … in the order
they are written, and you never write the identifiers yourself. A feed post, a forum thread and a report
finding all point at a claim by its identifier. That is why reordering claims makes a *different* brief: a
study whose claims moved is not comparable with the one before, and the engine refuses to resume it.

**Where a claim came from.** Every claim and assumption states its source: `user_asserted` (you say so),
`public_source` (it is published somewhere), or `assumed` (nobody has checked).

**Evidence.** A claim may cite a URL. A URL says where to look, not what was there, so loading a brief never
touches the network. A separate command fetches each cited URL once and records the **content hash** of what
it served. A cited URL that was never fetched is refused ([ADR 0013](../adr/0013-intake-is-pure-and-evidence-is-fetched-separately.md)).

**Audiences.** An audience is a named, attribute-defined slice of the market. A filter is one value, a list of
values, or a `range` of ordinal bands. Shares are all-or-nothing and sum to one. A brief that declares no
audiences draws uniformly from everyone eligible.

## The assumption ledger

Everything the study takes as true without evidence is gathered into the **assumption ledger**:

- the assumptions you wrote down;
- every claim marked `assumed`;
- what the brief left unstated, such as a target market with no audiences behind it.

The ledger is not stored separately. It is gathered from the brief each time it is needed, and it is printed
in every report, so a caveat cannot go missing between the brief and the conclusion.

## The category ontology

A brief never says which persona attributes matter for its product. That is the job of the **category
ontology**, a separate, versioned file the brief names by version
([ADR 0004](../adr/0004-briefs-reference-their-ontology-by-version.md),
[ADR 0044](../adr/0044-an-ontology-is-an-immutable-versioned-study-input.md)). One ontology serves many briefs
in the same category.

```json
{
  "category": "beverage_protein",
  "version": "1.0.0",
  "attribute_domains": {
    "age": "demographic", "sex": "demographic",
    "exercise_frequency": "category_behaviour",
    "diet_protein_focus": "psychographic"
  },
  "conditioning_set": ["age", "sex", "exercise_frequency"],
  "relevance_order": ["age", "sex", "exercise_frequency", "diet_protein_focus"],
  "anchor_sets": { "purchase_intent": "purchase-intent-v1" },
  "completion_policy": { "completable_domains": ["economic", "decision_rule", "media"] },
  "ordinal_scales": [
    { "attribute": "exercise_frequency",
      "bands": [ {"label": "rarely", "midpoint": 0.25},
                 {"label": "weekly", "midpoint": 1.0},
                 {"label": "3_plus_weekly", "midpoint": 4.0} ] }
  ]
}
```

| Field | What it decides |
|---|---|
| `attribute_domains` | Which attributes the category uses, and what kind each is: demographic, psychographic, category behaviour, economic, decision rule or media. |
| `conditioning_set` | Attributes every persona **must** have. A row missing any of them is never eligible ([ADR 0002](../adr/0002-conditioning-set-filters-before-sampling.md)). |
| `relevance_order` | Every attribute, ranked once. It decides what is cut first when a prompt runs out of room, how a filter is relaxed, and how much each attribute weighs in the social network. |
| `completion_policy` | Which domains a model may fill in when the data is sparse. Demographics and psychographics never can be. |
| `ordinal_scales` | Ordered attributes, with a numeric midpoint per band. Used by ordinal gates, ranges and network similarity. |
| `anchor_sets` | Which reference statements score each measured construct (see [Measuring purchase intent](measuring-intent.md)). |
| `targets` *(optional)* | The category's measured real-world distribution, used to judge a study that declares no audiences. |

A saved ontology version is never changed. Editing it saves a new version.

## Identity

A brief is identified by a hash of its content, not its file name: comments and whitespace do not change it,
and reordering claims does. The same is true of the ontology, the population and the run configuration
([ADR 0009](../adr/0009-identity-is-derived-and-every-pin-is-verified.md)).
