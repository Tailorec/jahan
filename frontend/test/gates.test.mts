import test from "node:test";
import assert from "node:assert/strict";
import { explainGate, explainRelaxation, gateMeter } from "../lib/gates.ts";

test("a categorical gate says the chance, the rule, and keeps the statistic to recompute it", () => {
  const words = explainGate({ kind: "categorical", attribute: "region", chi_square: 3.21, degrees_of_freedom: 4, p_value: 0.523, significance_level: 0.05, passed: true, reference: "design" }, () => "Region");
  assert.equal(words.title, "Region");
  assert.match(words.result, /52% of the time/);
  assert.match(words.rule, /above 5%\./);
  assert.equal(words.raw, "χ² 3.21 · dof 4 · p 0.523");
});

test("an ordinal gate reads similarity against its threshold", () => {
  const words = explainGate({ kind: "ordinal", attribute: "age_bracket", ks_statistic: 0.07, ks_similarity: 0.93, similarity_threshold: 0.8, passed: true, reference: "design" });
  assert.match(words.result, /Similarity 0\.93: the two spreads are never more than 7% apart/);
  assert.match(words.rule, /0\.80 or more/);
});

test("graph gates are floors, each in its own words", () => {
  assert.match(explainGate({ kind: "graph", check: "connectivity", measured: 0.96, threshold: 0.9, passed: true, reference: "design" }).result, /96% of personas/);
  assert.match(explainGate({ kind: "graph", check: "degree_shape", measured: 4.2, threshold: 3, passed: true, reference: "design" }).result, /4\.2× the average/);
});

test("a relaxation says what was loosened and what it cost", () => {
  const text = explainRelaxation({ audience: "retirees", rung: "drop_filter", attribute: "region", rows_before: 41, rows_after: 912, share_achieved: 1 });
  assert.equal(text, "retirees: dropped the region filter to find enough people — 41 → 912 eligible, 100% of its share reached.");
});

test("a vanishing chance is said as one, not rounded to zero", () => {
  const words = explainGate({ kind: "categorical", attribute: "region", chi_square: 21.7, degrees_of_freedom: 4, p_value: 0.0002, significance_level: 0.05, passed: false, reference: "design" });
  assert.match(words.result, /less than 0\.1% of the time/);
});

test("a meter puts each result against its pass line", () => {
  const chance = gateMeter({ kind: "categorical", p_value: 0.28, significance_level: 0.05, passed: true, reference: "design" });
  assert.deepEqual([chance.value, chance.line, chance.max, chance.short], [0.28, 0.05, 1, "chance 28% · needs above 5%"]);
  assert.equal(gateMeter({ kind: "ordinal", ks_similarity: 0.99, similarity_threshold: 0.8, passed: true, reference: "design" }).short, "similarity 0.99 · needs 0.80+");
  const hubs = gateMeter({ kind: "graph", check: "degree_shape", measured: 4, threshold: 3, passed: true, reference: "design" });
  assert.equal(hubs.short, "4.0× · needs 3.0×+");
  assert.equal(hubs.max, 5);
});
