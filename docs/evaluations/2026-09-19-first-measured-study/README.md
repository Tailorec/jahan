# Evaluation: the first study the engine actually measured

*2026-09-19 · real corpus, real model, a scale that passed its own gate · Bedrock spend < $0.01*

Every study before this one reported adoption as unmeasured, and said so honestly: no anchor
version had ever passed its check (ADR 0029), so no turn could be scored. This is the first run
where the engine measured the thing it exists to measure.

## What ran

| | |
|---|---|
| Brief | `examples/protein_water_persona1m.yaml` (the corpus's own attribute names) |
| Ontology | `beverage_protein_persona1m` 1.0.0 — conditions on `age_bracket`, `gender_identity`, `lstyle_exercise_freq`, `health_fitness_level` |
| Population | 500 personas, seed 4021, shards 0000/0004/0005, sources `wiki,gss,amazon,stackoverflow` |
| Scale | `purchase_intent/v2`, checked and passing against Titan Text Embeddings v2 |
| Chat | `amazon.nova-micro-v1:0` through a local LiteLLM proxy over Bedrock |
| Scenario | survey room, 3 day-ticks, `elicits: purchase` |
| Gates | all six passed (p = 0.71–0.88), mix 0.60/0.40 exactly as requested |

## What it measured

```
ADOPTION              0.5684        share-weighted top-two-box
  gym_regulars   0.60  ttb 0.592    pmf [0.003, 0.156, 0.249, 0.377, 0.215]
  protein_dieters 0.40 ttb 0.532    pmf [0.012, 0.181, 0.275, 0.356, 0.177]
audience divergence   0.0049
polarization          not measurable — the population formed no communities
turns                 461, every one scored, every one `answer`
word of mouth         0 deliveries (a survey room has no social channel)
```

The distribution is shaped like a real one: the mode sits at 4 with a genuine left tail, rather
than collapsing onto the midpoint, which is what a working SSR mapping should produce.

**This is not a finding about protein water.** Trust is `UNCALIBRATED` and the report says so
once. Nothing here has been benchmarked against human purchase intent, and an adoption number
from an uncalibrated instrument is a demonstration that the instrument runs, not evidence about
a market.

## The scale

`purchase_intent/v1` fails on two embedding models; against Titan v2 its rank stability is 0.500
where the floor is 0.8. The Titan evaluation named the cause exactly: v1's six sets drift off the
construct's own verb — "get", "purchase", "try", "choose" — and off the probability axis at the
top, where "lean strongly toward", "inclined to try" and "appeals to me" sit close enough that
Titan's compression of near-paraphrases decides the peak by wording rather than intensity.

v2 holds both fixed. Every statement is about buying; every rung carries one unambiguous
probability marker (never, unlikely, even, likely, certain); the surface variety lives in the
sentence frame; and nothing borrows a ladder rung's own distinctive wording at a position that is
not its own. It was checked **once** and passed on the first attempt:

| | v1 | v2 |
|---|---|---|
| Rank stability (floor 0.8) | 0.500 ✗ | **0.929** ✓ |
| Ladder strictly increasing | ✓ | ✓ (1.70 → 2.05 → 3.17 → 3.65 → 3.81 → 4.00 → 4.12) |
| Non-collapse (floor 0.1) | 0.73 ✓ | **0.777** ✓ |

It was not iterated against the gate. A version fitted to its own test is evidence of nothing,
which is why v1 was left as it fell rather than adjusted (ADR 0027), and why the same restraint
applies to everything below.

## Two findings about the instrument

**Belief deltas saturate.** Of 826 recorded moves, 611 are exactly `+1.0` and 170 exactly `-1.0`;
the median is 1.0.

```
+1.0 → 611    -1.0 → 170    0.5 → 21    0.1 → 17    0.0 → 5    -0.5 → 2
```

Nova Micro reads "a move in -1..1" as an instruction to pick an end. The mechanism works — beliefs
move, per dimension and per claim, and the movement is recorded — but the magnitudes are not
credible, so `belief_move_mean` is not a number to quote and the belief-shift findings measure
saturation rather than persuasion. This is also what produced the contract violation that killed
an earlier run: two `+1.0` moves in one tick summed to 2.0, outside what a `BeliefChange` may
state. Eliciting graded deltas from a small model needs its own design work; nothing here was
tuned to hide it.

**Community detection is all-or-nothing.** Polarization compares communities, and the population
formed none — not for want of structure. Across the resolution search:

| γ | modularity | communities | sizes | verdict |
|---|---|---|---|---|
| 0.50 | 0.152 | 2 | 405, 95 | below the modularity floor |
| **0.75** | **0.409** ✓ | **8** ✓ | 104, 103, 85, 71, 52, 38, 37, **10** | one community below the 5% floor |
| 1.00 | 0.417 | 13 | … | too many, three below the floor |
| 1.25 | 0.416 | 17 | … | too many, seven below the floor |
| 1.50 | 0.406 | 21 | … | too many, ten below the floor |

At γ=0.75 the partition clears modularity and sits exactly at the community ceiling, with seven
communities of 37–104 people and one of ten. Every community must hold 5% of the population, so a
single 2% remainder discards the whole partition — and Leiden almost always leaves one. The
thresholds are documented as the study's to tune (`CommunityThresholds`), and they are left
untouched here: loosening a rule so that one's own run passes is the same error as fitting anchors
to their gate. What was fixed is the silence — a digest that cannot measure polarization now says
why (ADR 0038).

## What the run exposed

Reaching this point took eleven defects, and the last three had never executed at all — none of
them *could*, because no scale had ever passed, and each fix made the next one reachable.

1. `ArrowInvalid: offset overflow` reading the release's largest shard
2. Every shard retained as its whole Arrow table, and every shard loaded at once — this took a 16 GB machine into swap
3. `grounding` read whole for two leaves: 3.08 GB of unused `evidence` text
4. 51M grounding entries in a single chunk, 390 MB of parent indices before any filtering
5. A row-set per field, `MemoryError` inside one persona's decode
6. A raw `KeyError: 'age'` for attributes the corpus does not carry, after four shards had been read
7. No way to name the anchor version, shards, sources or elicited task on the command line
8. A combined belief move of 2.0 broke its contract and ended the run — and one persona's failure took the batch with it, against ADR 0031
9. The survey room offered all fifteen actions and affords one: 895 of 897 turns chose something it discards
10. The intent question replaced the turn envelope: 1000 unparseable outputs, zero turns
11. Anchor hashes keyed by construct, looked up by anchor set id: 252 perfect answers, none scored

`--fake` could not have caught any of them. The synthetic corpus is generated from whatever
attribute names the study asks for, so every name exists by construction; the stub responder
always answers `action: "answer"`, which is coincidentally the one action a survey room affords;
and it returns a belief delta of 0.05, which never sums past the contract's bound.

## Reproducibility

Re-running the same configuration reproduced the measurement exactly — adoption 0.5684, the same
per-audience masses, 461 turns all scored. The second run was served entirely from the engine's
completion cache (4,214 of 4,214 calls), which is why its recorded spend is zero; a cold run of
this study costs under a cent.

## Caveats, stated plainly

- Trust is `UNCALIBRATED`. No claim here is about a market.
- Belief magnitudes are saturated on this model and should not be read as effect sizes.
- Polarization is unmeasured, for the reason above, not because opinion was uniform.
- One world, one seed: there is no replicate spread, so herding reports as not measurable.
- The artefacts of this run are not committed; `runs/` is deliberately outside the repository.
