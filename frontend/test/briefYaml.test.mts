import test from "node:test";
import assert from "node:assert/strict";
import { briefToYaml, formFromBrief, parseBriefYaml, type BriefForm } from "../lib/briefYaml.ts";

const form = (over: Partial<BriefForm> = {}): BriefForm => ({
  product: { name: "Protein water", category: "beverage_protein", description: "Clear water with 20g whey isolate" },
  price: "2.49", currency: "USD",
  claims: [{ text: "20g protein with zero sugar", source: "user_asserted", evidence_url: "https://example.com/panel" }],
  competitors: [{ name: "Clear whey shooter", price: "2.99", currency: "USD", claims: "Shooter format, 25g protein" }],
  target: "US urban adults 25-40",
  audiences: [{ name: "gym_regulars", share: "0.6", filters: { exercise_frequency: { kind: "exactly", value: "3_plus_weekly" } } }],
  assumptions: [{ text: "Respondents tell clear from milky", source: "assumed" }],
  ontologyVersion: "1.0.0",
  ...over,
});

test("a nested audience filter stays inside its audience", () => {
  const parsed = parseBriefYaml(briefToYaml(form())) as { audiences: { attribute_filters: Record<string, string> }[] };
  assert.deepEqual(parsed.audiences[0].attribute_filters, { exercise_frequency: "3_plus_weekly" });
  assert.deepEqual(Object.keys(parsed.audiences[0]).sort(), ["attribute_filters", "name", "share"]);
});

test("text the form takes is text the engine reads, however it is punctuated", () => {
  const awkward = [
    "Kellogg's \"protein\" water", "- leads with a dash", "[bracketed]", "# not a comment", "ends with a colon:",
    "two\nlines", "007", "true", "null", "1.0.0", "2024-01-01", "yes", "~", "*starred", "&anchored", "!tagged", "@at", "%pct", "  padded  ",
  ];
  for (const text of awkward) {
    const parsed = parseBriefYaml(briefToYaml(form({
      product: { name: text, category: "beverage_protein", description: text },
      claims: [{ text, source: "assumed", evidence_url: "" }],
      target: text,
    }))) as { product: { name: string; description: string }; claims: { text: string }[]; target_market: string };
    assert.equal(parsed.product.name, text, `name ${JSON.stringify(text)}`);
    assert.equal(parsed.claims[0].text, text, `claim ${JSON.stringify(text)}`);
    assert.equal(parsed.target_market, text, `target ${JSON.stringify(text)}`);
  }
});

test("an assumption stays as assumed as it was stated", () => {
  const parsed = parseBriefYaml(briefToYaml(form({
    assumptions: [{ text: "taken as true", source: "assumed" }, { text: "the author asserts", source: "user_asserted" }],
  }))) as { assumptions: { text: string; source: string }[] };
  assert.deepEqual(parsed.assumptions.map((a) => a.source), ["assumed", "user_asserted"]);
});

test("loading a brief and writing it back drops nothing it stated", () => {
  const brief = {
    product: { name: "P", category: "c", description: "d" },
    price: { amount: 2.49, currency: "EUR" },
    claims: [{ id: "C1", text: "a", source: "public_source" as const, evidence_url: "https://x.example/y" }],
    competitors: [
      { name: "Shooter", price: { amount: 2.99, currency: "GBP" }, claims: ["25g", "shot format"] },
      { name: "Electrolyte water", price: null, claims: [] },
    ],
    target_market: "t",
    audiences: [{ name: "a", share: 1, attribute_filters: { exercise_frequency: { kind: "exactly", value: "3_plus_weekly" } } }],
    assumptions: [{ text: "x", source: "assumed" as const }],
    ontology_version: "1.0.0",
  };
  const back = parseBriefYaml(briefToYaml(formFromBrief(brief))) as Record<string, unknown>;
  assert.deepEqual(back.price, { amount: 2.49, currency: "EUR" });
  assert.deepEqual(back.competitors, [
    { name: "Shooter", price: { amount: 2.99, currency: "GBP" }, claims: ["25g", "shot format"] },
    { name: "Electrolyte water" },
  ]);
  assert.deepEqual(back.assumptions, [{ text: "x", source: "assumed" }]);
  assert.deepEqual(back.claims, [{ text: "a", source: "public_source", evidence_url: "https://x.example/y" }]);
});

test("a share left blank is left out, not written as zero", () => {
  const parsed = parseBriefYaml(briefToYaml(form({ audiences: [{ name: "a", share: "", filters: {} }] }))) as
    { audiences: Record<string, unknown>[] };
  assert.equal("share" in parsed.audiences[0], false);
});

test("an audience filter keeps the form the brief stated it in: a value, a list, a range", () => {
  const brief = {
    product: { name: "P", category: "c", description: "d" },
    price: { amount: 1, currency: "USD" },
    claims: [{ id: "C1", text: "a", source: "assumed" as const, evidence_url: null }],
    competitors: [],
    target_market: "t",
    audiences: [
      { name: "a", share: 0.5, attribute_filters: { att_ai: ["Skeptical", "Opposed"] } },
      { name: "b", share: 0.5, attribute_filters: { years_experience: { range: ["6-10", "20+"] as [string, string] }, age: 25, sex: "female" } },
    ],
    assumptions: [],
    ontology_version: "1.0.0",
  };
  const back = parseBriefYaml(briefToYaml(formFromBrief(brief as never))) as { audiences: { attribute_filters: unknown }[] };
  assert.deepEqual(back.audiences[0].attribute_filters, { att_ai: ["Skeptical", "Opposed"] });
  assert.deepEqual(back.audiences[1].attribute_filters, { years_experience: { range: ["6-10", "20+"] }, age: 25, sex: "female" });
});
