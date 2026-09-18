# PRD — M11 `report`: turning findings into documents

## Problem Statement

Everything the engine measures now has an owner except the document a person actually reads. Findings and
digests exist as objects; nothing turns them into something a user can open, and nothing guarantees that the
markdown a human reads and the JSON a page consumes say the same thing.

The risk here is not complexity — this module is deliberately thin — it is smuggling. A renderer that can
compute anything can introduce a claim that no trace supports, and that claim will look exactly like the
measured ones around it. The previous design put the trust guard in the renderer, where it could only be
tested by rendering, and computed objection clusters here as well as in the digest builder.

A second risk is provenance. A report travels: it is the artefact that leaves the machine and reaches someone
who has no access to the run. The first real study's report named neither its seeds nor the engine commit that
produced it, so two reports from different code were indistinguishable (ADR 0042).

## Solution

One call: `render(findings, digests, pack) -> Report`.

The module formats and nothing else. Every claim arrives as a `Finding` that `analysis` already validated —
evidence resolved, disconfirming test present — so this module cannot introduce one. It emits markdown for a
person and JSON for the mockup pages, from one pass over the same finding set, so the two cannot diverge.

Three things appear in every report without exception: the run's single `TrustStatement`, the recommended
real-world validation section, and the method disclosure — model pins, seeds, template versions and the engine
commit. Where a digest reports adoption as not measurable, the report says so in the place adoption would have
been, rather than omitting the line.

Rendering the same findings twice is byte-identical, so a diff between two reports is a difference in
findings.

## User Stories

1. As a user, I want a markdown report I can read and a JSON report a page can consume, carrying the same
   findings, so neither can quietly say more than the other.
2. As a researcher, I want every report to state the run's calibration once, so no finding appears better
   evidenced than the engine is.
3. As a researcher, I want every report to end with the real-world validation it recommends, so the reader is
   told what would confirm it.
4. As a researcher, I want the method disclosure to name the pins, seeds, templates and engine commit, so a
   report that travels can still be traced to its run.
5. As an analyst, I want unmeasured quantities stated as unmeasured where they would have appeared, so a
   missing adoption number is visible rather than absent.
6. As a maintainer, I want rendering to introduce no computation, so the renderer cannot make a claim.
7. As a maintainer, I want two renders of one finding set to be byte-identical, so a report diff means
   something.
8. As a user, I want each finding rendered with its evidence ids and its disconfirming test, so I can check it.
9. As a user, I want the assumption ledger surfaced, so what the study took on faith is in front of me.
10. As a maintainer, I want the JSON shape versioned with the contract, so the pages that consume it break
    loudly rather than silently.

## Implementation Decisions

**Interface.** `render(findings, digests, pack) -> Report`, with `Report` the existing contract.

**One pass, two formats.** Markdown and JSON are produced from the same intermediate, never by two renderers.

**No computation.** The module may sort, group and format; it may not derive. A boundary test asserts the
package calls nothing from `analysis` and computes no statistic of its own.

**Provenance.** Run id, configuration hash, seeds and engine commit are carried into both formats.

**Determinism.** Stable ordering everywhere — findings by kind then id, clusters by size then label — so
byte-identical renders are achievable rather than accidental.

**Test posture.** Boundary tests through `render` with hand-built finding sets; no network, no model.

## Testing Decisions

- Markdown and JSON contain the same finding ids, and neither carries a finding the other omits.
- The validation section, the trust statement and the method disclosure are present in every rendered report.
- Rendering one finding set twice produces byte-identical output in both formats.
- A digest whose adoption is unmeasured renders a line saying so, rather than omitting it.
- The package computes no statistic, asserted over its imports and its code.
- Every rendered finding shows its evidence ids and its disconfirming test.
- The JSON carries the contract version it was rendered under.

## Out of Scope

Deriving anything (`analysis`, module 10). Deciding which findings matter — the order is stable, not curated.
Entrypoints and file writing (`cli`, module 12). Templates for a client's own branding, which is a product
question and not an engine one.

## Further Notes

The mockup pages consume the JSON, so that shape is a real contract rather than a convenience, and it is
versioned accordingly.
