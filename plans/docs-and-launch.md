# Plan: documentation and public launch

Jahan goes public as `Tailorec/jahan`, source-available under FSL-1.1-ALv2 (copyright Faishal Manzar), with
its documentation on GitHub Pages built by Material for MkDocs. Everything stays public: ADRs, PRDs,
evaluations and plans. Docs explain what the engine is and how it works; running it is one page, not the focus.
Decided 2026-10-02.

## Phase 1 — license and site skeleton
- [x] `LICENSE.md`: the official FSL-1.1-ALv2 template, notice filled in, otherwise verbatim.
- [x] License declared in `pyproject.toml` and `frontend/package.json`.
- [x] `mkdocs.yml` (Material), `docs/index.md`, the glossary included from `CONTEXT.md`, not copied.
- [x] `.github/workflows/docs.yml` builds on every PR and deploys `master` to GitHub Pages.
- [x] `README.md`: pitch, what makes it different, honest-results callout, data and license.

## Launch blockers (decisions owed)
- [ ] GPL dependencies: `igraph` (GPL-2.0+) and `leidenalg` (GPL-3.0+) in `population/_communities.py`.
- [ ] A fresh clone cannot run a fake study: `examples/` and `ontologies/` are not in the repository but the
      quickstart and the CLI/interface tests need a brief and an ontology.
- [x] Root clean-up: the superseded first-draft `ARCHITECTURE.md` and `OSSARCH.md` (open-core plan, old
      module names) removed; the current `FINAL_ARCH.md` and `SALVAGE.md` moved into `docs/`.
- [ ] `docs/running-a-real-study.md` names `examples/` files that are no longer in the repository.
- [ ] Naming: the package is `simcore` and the interface says ConsumerSim; the repository is Jahan.
- [ ] Contributor License Agreement before the first outside pull request.

## Phase 2 — README hero
- [ ] A 15-second GIF of the World tab replaying a fake study (no corpus-derived content).
- [ ] Three screenshots: world, numbers, trace. A 60-second quickstart once a fake study runs from a clone.

## Phase 3 — concepts (`docs/concepts/`)
- [ ] overview, study and brief, personas and population, social network, worlds and scenarios, channels,
      survey waves, beliefs and memory, measuring intent, the trace, trust levels, limitations.

## Phase 4 — how it works (`docs/how-it-works/`)
- [ ] One page per `simcore` module, drawn from its ADRs and PRD; architecture and testing pages.

## Phase 5 — research (`docs/research/`)
- [ ] Methodology and threats to validity, related work, an index of evaluations with one-line results.

## Phase 6 — reference (`docs/reference/`)
- [ ] Brief format, trace events, run artefacts, HTTP API (from OpenAPI), CLI, configuration.

## Phase 7 — community and launch
- [ ] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CITATION.cff`, `CHANGELOG.md`, issue and PR templates.
- [ ] Show HN, r/MachineLearning, r/LocalLLaMA, an X thread around the GIF, a write-up of the holdout result.
