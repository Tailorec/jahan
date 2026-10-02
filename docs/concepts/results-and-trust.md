# Results and trust

Every result is **derived** from the trace: recomputed from recorded events, never stored separately and never
judged by a model. The only model call in the whole analysis step is embedding what personas said, to group
it, through the run's pinned embedding model.

## The digest: what one world produced

Each world gets a **digest**:

- **adoption** at every survey wave, and at the end;
- each **audience's** and each **community's** purchase-intent distribution;
- **polarization** between communities, and **divergence** between audiences;
- the **action mix** (how many likes, replies, purchases, ignores…), and how far beliefs moved, on average and
  in absolute terms;
- **word-of-mouth** deliveries and how many personas they reached;
- the [budget rungs](scenarios-and-worlds.md#budget-and-degradation) the world ran under.

### Adoption

**Adoption** is the probability of answering 4 or 5 on the five-point purchase-intent scale (the *top two
box*, a standard summary in concept testing), weighted across audiences by their share
([ADR 0007](../adr/0007-digest-metrics-are-computed-from-carried-weights.md)). With audience $a$ having share
$w_a$ and mean intent distribution $p^{(a)}$:

$$
\text{adoption} = \frac{\sum_a w_a \left(p^{(a)}_4 + p^{(a)}_5\right)}{\sum_a w_a}
$$

It is measured in survey waves only, so a study with several waves has an adoption per wave. A purchase a persona
makes on a channel is behaviour, not adoption.

!!! example "Worked example"
    | audience | share $w$ | intent distribution $(p_1 \dots p_5)$ | $p_4 + p_5$ |
    |---|---|---|---|
    | gym regulars | 0.6 | (0.05, 0.10, 0.20, 0.40, 0.25) | 0.65 |
    | protein dieters | 0.4 | (0.30, 0.30, 0.20, 0.15, 0.05) | 0.20 |

    $\text{adoption} = 0.6 \times 0.65 + 0.4 \times 0.20 = 0.47$.

### Polarization

**Polarization** asks whether social dynamics split the population into camps. It is the generalised
**Jensen–Shannon divergence**[^lin] between communities' intent distributions, weighted by community size and
divided by its maximum, so it lies between 0 (every community answers alike) and 1 (completely different).
With community $c$ having weight $\pi_c$ (its share of personas), distribution $p^{(c)}$, $n$ communities, and
$H(p) = -\sum_i p_i \log_2 p_i$ the Shannon entropy:

$$
\text{polarization} = \frac{H\!\left(\sum_c \pi_c\, p^{(c)}\right) - \sum_c \pi_c\, H\!\left(p^{(c)}\right)}{\log_2 n}
$$

The numerator is the entropy of the mixture minus the average entropy of its parts: how much uncertainty is
explained by knowing which community someone is in. **Audience divergence** is the same formula over audiences,
weighted by share. The two are reported separately, because camps that formed in the network and a split in
the target market are different findings.

!!! example "Worked example"
    Two communities of 60 and 40 personas, with the two distributions from the adoption example above.

    - Mixture: $0.6\,p^{(1)} + 0.4\,p^{(2)} = (0.15, 0.18, 0.20, 0.30, 0.17)$, entropy $2.276$ bits.
    - Parts: $H(p^{(1)}) = 2.041$, $H(p^{(2)}) = 2.133$; weighted mean $0.6(2.041) + 0.4(2.133) = 2.078$.
    - Divergence: $2.276 - 2.078 = 0.198$, divided by $\log_2 2 = 1$: **polarization = 0.198**.

    Had both communities answered identically, it would be exactly 0.

### Unmeasured is not zero

A quantity a run could not establish is reported as **unmeasured, with its reason**, never as zero and never
left out ([ADR 0038](../adr/0038-a-digest-reports-what-a-run-measured.md)). A study that could not score
purchase intent has *unmeasured* adoption, not adoption of none. A population that formed no communities has
*unmeasurable* polarization, not polarization of zero. The report prints the reason where the number would have
been.

### Spread between worlds

A scenario's worlds are gathered into a **scenario summary**: each seed's digest, and the
[replicate spread](scenarios-and-worlds.md#replicate-spread) between them. Worlds that ran at different budget
rungs are marked, since they are not comparable.

## Objection clusters

What personas said is grouped by meaning. Every verbatim is embedded once; two verbatims are linked when their
cosine similarity is at least **0.75**; each connected group is a **cluster**. A cluster is labelled by its
**medoid**, the verbatim with the smallest total distance to the others in its group, **quoted exactly as a
persona wrote it**. No k-means, no generated summary: a label is always something a persona actually said, and
two runs over one trace give one answer
([ADR 0041](../adr/0041-objection-clusters-are-deterministic-and-quoted.md)).

## Anomalies

An **anomaly** is a pattern a fixed rule recognises. No model judges anything
([ADR 0040](../adr/0040-anomalies-are-rules-over-what-was-measured.md)). Rules read the **signed move** of each
turn: the mean of its belief changes across dimensions and claims.

| Anomaly | Rule (default thresholds) |
|---|---|
| **Herding** | over a trailing window of 3 ticks, the mean signed move exceeds **2 ×** the replicate spread of that same quantity |
| **Backlash** | in a window with at least 4 non-zero moves, the smaller of the two signs makes up at least **30%** of them: opinion is splitting |
| **Flop** | measured adoption below **0.25** |

Herding needs a spread above zero. With one seed, or seeds that agreed exactly, twice the spread is zero, and any
movement at all would clear it, so herding is then reported as *not measurable*, with that reason. Every anomaly
carries the threshold it was judged against beside the value observed.

!!! example "Worked example"
    Three seeds give a replicate spread of mean belief movement of 0.012, so the herding limit is 0.024. In the
    window ending at tick 9, 40 turns moved by a mean of +0.031. $\lvert 0.031 \rvert > 0.024$: **herding at
    tick 9**, citing those 40 turns as evidence.

## Findings

A **finding** is one statement the engine makes about what happened. It **cannot exist** without:

1. the **trace records** that support it, resolved against the trace when the finding is written; and
2. a **disconfirming test**: the real-world check that would show it to be wrong
   ([ADR 0042](../adr/0042-a-report-is-derived-from-the-record.md)).

Findings are extracted deterministically (objection clusters, belief shifts, word-of-mouth paths), never
generated. "Concept B wins" is never crowned: every winner is a hypothesis, and the report ends with the next
real-world test.

Each finding carries its own **confidence** (low, medium or high): how strongly *its* evidence supports it,
given how many personas, how large an effect and how many verbatims. Confidence is about one finding. It says
nothing about whether the engine itself has been checked against reality. That is the trust level.

## Trust level

The **trust level** says whether a study's results have been checked against real human data. It is stated
**once per run**, never per finding, so it cannot quietly vary between findings.

| Level | Requires | Reachable today? |
|---|---|---|
| **Uncalibrated** | nothing | yes, the only level |
| **Category benchmarked** | a benchmark against human answers in this category, pinned by hash, with distribution similarity **and** rank attainment both ≥ 0.80 | no |
| **Prospectively validated** | the same, against a study that predicted human results before they were collected | no |

Any level above uncalibrated must cite a calibration reference that pins its benchmark and human study by
hash, and nothing in the repository can produce one. The engine **cannot overclaim by construction**, not by
discipline ([ADR 0008](../adr/0008-calibration-claims-carry-measured-evidence.md)).

## The report

The report (Markdown for people, JSON for the interface, both from one source so they cannot disagree) states:

- the trust level, once;
- the assumption ledger: everything the study took on faith;
- the digests, with unmeasured values and their reasons in place;
- findings with their evidence, confidence and disconfirming test;
- objection clusters and anomalies;
- the **method disclosure**: pinned models, seeds, template and anchor versions, engine commit, and anything a
  resume was forced past;
- last, the recommended real-world validation.

Two renders of the same findings are byte-identical, so a diff between reports means a difference in findings.

[^lin]: J. Lin (1991). "Divergence measures based on the Shannon entropy." *IEEE Transactions on Information
    Theory*, 37(1), 145–151.
