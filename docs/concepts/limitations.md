# Limitations

What Jahan can and cannot tell you today. Read this before reading any number it produces.

## Every result is uncalibrated

No simulated result has been compared with how real people answered the same question about the same product.
Until that happens, a Jahan number is **what a simulation measured**, not a fact about a market. Every report
states this once, at the top, and the engine has no way to claim otherwise
([Results and trust](results-and-trust.md#trust-level)).

## What it is good for now

- **Exploring mechanisms.** How does word of mouth change intent compared with a feed? Does an objection spread
  through one community and not another? Does a claim lose credence while overall intent holds?
- **Finding objections in people's own words.** Objection clusters are quoted verbatims, grouped by meaning.
- **Generating hypotheses to test with real people.** Every finding comes with the real-world test that would
  disprove it.
- **Research on simulation itself.** Every turn is recorded, every prompt rebuildable, every run replayable.

## What it is not good for

- **Forecasting sales or market share.** Adoption is the share of simulated personas who say they would probably
  or definitely buy. It is not a purchase rate, and stated intent overstates real buying even among real people.
- **Replacing a survey.** Nothing here has been shown to match a survey's answers.
- **Commercial studies on the default corpus.** Persona 1M is licensed for non-commercial research only. A
  commercial study needs a population you have the rights to.

## Known weaknesses, measured

| Weakness | Evidence |
|---|---|
| Model-filled attitudes get the overall level wrong and lose to a counting baseline | [holdout](../research/results.md#holdout) |
| Anchor statements can fail on a given embedding model; `purchase_intent/v1` failed on two | [anchor checks](../research/results.md) |
| A pre-registered prediction about which audience would respond best was wrong | [education savings](../research/results.md#a-prediction-that-failed) |
| Most evaluations so far ran one seed and small populations (60–500) | [results](../research/results.md) |

## Design limits

- **One construct.** Purchase intent is the only construct a study measures; satisfaction anchors exist only to
  validate the scoring method.
- **Three channels.** An X-like feed, a Reddit-like forum and word of mouth. No retail shelf, search, advertising
  auctions or offline exposure.
- **Simulated time is coarse.** Ticks are hours, days or weeks, and engagement becomes visible one tick late.
- **Cost grows with people × ticks.** Every active persona's turn is a model call, and every survey wave asks
  everyone. Use the budget, and run small first.
- **Results depend on the models.** A study is a property of its pinned models; a different model is a different
  instrument.

See [Threats to validity](../research/threats-to-validity.md) for the research-level view of the same limits.
