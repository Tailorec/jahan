import test from "node:test";
import assert from "node:assert/strict";
import { refusalText } from "../lib/refusal.ts";

test("a refusal keeps the sentence the engine wrote", () => {
  assert.equal(refusalText({ detail: "attribute 'agee' is not in the corpus; did you mean 'age_bracket'?" }, "x"), "attribute 'agee' is not in the corpus; did you mean 'age_bracket'?");
});

test("a validation refusal lists each field and why, without the word body", () => {
  const text = refusalText({ detail: [{ loc: ["body", "n"], msg: "Input should be greater than or equal to 1" }] }, "x");
  assert.equal(text, "n: Input should be greater than or equal to 1");
});

test("the engine's own sentence wins over the status code", () => {
  assert.equal(refusalText({ error: "no record of run nope" }, "/api/runs/nope: 404"), "no record of run nope");
  assert.equal(refusalText(null, "/api/runs/nope: 404"), "/api/runs/nope: 404");
  assert.equal(refusalText({ detail: "   " }, "fallback"), "fallback");
});
