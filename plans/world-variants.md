# Plan: versions of a study — named, launched from the interface, compared in the atlas

Decided 2026-10-03:

- **Personas see what a version tests.** The concept a persona is shown is the scenario's own variant description
  and its price, not the brief's description alone — before this, every price or wording variant showed identical
  text, so a sweep could never separate them.
- **A version has a name, recorded by the engine.** `Scenario.label` ("Budget $9") is presentation: kept out of
  every identity hash, so naming or renaming never makes a different world. Its worlds read "Budget $9 · seed 1".
- **New study launches versions.** A person varies price, description wording, channels, horizon and survey
  schedule between versions, and chooses how many seeds; the engine runs them as one sweep under one budget.
- **The atlas leads with the decision.** Versions ranked by adoption with their seed spread, a verdict on whether
  the ranking beats chance, intent over waves per version, then the version-by-seed grid.

## Phase 1 — personas see the version's description and price (engine)
- [x] The concept stimulus is the scenario's variant description and its price.
- [x] ADR 0051; the code-review benchmark write-up corrected (it showed no price).

## Phase 2 — a version's name (engine)
- [x] `Scenario.label`, optional, excluded from the scenario hash; the grid and the interface can set it.
- [x] A run serves each world's label and seed index; a rename is recorded beside the run and served over it.

## Phase 3 — launching versions from the interface (engine + web)
- [ ] The study request carries versions (label + what differs) and a seed count; the web writes a grid and
      launches `sweep run`; a single version still launches `concepts run`.

## Phase 4 — New study: versions
- [ ] A "Versions" section: add, name and edit versions; the world count and a call estimate before launch.

## Phase 5 — the atlas, decision-first
- [ ] Ranked versions with seed spread, a verdict, intent over waves per version, the grid; one-world runs explain
      themselves and offer to launch versions.

## Phase 6 — names everywhere
- [ ] World picker, run bar, run details, report and trace name worlds by label and seed.
