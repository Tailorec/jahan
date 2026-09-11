# ConsumerSim

A simulation engine that runs a population of grounded personas through interacting environments to observe how they react to a product proposition. This glossary is the project's ubiquitous language — the words the code, the docs, and the conversation all use for the same things.

## Language

### The brief

**Brief**:
The user-authored description of the proposition under study — the product, its claims, its price, its competitors, its target market, and the decision the study is meant to inform.
_Avoid_: spec, input, request, study definition

**Claim**:
A single assertion in the brief about the product. Claims are the atomic unit of stimulus: posts, feed cards, and findings all reference a specific claim.
_Avoid_: message, benefit, feature, statement

**Assumption**:
Something the brief takes as true without evidence. Assumptions are recorded rather than resolved, and surface in every report.
_Avoid_: guess, hypothesis

**Claim Source**:
Where a claim or assumption in the brief came from — asserted by the user, drawn from a public source, or assumed. A property of statements in the brief only; it never describes persona data or simulation output.
_Avoid_: provenance (too broad — that word covers three unrelated things), origin

### The population

**Persona**:
One simulated individual, projected from a single row of the persona dataset. A persona is never invented by a model; it is sampled.
_Avoid_: agent (an agent is a persona in the act of behaving), respondent, user, profile

**Field Origin**:
Whether a given persona field came from the dataset, was completed by a model, or was corrected from external data. Stated explicitly on every projected field — never inferred from a field's absence.
_Avoid_: provenance, source (the dataset already uses "source" for which corpus a row came from)

**Grounded**:
A persona field whose value comes from the dataset row. The engine's central invariant is that grounded and synthesized values never mix silently.
_Avoid_: real, actual, true

**Synthesized**:
A persona field whose value was completed by a model because the dataset row was sparse there. Demographics and psychographics are never synthesized.
_Avoid_: generated, imputed, filled, inferred

**Calibrated**:
A persona field whose value was corrected using external human data. No such data exists yet; the term is reserved so the distinction from *synthesized* stays sharp when it does.
_Avoid_: validated, tuned, fitted

**Audience**:
A named, attribute-defined slice of the target market, declared in the brief and referred to by name in study inputs. When a brief declares none, the engine derives audiences from the dataset's calibration targets so there is always a grouping to report over.
_Avoid_: segment (ambiguous — it has meant three different things), stratum, cell, demo

**Community**:
A cluster of personas discovered in the generated social graph. Communities emerge from homophily and tie strength, so they routinely cut across audiences — that divergence is a finding, not a defect. Communities never appear in study inputs, only in results.
_Avoid_: segment, cluster, group, tribe

**Population**:
The complete set of personas for one study, together with their social graph and the communities discovered in it. A study has exactly one population; scenarios vary against it.
_Avoid_: cohort, sample, panel, audience (an audience is a slice of a population)

### The study

**Study**:
One investigation of a single brief — a population, the scenarios tested against it, and the worlds run to test them.
_Avoid_: project, experiment, job, campaign

**Variant**:
One version of the proposition under test — a concept and an emphasis among the brief's claims. The price is not part of a variant, so one variant can be tested at several prices.
_Avoid_: arm, option, treatment, cell

**Scenario**:
A variant together with the conditions it faces: the price it is offered at, which audiences see it, through which channels, and what happens on the way. A scenario describes conditions only; it says nothing about how many times it is run.
_Avoid_: config, setup, case

**World**:
One execution of one scenario over the population — a single independent draw. Running a scenario several times produces several worlds, and the spread between them is the study's variance estimate.
_Avoid_: run (a run is the whole study execution), simulation, trial, replicate

### Grounding and conditioning

**Category Ontology**:
The shared, versioned description of a product category — which attributes matter, what kind of information each holds, which must be present for conditioning, which may be synthesized, and how ordered attributes are scaled. A brief names the version it is read against; it never carries its own copy.
_Avoid_: schema, taxonomy, category config, codebook (the codebook is the dataset's, not the category's)

**Field Domain**:
The kind of information a persona field holds — demographic, psychographic, category behaviour, economic, decision rule, or media. Demographic and psychographic fields are never synthesized.
_Avoid_: field type, section, attribute group

**Conditioning Set**:
The attributes a persona must have populated to be usable in a given category — the demographic and category-behaviour fields the elicitation method depends on. Declared per category; personas lacking any of them are excluded from the candidate pool before sampling, never dropped afterwards.
_Avoid_: required fields, minimum profile, completeness threshold

