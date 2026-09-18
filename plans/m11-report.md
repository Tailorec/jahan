# Plan: M11 `report` — turning findings into documents

> Source PRD: `docs/prd/M11-report.md`
> Binding decisions: ADR 0042 (a report is derived from the record and carries what produced it), ADR 0038 (unmeasured is stated, not omitted), ADR 0008 (trust stays uncalibrated, stated once per run). `CONTEXT.md` (Method Disclosure, Disconfirming Test, Unmeasured, Finding, Trust Level, Assumption Ledger). Where `FINAL_ARCH.md` §5.11 disagrees, the ADRs win.

## Architectural decisions

Durable across every phase:

- **One call** — `render(findings, digests, pack) -> Report`. Findings arrive already validated by `analysis`; this module formats them.
- **It cannot make a claim** — the package derives no statistic and calls nothing from `analysis`. It may sort, group and format; it may not compute.
- **One pass, two formats** — markdown for a person and JSON for the pages, produced from one intermediate, so they cannot diverge.
- **Three things always appear** — the run's single trust statement, the recommended real-world validation, and the method disclosure naming pins, seeds, templates and the engine commit.
- **Unmeasured is printed** — where adoption would have appeared, a report that has none says so in that place rather than dropping the line.
- **Deterministic** — stable ordering everywhere, so two renders of one finding set are byte-identical and a diff means a difference in findings.
- **The JSON is a contract** — the mockup pages consume it, so it carries the contract version it was rendered under.
- **Test posture** — boundary tests through `render` with hand-built finding sets; no network, no model, no trace.

---

## Phase 1: One pass, two formats

**User stories**: 1, 10

### What to build

The module's shape: findings and digests in, a `Report` carrying markdown and JSON out, both produced from one intermediate over the same finding set. The JSON carries the contract version, so a page consuming it breaks loudly rather than silently when the shape moves.

### Acceptance criteria

- [x] `render` returns a report carrying both formats, built from one intermediate
- [x] Markdown and JSON contain the same finding ids, and neither holds one the other omits
- [x] The JSON records the contract version it was rendered under
- [x] A report with no findings renders both formats and says so plainly
- [x] Rendering reads nothing but what it was given

---

## Phase 2: What every report carries

**User stories**: 2, 3, 4

### What to build

The parts that appear whatever the study found. The run's calibration, stated once. The real-world validation the report recommends. And the method disclosure: model pins, seeds, template versions and the engine commit that produced it, so a report that travels can still be traced to its run.

### Acceptance criteria

- [x] Every rendered report carries the run's trust statement exactly once
- [x] Every rendered report ends with its recommended real-world validation
- [x] The method disclosure names the pins, seeds, template versions and engine commit
- [x] A report whose run was forced across engine versions says so
- [x] Neither format can be rendered without all three parts, asserted by removing each

---

## Phase 3: Findings on the page

**User stories**: 5, 8, 9

### What to build

What a reader sees per finding: the statement, its evidence trace ids, its confidence, and the disconfirming test that would show it wrong. Beside them the assumption ledger, so what the study took on faith is in front of the reader, and any quantity the digest could not measure — stated where it would have appeared.

### Acceptance criteria

- [x] Every rendered finding shows its evidence ids and its disconfirming test
- [x] The assumption ledger appears, including what the brief left unstated
- [x] A digest with unmeasured adoption renders a line saying so, with the reason, where adoption would be
- [x] A finding's confidence renders beside it, and the run's calibration never does
- [x] Objection clusters render their quoted label, never a paraphrase

---

## Phase 4: Determinism

**User stories**: 7

### What to build

Stable order everywhere, so a report is a function of its findings. Findings by kind then id, clusters by size then label, digests by scenario then seed — nothing ordered by a set's iteration or a dictionary's insertion.

### Acceptance criteria

- [x] Rendering one finding set twice produces byte-identical markdown and byte-identical JSON
- [x] Shuffling the input findings produces the same output
- [x] Ordering rules are explicit in the code rather than incidental
- [x] Two reports differing only in one finding differ only where that finding appears

---

## Phase 5: Nothing computed here

**User stories**: 6

### What to build

The guarantee that the renderer cannot smuggle a claim. The package imports nothing from `analysis`, computes no statistic of its own, and a test asserts both over the module — the previous design put the trust guard in the renderer, where it could only be tested by rendering.

### Acceptance criteria

- [x] The package imports nothing from `analysis`, asserted over its imports
- [x] No arithmetic on findings or digests beyond formatting, asserted over the module
- [x] A number in the report always appears in the digest or finding it came from
- [x] `FINAL_ARCH.md` §5.11 and `CONTEXT.md` describe what was built
