# A digest reports what a run measured, and says plainly what it could not

`OutcomeDigest` required response masses per audience and computed adoption from them, so it encoded an
assumption that every study ends in ratings. No anchor version passes its check (ADR 0029), so no run the
engine can produce carries any purchase intent at all, and the contract as written could not digest a single
real trace. That is not an edge case to wait out: it is the normal case until a client supplies a validated
scale, and a module that cannot digest the normal case cannot be built or tested against anything real.

So intent is optional. A digest carries response masses when the run scored them, and when it did not,
`adoption`, `polarization` and `audience_divergence` are `None` — reported as not measurable rather than as a
measured zero, exactly as `polarization` already behaved for a population with fewer than two communities. The
digest records how many turns went unscored and why, so a reader is told the reason rather than left to infer
one from an absence.

What the digest reports instead is what the run actually produced, which is a great deal: the action mix, how
far beliefs moved and in which direction, how far word of mouth reached, and the objections personas raised.
A study of 200 personas that published 116 stimuli, took 495 turns and delivered 113 word-of-mouth messages
measured plenty; refusing to digest it would say the engine learned nothing, which is false.

## Considered options

Refusing to digest a run without intent was rejected: it blocks `analysis`, `report` and `cli` behind an
anchor problem that is none of theirs, and leaves all three testable only against fixtures carrying invented
masses — which is how nine defects survived until the first real run. A second digest type for runs without
intent was rejected because every non-intent measure would then exist twice, and one concept implemented twice
is what made this module necessary in the first place. Filling the gap with a proxy for intent — asking a
model to rate the verbatims, or reading sentiment as a stand-in — was rejected outright: it is an unvalidated
number wearing the name of a validated one.

## Consequences

`OutcomeDigest` changes shape, so pinned identities re-pin; doing that now is cheaper than after a client's
anchors land. Adoption, the study's headline, is `None` for every run the engine can currently produce, and
every report that quotes it must say why. Analysis can be built, tested and reviewed against real traces
today, which is the point.