**Conditioning**:
Presenting a persona's own attributes to the model as the frame for its response. Unconditioned responses converge on a narrow optimism that does not match human answers, which is why conditioning is an invariant rather than a quality setting.
_Avoid_: persona prompting, priming, context injection

**Source**:
Which upstream corpus a persona's dataset row came from. Sources differ enormously in richness, so the source mix of a population is reported alongside its distributions.
_Avoid_: origin (that word describes a field, not a row), provenance

### Time

**Tick**:
One step of simulated time. Its real-world duration is declared per study rather than assumed, so an adoption curve always has a stated unit and two studies are only compared when their units match.
_Avoid_: step, round, turn (a turn is one persona acting), day, world-day

**Horizon**:
How many ticks a world runs before it ends. Memory decay and trend windows are expressed relative to the horizon, not in absolute ticks.
_Avoid_: duration, length, window

**Intervention**:
Something the study does to the world at a given tick — a launch, a teaser, a promotion. Interventions compose: a promotion during a launch is both, not the later one.
_Avoid_: event (an event is a trace record), trigger, shock

### What personas see and do

**Stimulus**:
Something a persona can be shown — a concept, a claim rendered as a post, another persona's post or reply, or a message passed along by word of mouth. Brand-authored and persona-authored stimuli are the same kind of thing seen from different sides.
_Avoid_: content, post (a post is one kind of stimulus), item, ad

**Exposure**:
One stimulus shown to one persona, with the reason it got through and how much attention it drew. A stimulus can be shown without being noticed; noticing is drawing any attention at all.
_Avoid_: impression (an impression is the whole set), view, delivery

**Impression**:
Everything one persona is shown on one channel in one tick. Personas react to an impression rather than to each stimulus separately, because seeing two things side by side is not the same as seeing each alone. A survey room impression holds exactly one exposure.
_Avoid_: batch, feed, screen, exposure set

**Turn**:
One persona reacting to one impression. The unit of simulation and the unit of cost.
_Avoid_: step, tick (a tick contains many turns), call, action

**Reaction**:
What a persona produced from an impression — what they said, what they did, how their beliefs moved, and which stimulus they were responding to.
_Avoid_: response, answer, output

### Belief and evidence

**Adoption**:
The probability that a respondent answers 4 or 5 on the five-point purchase-intent scale, weighted across audiences by their share — the headline measure of whether a variant would be bought.
_Avoid_: purchase rate, conversion, mean intent, score

**Polarization**:
How far communities' purchase-intent responses diverge from one another, weighted by community size — whether social dynamics split the population into camps. Divergence between audiences is reported separately, because camps and target-market splits are different findings.
_Avoid_: disagreement, variance, spread, controversy

**Memory**:
A persona's recollection of something it already experienced — an earlier turn or reflection of its own. A memory is never new information; it is a pointer back into what happened.
_Avoid_: context, history, knowledge

**Belief**:
What a persona currently holds to be true about the proposition — how much they credit each individual claim, and where they stand on value, personal fit, and trust. Beliefs move as personas encounter stimuli and each other.
_Avoid_: attitude, opinion, sentiment, score

**Reflection**:
A persona consolidating recent experience into a revised belief. Triggered by accumulated time or by a large enough shift on any single belief, including a single claim.
_Avoid_: summary, consolidation, update

**Finding**:
One statement the engine makes about what happened, carrying the trace records that support it and the real-world test that would falsify it. A finding cannot exist without both.
_Avoid_: insight, result, conclusion, recommendation (a recommendation is one kind of finding)

**Disconfirming Test**:
The real-world check that would show a finding to be wrong. Required on every finding, because a result nobody could disprove is not a result.
_Avoid_: next step, validation, follow-up

**Trust Level**:
Whether a study's results have been checked against real human data, stated once per run rather than per finding. Uncalibrated is the only level the engine can currently reach, and it cannot claim otherwise because nothing in it produces the evidence a higher level requires.
_Avoid_: confidence (confidence varies per finding and means something else), accuracy, tier, quality

**Confidence**:
How strongly the evidence supports one particular finding — a function of how many personas, how large an effect, how many verbatims. Independent of whether the engine as a whole has been calibrated.
_Avoid_: trust, certainty, significance
