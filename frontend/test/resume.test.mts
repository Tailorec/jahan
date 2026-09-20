import test from "node:test";
import assert from "node:assert/strict";
import { FORCE_WARNING, movedInputRefusal } from "../lib/resume.ts";

test("a refusal for a moved input is named, and is the only thing worth forcing", () => {
  const log = "run_id: x\nresume refused: population_hash moved from abc123 to def456\n";
  assert.equal(movedInputRefusal(log), "population_hash moved from abc123 to def456");
  assert.equal(movedInputRefusal("MemoryError"), null);
  assert.equal(movedInputRefusal(null), null);
  assert.equal(movedInputRefusal(undefined), null);
});

test("the warning says what forcing does before it is done", () => {
  assert.match(FORCE_WARNING, /records what it was forced past/);
});
