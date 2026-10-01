import test from "node:test";
import assert from "node:assert/strict";
import { runKind, runLabel, runName, runWhen } from "../lib/runs.ts";

test("a run says when it began from the engine's record, never from its random id", () => {
  assert.notEqual(runWhen({ created_at: "2026-10-01T09:30:00+00:00" }), "");
  assert.equal(runWhen({ created_at: null }), "");
  assert.equal(runWhen({}), "");
});

test("a run is named by its product, else its category, and says what it was", () => {
  const base = { run_id: "run-01k6m15qp0000000000000000", status: "completed", created_at: "2026-10-01T09:30:00+00:00" };
  assert.equal(runName({ ...base, product: "NestEgg Kids" }), "NestEgg Kids");
  assert.equal(runName({ ...base, category: "kids_savings" }), "kids savings");
  assert.equal(runName(base), "unnamed run");
  assert.equal(runKind({ ...base, scenarios: [{ channels: [] }] }), "concept test");
  assert.equal(runKind({ ...base, scenarios: [{ channels: ["social_feed", "wom"] }] }), "feed + word of mouth");
  assert.equal(runKind(base), "population draw");
  assert.match(runLabel({ ...base, product: "NestEgg Kids", personas: 60, scenarios: [{ channels: ["forum"] }] }), /^NestEgg Kids · forum · 60 personas · .+ · done$/);
});
