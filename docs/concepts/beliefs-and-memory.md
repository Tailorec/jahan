# Beliefs, memory and reflection

A persona is not a fresh prompt every tick. Between ticks it carries **persona state**: what it currently
believes, what it remembers, and when it last reflected. The state travels with the persona to wherever its
turn is taken, and is never shared between personas
([ADR 0030](../adr/0030-a-personas-state-travels-with-its-job.md)). The method follows *Generative
Agents*[^ga]: memories scored by recency, importance and relevance, consolidated by periodic reflection.

## Beliefs

A **belief** is what a persona holds to be true about the proposition, on two levels:

- three **dimensions**: *value* (is it worth the price?), *fit* (is it for someone like me?), *trust* (do I
  believe the brand?);
- a **credence** for each individual claim of the brief ("20g protein with zero sugar").

Every value lies between 0 and 1, and every persona starts at 0.5 on everything: no opinion yet. A reaction
may move any of them by a signed change $\Delta \in [-1, 1]$, and the result is clamped:

$$
b' = \min\big(1,\ \max(0,\ b + \Delta)\big)
$$

Credence is tracked **per claim** so that a flip on one claim stays visible even when the overall picture
barely moves: a persona that stops believing "zero sugar" but still likes the price is a finding.

## Memory

A **memory** is something that happened to one persona, in its own words, with how much it mattered and when.
Each turn writes one ("commented on C2: 20 grams sounds great but…"). A memory is embedded once, when written,
and never again.

### How important a memory is

Importance comes from what the persona *did*, plus how much its beliefs moved, capped at 1:

$$
\text{importance} = \min\Big(1,\ \text{base}(\text{action}) + \min\big(0.6,\ \textstyle\sum \lvert \Delta \rvert\big)\Big)
$$

| Action | Base | Action | Base |
|---|---|---|---|
| ignore | 0.05 | answer, post, comment, reply, quote, ask a peer, complain | 0.5 |
| like, upvote, downvote, follow | 0.2 | buy, reject | 0.7 |
| repost | 0.3 | | |

On the cheaper model this is pure arithmetic: no extra model call. A quiet turn that moved nothing stays light;
a turn that changed a mind weighs up to 0.6 more.

### Which memories come back

Before each turn, the persona's **own** memories are scored against what it is looking at, and the best
$k$ are put into its prompt (3 on the cheaper model, 8 on the frontier model). For a memory written $\Delta t$
ticks ago:

$$
\text{score} = \underbrace{e^{-\Delta t / \tau}}_{\text{recency}} \times \underbrace{\text{importance}}_{\text{0 to 1}} \times \underbrace{\cos(\mathbf{m}, \mathbf{s})}_{\text{relevance}}
$$

where $\mathbf{m}$ is the memory's embedding, $\mathbf{s}$ the embedding of the stimulus in front of the persona,
the cosine is clamped to $[0, 1]$, and the time constant is a quarter of the horizon,
$\tau = \max(1,\ H/4)$.

!!! example "Worked example"
    A 30-tick study, so $\tau = 7.5$. At tick 12 a persona holds four memories:

    | memory | age $\Delta t$ | recency $e^{-\Delta t/7.5}$ | importance | relevance | score | rank |
    |---|---|---|---|---|---|---|
    | A: replied to a sceptical post | 2 | 0.766 | 0.50 | 0.80 | **0.306** | 1 |
    | C: liked the launch post | 1 | 0.875 | 0.20 | 0.90 | **0.158** | 2 |
    | B: told a friend it was overpriced | 10 | 0.264 | 0.90 | 0.60 | **0.142** | 3 |
    | D: reflection: "I don't trust the brand" | 20 | 0.069 | 0.85 | 0.70 | 0.041 | 4 |

    On the cheaper model ($k = 3$) the persona remembers A, C and B. On the frontier model ($k = 8$) it also
    remembers D.

Retrieval never reaches another persona's memories, so nothing leaks between people. A persona keeps at most
50 memories. Past that the least important are dropped, never the most important.

## Reflection

Every so often a persona **reflects**: a frontier-model call consolidates what has happened into a revised
belief and one to three new memories of high importance (0.85). Reflection fires when either holds:

- **Cadence.** Every $n$ turns, where each persona's interval is jittered from the run seed:
  $n = 4 + (\text{first byte of } \operatorname{SHA\text{-}256}(\text{"reflection-cadence"} \,|\, \text{seed} \,|\, \text{persona})) \bmod 5$,
  giving an interval between 4 and 8. Jitter stops every persona reflecting on the same tick.
- **A sharp move.** The largest single change in a turn, across dimensions and claims, exceeds 0.3:
  $\max \lvert \Delta \rvert > 0.3$. A single claim flipping is enough.

If a reflection call fails, the persona consolidates by rule instead.

## Character probes and drift

A persona can slowly stop sounding like itself over a long study. That is **drift**. To measure it, a seeded 2%
of active personas are asked, every 10 ticks, two questions whose answers are already in their own attributes
("what is your employment status?"). The run reports the share that disagreed with themselves. A probe never
changes the persona's reaction or fails its turn; it only measures.

## What the persona is told about itself

Every turn starts from the **persona block**: the persona's own attributes, rendered once per study from the
ontology's relevance order and reused every tick. This is **conditioning**, and it is not optional. A turn
whose block is empty is refused before any model call.

!!! note "Measured: conditioning is what makes a population"
    On 150 personas, the same question asked without a persona block returned the **same answer from every
    persona**; with their blocks they gave 57 different ones
    ([evaluation](../evaluations/2026-09-19-conditioning-effect/README.md)). The SSR paper found the same:
    unconditioned answers are optimistic and narrow, and rank agreement with humans falls by about half.

[^ga]: J. S. Park, J. C. O'Brien, C. J. Cai, M. R. Morris, P. Liang and M. S. Bernstein (2023). "Generative
    Agents: Interactive Simulacra of Human Behavior." *UIST 2023*. arXiv:2304.03442.
