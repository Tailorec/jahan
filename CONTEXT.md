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

**Evidence**:
What a claim points at, identified by the content hash of what was actually retrieved rather than by its address. A URL says where to look; only the hash says what was seen.
_Avoid_: source (that is Claim Source), citation, reference, proof

**Assumption Ledger**:
The full set of things a study takes as true without evidence — the brief's stated assumptions, the claims it marks as assumed, and what it leaves unstated, such as an undeclared target market. Gathered rather than stored, and surfaced in every report.
_Avoid_: caveats, limitations, disclaimer, risks

**Claim Source**:
Where a claim or assumption in the brief came from — asserted by the user, drawn from a public source, or assumed. A property of statements in the brief only; it never describes persona data or simulation output.
_Avoid_: provenance (too broad — that word covers three unrelated things), origin

### The population

**Persona**:
One simulated individual, projected from a single row of the persona dataset. A persona is never invented by a model; it is sampled.
_Avoid_: agent (an agent is a persona in the act of behaving), respondent, user, profile

**Field Origin**:
Whether a given persona field came from the dataset — and if so whether it was measured or extracted — was completed by a model, or was corrected from external data. Stated explicitly on every projected field — never inferred from a field's absence.
_Avoid_: provenance, source (the dataset already uses "source" for which corpus a row came from), grounded (it hid the measured/extracted distinction)

**Measured**:
A persona field whose value an instrument recorded — a survey answer, a dataset field as recorded. The strongest evidence a field can carry, and empty evidence does not weaken it when the instrument is the source.
_Avoid_: grounded, real, actual, true

**Extracted**:
A persona field whose value a model took rather than an instrument recorded — a reading of corpus text, or an inference from a respondent's other answers. Even in a survey, a value no question asked is extracted. It is a claim about the corpus, not a measurement of the respondent.
_Avoid_: inferred, guessed, derived, grounded

**Synthesized**:
A persona field whose value was completed by a model because the dataset row was sparse there. Demographics and psychographics are never synthesized.
_Avoid_: generated, imputed, filled, inferred

**Calibrated**:
A persona field whose value was corrected using external human data. No such data exists yet; the term is reserved so the distinction from *synthesized* stays sharp when it does.
_Avoid_: validated, tuned, fitted

**Evidence Tier**:
How strongly a value is supported — measured, extracted, calibrated or synthesized — ordered strongest to weakest. A tier grades a claim and never gates one: a report carries the weakest tier among the things it gated, so a pass is never read as stronger than its weakest evidence. The one refusal is that a report may not claim to match the measured category on anything short of measured evidence.
_Avoid_: confidence, provenance, grounding level

**Unexpressible**:
A value a respondent did give that the attribute's vocabulary has no place for — an open band like "65+" against bands that split at 75. It is neither present nor missing: the field is left empty rather than guessed, and counted, because the loss falls on particular values rather than at random.
_Avoid_: invalid, unmapped, dropped, missing

**Coverage**:
How much of a source actually holds a given attribute, stated with its denominators so "nobody was asked" and "nobody is like this" cannot look identical. The reason a study can fail before it runs is almost always absent coverage, not absent matches.
_Avoid_: completeness, fill rate, density

**Audience Preview**:
What the corpus would give a proposed audience before anything is drawn — how many rows match, carry and exist per source, which attributes are measured, extracted or absent, how many fields would be synthesized, which constraints the relaxation ladder would climb, and the evidence tier the result would carry. It is a forecast from the index, never a verdict on a sample.
_Avoid_: dry run, estimate, what-if, simulation

**Audience**:
A named, attribute-defined slice of the target market, declared in the brief and referred to by name in study inputs. When a brief declares none, the engine derives audiences from the dataset's calibration targets so there is always a grouping to report over.
_Avoid_: segment (ambiguous — it has meant three different things), stratum, cell, demo

**Audience Set**:
What Who you study finishes with, saved as one unit: the audiences with their filters and shares, the assumptions they carry, the sources and study size they were counted at, and the one ontology version they were drafted against. A study starts by choosing an audience set, never an ontology alone — one ontology serves many audience sets. A saved set is never changed; editing one saves another.
_Avoid_: preset, template, saved audiences, draft

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

**Relaxation**:
A recorded loosening of an audience's filter, made because too few conditionable rows matched what the brief asked for. The population is still built and may still pass its gates, but it no longer matches the audience as declared, so the relaxation travels with the gate report.
_Avoid_: degradation (that word belongs to the budget), fallback, compromise, best effort

**Degradation**:
A budget-driven reduction in how fully a world is simulated — optional reflections frozen, fewer personas activated per tick, or the world paused. A degraded world is not comparable to one that ran in full, so degradation is recorded where it happens. A survey wave is never thinned: a world pauses before a wave it cannot afford, so every wave it recorded was answered by everyone.
_Avoid_: throttling, fallback, downgrade

