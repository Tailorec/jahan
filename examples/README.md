# Example studies

Two runnable studies, each built with the two stages of the pre-flight (`preview` then `assess`/`build`).

## The offline quickstart — `beverage_protein`

```
python examples/beverage_quickstart.py
```

Runs entirely on a `SyntheticCoresetSource`: it downloads nothing and opens no socket. The synthetic
shape supplies exactly the attributes the beverage ontology conditions on, so every field is measured
stand-in data and nothing is synthesized — the quickstart grades `measured`, and it carries no category
targets because a synthetic corpus is not a measurement of the real beverage category.

## The real-data study — `software_dev` on Stack Overflow

```
hf download MatrAIx2026/MatrAIx_Persona_1M_Public_Release --repo-type dataset \
  --local-dir "$HOME/.cache/consumersim/coreset/MatrAIx2026__MatrAIx_Persona_1M_Public_Release"
python examples/ai_code_review.py
```

The download is explicit and opt-in; the study never fetches a shard on its own. Point it at an existing
cache with `CONSUMERSIM_CORESET_CACHE=/path/to/persona_1m`. Stack Overflow is the one source carrying
demographics and developer attitudes on the same person, so both audiences are grounded filters on
measured attributes — not projections — and the gate report grades `measured`.

### Reading coverage: the worked preview

The `ai_skeptics` audience — `att_ai` in {Skeptical, Opposed} — previewed against the index alone (no
shard is decoded to answer it), on the cached Stack Overflow rows:

```
stackoverflow    matched 34,373  carrying 100,662  total 113,120
    age_bracket              measured
    region                   measured
    demo_employment_status   measured
    highest_education        measured
    years_experience         measured
    dev_professional_status  measured
    att_ai                   measured
    coding_ai_sentiment      measured
evidence measured   synthesized 0   relaxations none
```

Every count is a different fact and the three denominators keep them apart. `total` 113,120 is what the
source holds that passes the conditioning set's eligibility check. `carrying` 100,662 is how many of
those carry the attributes the audience depends on at all. `matched` 34,373 is how many actually are
skeptics or opposed. A zero in `carrying` would mean "nobody was asked" (look elsewhere or relax);
a zero in `matched` beside a nonzero `carrying` would mean "nobody is like this" (an empirical finding).
Here the ratio 34,373 / 100,662 — about a third — is the audience's size, and it clears a quota of 750
with room to spare, so the relaxation ladder has no rung to climb.
