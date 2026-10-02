# Threats to validity

What could make Jahan's results wrong even when the engine runs exactly as designed. They are grouped in the
usual way: whether the measurement means what it says (construct), whether the effect is really caused by what
was varied (internal), and whether it would hold for real people (external).

## Construct validity: does the number measure intent?

- **The simulation claim is unchecked.** No simulated purchase-intent distribution has been compared with human
  answers to the same question about the same product. Until one is, adoption is a property of the simulation.
- **The mapping claim is unchecked on this setup.** SSR's accuracy was established on the paper's own anchors and
  embedding model. Jahan's anchors are hand-written and its embedding model differs; `purchase_intent/v2` passes
  the internal anchor check, but has not been validated against human ratings.
- **Anchors are sensitive to wording.** `purchase_intent/v1` failed on two embedding models because near-paraphrases
  at the top of the scale were ordered by wording, not intensity. A version that passes on one embedding model
  may fail on another, so a pin is per model.
- **Within one anchor set the least similar point gets exactly zero.** This is the published formula. Averaging over
  six sets usually restores some mass, but a group that agrees closely can still show zeros at an end of the scale.

## Internal validity: is the effect caused by what was varied?

- **One seed is not a result.** A single world gives no estimate of noise; several evaluations ran one seed. The
  report says so, and herding cannot be judged without a spread.
- **Common random numbers cut both ways.** Worlds of one variant share their draws across prices, which isolates
  the price effect, but means those worlds are not independent samples of each other.
- **The model is a confound.** Results belong to the pinned chat and embedding models. A different model is a
  different instrument; studies are comparable only under the same pins.
- **Order effects are controlled, not absent.** Engagement becomes visible only on the next tick, so turn order
  within a tick cannot matter, at the cost of a one-tick lag that real platforms do not have.

## External validity: would real people behave this way?

- **Filled-in attitudes are biased.** The holdout found model-completed attitudes reproduce relative differences
  between demographic groups but get the overall level wrong, losing to a counting baseline
  ([results](results.md#holdout)). Every synthesized field is marked, but a study that leans on many of them
  inherits that bias.
- **The corpus is not a population.** Persona 1M mixes surveys, encyclopedia biographies, product reviewers and
  synthetic rows. Survey sources differ in who they reached, and text sources describe people who wrote or were
  written about. Gates judge a draw against the study's own design, not against a real population, unless the
  ontology carries measured category targets.
- **Channels are models of platforms.** The feed and forum use published ranking rules (X's, ported by OASIS, and
  Reddit's hot score), not the platforms' current production systems, and simulated personas are not their users.
- **Conditioning is necessary, not sufficient.** It prevents collapse into one respondent; it does not show that
  each persona answers as the real person would.
- **Time is compressed.** A tick is declared, but simulated personas do not forget, get busy or see competitors'
  advertising the way real people do over the same span.

## What would reduce these threats

| Threat | What would address it |
|---|---|
| unchecked simulation claim | a human purchase-intent benchmark on the same concepts, scored at the trust floors (similarity and rank attainment ≥ 0.80) |
| unchecked mapping claim | a satisfaction anchor version that passes its check, then validation on public reviews with star ratings |
| biased filled-in attitudes | recalibrating completed values toward measured marginals where they exist, then a second holdout |
| single seeds | running every reported comparison under several replicate seeds |