**Rung**:
One step of the degrade ladder: the level of reduction every live world of a run is currently under. A rung belongs to the run, because worlds at different rungs are not comparable.
_Avoid_: level, stage, tier (a tier is a model role)

**Cost Ledger**:
What a run has spent so far, summed from the billed calls it recorded. It is derived, never kept as a separate figure.
_Avoid_: budget (the budget is the ceiling), total, accounting

**Discarded Tick**:
A tick that was interrupted before it could be recorded whole. Its work is lost and its spend is unknown but not zero, so a run that lost one says so.
_Avoid_: failed tick, partial tick, rollback

**Partition**:
One world's whole record: its header and every event that happened in it. The unit that is written, validated, resumed and read.
_Avoid_: shard, file, log

**Tick Closed**:
The mark that a tick was recorded whole. A resumed world continues from the last one.
_Avoid_: commit, flush, checkpoint

**Finalization**:
Turning a finished world's live record into its lasting one. What can be read does not change; where it is read from does.
_Avoid_: export, archive, migration

**Trace View**:
The fixed set of questions that can be asked of a run's record. Nothing else can be asked, and nothing that reads it can reach past it.
_Avoid_: query, handle, dataset

**Sweep**:
One run over many worlds — scenarios and seeds — sharing one budget. It is not a separate kind of thing from a run.
_Avoid_: batch, grid, experiment

**Category Ontology**:
The shared, versioned catalogue of which persona attributes matter for a product category — what kind of information each holds, which must be present for conditioning, which may be synthesized, how ordered attributes are scaled, what order they are cut in under a token budget, and which anchor set scores each construct. It declares attributes, never relationships or behaviour: how personas interact is the world's business, not the ontology's. A brief names the version it is read against; it never carries its own copy.
_Avoid_: schema, taxonomy, category config, knowledge graph, entity model, codebook (the codebook is the dataset's, not the category's)

**Category Targets**:
The measured distribution of a category's real population on some of its attributes, with the source it was measured from. A study that claims to represent the whole category is judged against them; a study that targets particular audiences is not, because it departs from its category on purpose. A report may only claim its sample matches the real category when every judgement it rests on was made against them.
_Avoid_: benchmarks, norms, calibration (calibration is checking results against human studies, not checking a sample against a population)

**Field Domain**:
The kind of information a persona field holds — demographic, psychographic, category behaviour, economic, decision rule, or media. Demographic and psychographic fields are never synthesized.
_Avoid_: field type, section, attribute group

**Conditioning Set**:
The attributes a persona must have populated to be usable in a given category — the demographic and category-behaviour fields the elicitation method depends on. Declared per category; personas lacking any of them are excluded from the candidate pool before sampling, never dropped afterwards.
_Avoid_: required fields, minimum profile, completeness threshold

**Candidate Pool**:
The personas a study can be drawn from: rows from its admitted sources that carry every attribute of the category's conditioning set, before any audience filter is applied. An audience is always a slice of the candidate pool, so an attribute the conditioning set requires shrinks every audience at once.
_Avoid_: eligible population (the population is what was drawn), universe, sampling frame

**Conditioning**:
Presenting a persona's own attributes to the model as the frame for its response. Unconditioned responses collapse: measured over 150 personas, every one returned the same answer, where conditioned personas gave fifty-seven different ones. Conditioning is what makes a population a population rather than one respondent repeated, which is why it is an invariant rather than a quality setting.
_Avoid_: persona prompting, priming, context injection

**Source**:
Which upstream corpus a persona's dataset row came from. Sources differ enormously in richness, so the source mix of a population is reported alongside its distributions.
_Avoid_: origin (that word describes a field, not a row), provenance

**Text Source**:
A source whose rows were read from text — encyclopedia entries, product reviews — rather than answered, so every field it carries is extracted. Wikipedia figures and Amazon reviewers are text sources; the four surveys are not, although a survey can still hold an extracted field where no question asked it.
_Avoid_: model-read source, inferred source, unsurveyed source, extracted source (extracted grades a field, not a source)

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

**Channel**:
A way information about the product reaches a persona from outside the study's own survey: a social feed, a forum, or word of mouth along the social graph. A study runs any combination of channels, including none; with none, nothing spreads and each persona only ever sees the concept.
_Avoid_: environment, platform (a platform is one kind of channel), survey room

**Launch Reach**:
The share of personas who hear of the product first-hand at launch, chosen at random, when word of mouth is the only channel — without them nobody has anything to pass on. Feeds and forums need none: their own launch posts reach whoever is active.
_Avoid_: seeding, seed share, initial exposure

