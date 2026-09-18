# Anomalies are rules over what was measured, and report what they cannot measure

The three anomalies were specified over purchase intent: herding as `|Δ mean_PI| > 2σ` on a trailing window,
backlash as a bimodal comment-sentiment split, flop as sustained low adoption with high awareness. Two of the
three therefore cannot run on any trace the engine currently produces, because nothing scores intent (ADR 0029).

Herding and backlash move to a quantity every turn now carries: the belief change a persona states. Herding is
a belief-movement shift beyond `2σ` of the replicate spread over a trailing window; backlash is a split in the
*sign* of those moves past a threshold. Both stay what anomalies were meant to be — deterministic arithmetic
over recorded numbers, cheap, reproducible and testable against a planted fixture. Flop genuinely needs
adoption, so it reports as not measurable, with the reason, rather than as absent.

What is refused is filling the gap with judgment. Asking a model to score sentiment, or to rate verbatims as a
stand-in for intent, would put a second uncalibrated instrument inside the module whose stated virtue is that
its anomalies are rule-based, need no judge model and carry no calibration burden. An anomaly nobody can
recompute from the trace is not a finding; it is an opinion with a threshold attached.

## Considered options

Detecting nothing until anchors pass was rejected: a run that moved every persona's beliefs and spread 113
word-of-mouth messages can herd, and refusing to look would waste the one signal the engine reliably produces
today. Reporting an unmeasurable anomaly as simply absent was rejected because absence reads as "we checked and
it did not happen", which is a stronger claim than the run supports. A model-scored sentiment split was
rejected as above.

## Consequences

Two anomaly rules now read belief movement, which means they measure what personas *said* changed rather than
what a rating scale would have shown — a weaker signal, and stated as such wherever it is reported. When
anchors pass, the intent-based forms return beside them rather than replacing them, and a study that has both
can be compared on whether they agree.
