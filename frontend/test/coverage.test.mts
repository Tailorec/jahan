import test from "node:test";
import assert from "node:assert/strict";
import { coverageLabel, coverageBand, percent, shouldPoll, type CoverageCell } from "../lib/coverage.ts";

const cell = (share: number | null, present = 0, total = 0): CoverageCell => ({ present, total, share });

test("an attribute is answered by most above half, by some down to a tenth, by few below", () => {
  assert.equal(coverageBand(cell(0.894)), "most");
  assert.equal(coverageBand(cell(0.5)), "most");
  assert.equal(coverageBand(cell(0.37)), "some");
  assert.equal(coverageBand(cell(0.1)), "some");
  assert.equal(coverageBand(cell(0.0004)), "few");
  assert.equal(coverageBand(cell(null)), "unknown");
  assert.equal(coverageBand(undefined), "unknown");
});

test("a share is named the way it is read, and a tiny one is not rounded to nothing", () => {
  assert.equal(percent(0.894359), "89%");
  assert.equal(percent(0.0371), "3.7%");
  assert.equal(percent(0.0004), "0.04%");
  assert.equal(percent(0), "0%");
});

test("the label carries the count it came from", () => {
  assert.equal(coverageLabel(cell(0.894359, 178735, 199847)), "answered by most · 89% populated · 178,735 of 199,847 recorded personas");
  assert.equal(coverageLabel(undefined), "coverage unknown");
});

test("the page polls only while the engine is counting", () => {
  assert.equal(shouldPoll(null), true);
  assert.equal(shouldPoll({ available: false, state: "building" }), true);
  assert.equal(shouldPoll({ available: true, state: "ready" }), false);
  assert.equal(shouldPoll({ available: false, state: "failed", detail: "x" }), false);
  assert.equal(shouldPoll({ available: false, state: "no_corpus" }), false);
});