**Survey Wave**:
The purchase-intent question put to every persona at a scheduled tick, apart from anything they do on a channel. It only reads: a persona answers from what it remembers, and answering changes nothing about it. Every study has at least one wave; repeated waves turn intent into a trajectory over ticks. A survey wave is neither a channel nor an environment.
_Avoid_: survey room, poll, check-in

**Stimulus**:
Something a persona can be shown — a concept, a claim rendered as a post, another persona's post or reply, or a message passed along by word of mouth. Brand-authored and persona-authored stimuli are the same kind of thing seen from different sides.
_Avoid_: content, post (a post is one kind of stimulus), item, ad

**Exposure**:
One stimulus shown to one persona, with the reason it got through and how much attention it drew. A stimulus can be shown without being noticed; noticing is drawing any attention at all.
_Avoid_: impression (an impression is the whole set), view, delivery

**Impression**:
Everything one persona is shown on one channel, or in one survey wave, in one tick. Personas react to an impression rather than to each stimulus separately, because seeing two things side by side is not the same as seeing each alone. A survey wave's impression holds exactly one exposure: the concept.
_Avoid_: batch, feed, screen, exposure set

**View**:
The public context around what a persona is shown: how others have engaged with each stimulus, the thread it belongs to, and the persona's relationship to its author. A view covers exactly the stimuli in the impression, and never reveals other personas' private state or how the study is turning out.
_Avoid_: world state, snapshot, context (context also includes the persona's own memories)

**Social Proof**:
Other personas' visible engagement with a stimulus — the counts a persona sees beside it. Social proof only works through what is visible, so it is part of the view rather than of the stimulus. Engagement becomes visible from the tick after it happens, never within the same tick.
_Avoid_: popularity, virality, trending

**Presentation**:
An impression together with its view — everything a persona is given to react to in one turn.
_Avoid_: prompt, input, context

**Turn**:
One persona reacting to one impression. The unit of simulation and the unit of cost.
_Avoid_: step, tick (a tick contains many turns), call, action

**Guardrail Violation**:
A persona's response that referred to something it was never shown, even after being asked again with a stricter instruction. It is recorded in place of a reaction, so the persona does not react that tick.
_Avoid_: hallucination, error, invalid response

**Reaction**:
What a persona produced from an impression — what they said, what they did, how their beliefs moved, and which stimulus they were responding to.
_Avoid_: response, answer, output

**Persona State**:
What a persona carries between ticks: its current beliefs, its own memories, and when it last reflected. It travels with the persona wherever its turn is taken, and is never shared between personas.
_Avoid_: agent state, session, context window, history

**Memory**:
Something that happened to one persona, in its own words, with how much it mattered and when. Only that persona can retrieve it.
_Avoid_: log, record, event (a memory is written as one, but the word means the persona's recollection)

**Reflection**:
A persona consolidating what has happened to it into revised beliefs and fewer, weightier memories. It happens on a cadence and whenever beliefs move sharply.
_Avoid_: summarisation, compaction, consolidation of logs

**Character Probe**:
A question whose answer is already in a persona's own attributes, asked occasionally to see whether it still answers as itself.
_Avoid_: test, validation, sanity check

**Drift**:
A persona answering less like itself the longer a study runs. The probe measures it; it is reported per run, never silently tolerated.
_Avoid_: degradation, hallucination, decay

**Affordance**:
What a channel allows a persona to do — a forum has votes, a survey wave has only an answer. A persona may attempt anything; the channel decides what lands.
_Avoid_: permission, capability, validation rule

**Activation**:
Whether a persona takes a turn on a given tick, drawn from its involvement and the rhythm of the tick unit.
_Avoid_: sampling, scheduling, selection

**Word of Mouth**:
One persona telling another about a stimulus because it felt strongly and the two are close. It reaches the other persona as an exposure on the next tick, never in the same one.
_Avoid_: sharing, virality, broadcast

### Belief and evidence

**Construct**:
The quantity a persona's free-text response is scored on, such as purchase intent.
_Avoid_: metric, measure, question

**Anchor Set**:
Reference statements for each point of a construct's five-point scale, which a response is compared against to become a response distribution. Each category names the anchor set it uses for each construct.
_Avoid_: rubric, scale labels, prompt examples

**Anchor Provenance**:
Who wrote an anchor set's statements and where they came from — a client's own survey instrument, a published scale, or a model. It is recorded beside the version and never changes the version's identity.
_Avoid_: author, source (a persona's source is a different thing), origin

**Mapping Claim**:
That the conversion of free text into a rating distribution recovers the rating a real person gave from what that person wrote. It can be checked on human writing that carries its own rating, and says nothing about whether simulated people answer like real ones.
_Avoid_: SSR accuracy, validation, model accuracy

**Simulation Claim**:
That simulated personas' rating distributions for a product match what real people's would be. It is the claim a study's findings rest on, and it needs human answers to the same question about the same product to check.
_Avoid_: realism, fidelity, accuracy

**Digest**:
What one world produced, summarised: how personas answered where they were asked, how far their beliefs moved, what they objected to, and what could not be measured at all.
_Avoid_: summary, rollup, metrics, stats

**Unmeasured**:
Something a run did not establish, reported as such rather than as zero or left out. A study that could not score purchase intent has unmeasured adoption, not adoption of none.
_Avoid_: missing, null, n/a, unknown

**Replicate Spread**:
How far a scenario's worlds disagreed with each other. It is the study's estimate of its own variance, and the yardstick every anomaly threshold is measured against. A quantity the scenario's worlds did not all measure has no spread, and a spread of zero is a yardstick that measures nothing.
_Avoid_: error bars, noise, variance (the word alone is ambiguous here)

**Objection Cluster**:
A group of things personas said that mean the same thing, named by the one sentence nearest the middle of the group. The label is always something a persona actually wrote.
_Avoid_: theme, topic, category, insight

**Anomaly**:
A pattern in a run that a rule recognises — attention converging, opinion splitting, a concept landing flat. Rules only: nothing here is judged by a model.
_Avoid_: outlier, alert, signal, red flag

**Trace Summary**:
The five shapes of a run's record joined once and frozen — belief histories, word-of-mouth edges, grouped verbatims, event counts per kind and costs per role, each from the shape that owns it. Two summaries of one trace are identical, so a diff means a difference in the record.
_Avoid_: export, dump, UI file, snapshot

**Trajectory**:
A derived shape in `analysis`: per-tick adoption and polarization for audiences and, separately, for communities, over a scenario's worlds. Audiences and communities are plotted separately because camps and target-market splits are different findings.
_Avoid_: chart data, curve, series

**Workspace Summary**:
The first screen's numbers — studies run, spend against budget, personas simulated, reports written — derived over registry entries rather than by walking partitions. The interface displays its fields and computes nothing itself.
_Avoid_: dashboard stats, totals, rollup

**Prompt Reconstruction**:
Rebuilding the exact messages a turn sent from the recorded parts and displaying them only when the rebuilt hash matches the hash the turn carries. A prompt that cannot be rebuilt says so and why; nothing approximates one and nothing stores one.
_Avoid_: prompt log, replay (replay re-runs a study), rendering

**Disconfirming Test**:
The real-world check that would show a finding to be wrong. A finding without one cannot be made.
_Avoid_: validation, caveat, limitation

**Method Disclosure**:
The part of a report that says how the numbers were produced: which models answered, under which seeds and templates, and which engine version ran.
_Avoid_: appendix, footnote, metadata

**Adoption**:
The probability that a respondent answers 4 or 5 on the five-point purchase-intent scale, weighted across audiences by their share — the headline measure of whether a variant would be bought. It is measured in survey waves only, so a study with several waves has an adoption per wave; a purchase a persona makes on a channel is behaviour, not adoption.
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

### Models

**Pinned Model**:
The model a study names for a role, fixed for the whole run. A pin is a full specification, not a bare name: the identifier sent to the endpoint, the served identifiers it accepts as answers, whether it follows a strict output schema, whether it honours a seed, and what it costs. A study's results are a property of the models that produced them, so a model is never chosen, swapped or upgraded while a study runs.
_Avoid_: default model, preferred model, current model

**Served Model**:
The model that actually answered a call, as the response reports it — which is not always the pinned one, since a gateway or provider can substitute another. Recorded beside the pinned model on every call.
_Avoid_: requested model, backend, deployment

**Pin Failure**:
A call answered by a model other than its pinned model or that model's declared aliases. It is a failed call, not a result: an answer from an unnamed model would silently change what the study measured.
_Avoid_: model drift, mismatch warning, fallback

**Cost Source**:
Where a call's recorded cost came from — reported by the gateway, computed from a price the study declared and the usage the response reported, estimated from that price and guessed usage, known to be nothing because the answer came from the cache, or unknown. An unknown cost stays unknown rather than becoming zero, and an estimate is never recorded as a price, because a budget enforced against invented prices is not enforced.
_Avoid_: estimated cost, pricing, spend

**Completion Temperature**:
How widely a filled-in attitude is allowed to vary from the one a persona's demographics make most likely. Chosen and recorded per study, because an attitude with no variance makes every persona with the same demographics think alike, and the network then looks more opinionated than any population is.
_Avoid_: randomness, creativity, noise, sampling temperature

**Holdout Evaluation**:
Measuring how well filled-in attitudes match real ones, on people whose real attitudes were recorded and then hidden. It is the evidence for — or against — the claim that projected attitudes mean anything.
_Avoid_: validation, backtest, accuracy check
