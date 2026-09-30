import test from "node:test";
import assert from "node:assert/strict";
import {
  CHANNELS, CHANNEL_GUIDE, cachedShards, defaultAnchor, defaultSources, gateRequest, leftOut, shardsFor, parseSeeds, problems, studyRequest, womAlone,
  type AnchorCatalogue, type CorpusInfo, type StudyForm,
} from "../lib/study.ts";

const form = (over: Partial<StudyForm> = {}): StudyForm => ({
  n: "500", horizon: "3", tickUnit: "day", seeds: "4021,917731", budget: "1.0",
  channels: ["social_feed"], surveyEvery: "2", launchReach: "0.10", recsysEmbedModel: "twhin-bert-base", anchorVersion: "purchase_intent=v2",
  model: "amazon.nova-micro-v1:0", embedModel: "amazon.titan-embed-text-v2:0",
  populationSeed: "4022", shards: ["0000", "0004", "0005"], sources: ["wiki", "gss", "amazon", "stackoverflow"],
  priceChatIn: "0.035", priceChatOut: "0.14", priceEmbedIn: "0.02", validation: "",
  ...over,
});

const corpus: CorpusInfo = {
  available: true,
  shards: [
    { id: "0000", rows: 100000, bytes: 1, cached: true },
    { id: "0001", rows: 100000, bytes: 1, cached: false },
    { id: "0004", rows: 100000, bytes: 1, cached: true },
    { id: "0009", rows: 100000, bytes: 1, cached: false },
  ],
  sources: { wiki: 1, gss: 1, stackoverflow: 1, synthetic: 4 },
  measured_sources: ["gss", "stackoverflow", "wiki"],
};

test("a real study names the corpus it draws from, the draw's seed and what the models cost", () => {
  const body = studyRequest(form(), "brief: yaml", null);
  assert.deepEqual(body.shards, ["0000", "0004", "0005"]);
  assert.deepEqual(body.sources, ["wiki", "gss", "amazon", "stackoverflow"]);
  assert.equal(body.population_seed, 4022);
  assert.equal(body.price_chat_in, 0.035);
  assert.equal(body.price_chat_out, 0.14);
  assert.equal(body.price_embed_in, 0.02);
  assert.equal(body.model, "amazon.nova-micro-v1:0");
  assert.equal(body.fake, false);
  assert.deepEqual(body.anchor_versions, ["purchase_intent=v2"]);
});

test("the endpoint and its key are never a field of a study", () => {
  const text = JSON.stringify([studyRequest(form(), "b", null), gateRequest(form(), "b", null)]);
  assert.doesNotMatch(text, /api[_-]?key|base_url|endpoint|token|secret/i);
});

test("a price the form leaves blank is not sent, and a half-given chat price is not sent as half", () => {
  const blank = studyRequest(form({ priceChatIn: "", priceChatOut: "", priceEmbedIn: "" }), "b", null);
  for (const key of ["price_chat_in", "price_chat_out", "price_embed_in"]) assert.equal(key in blank, false);
  const half = studyRequest(form({ priceChatIn: "0.035", priceChatOut: "" }), "b", null);
  assert.equal("price_chat_in" in half, false);
  assert.equal("price_chat_out" in half, false);
});

test("a blank population seed leaves the draw to the engine's default", () => {
  assert.equal("population_seed" in studyRequest(form({ populationSeed: "" }), "b", null), false);
});

test("a real study's preview reads the real corpus with the same pins and choices", () => {
  const gate = gateRequest(form(), "b", null);
  assert.equal(gate.fake, false);
  assert.equal(gate.seed, 4022);
  assert.equal(gate.model, "amazon.nova-micro-v1:0");
  assert.deepEqual(gate.shards, ["0000", "0004", "0005"]);
  assert.deepEqual(gate.sources, ["wiki", "gss", "amazon", "stackoverflow"]);
});

test("the preview no longer hard-codes a seed the study is not using", () => {
  assert.equal(gateRequest(form({ populationSeed: "917731" }), "b", null).seed, 917731);
  assert.equal(gateRequest(form({ populationSeed: "" }), "b", null).seed, 4021);
});

test("the corpus is offered from what is cached, and defaults to the sources a study can actually admit", () => {
  assert.deepEqual(cachedShards(corpus), ["0000", "0004"]);
  assert.deepEqual(defaultSources(corpus), ["gss", "stackoverflow", "wiki"]);
  assert.equal(defaultSources(corpus).includes("synthetic"), false);
  assert.deepEqual(cachedShards(null), []);
  assert.deepEqual(defaultSources(null), []);
});

test("shards follow the sources: a study reads the shards its people are in, and says who unticked ones leave out", () => {
  const release: CorpusInfo = {
    available: true, measured_sources: ["gss", "stackoverflow", "wiki"], sources: {},
    shards: [
      { id: "0000", rows: 3, bytes: 1, cached: true, sources: { wiki: 3 } },
      { id: "0004", rows: 3, bytes: 1, cached: true, sources: { stackoverflow: 2, amazon: 1 } },
      { id: "0005", rows: 3, bytes: 1, cached: true, sources: { gss: 2, stackoverflow: 1 } },
      { id: "0006", rows: 3, bytes: 1, cached: true, sources: { synthetic: 3 } },
      { id: "0007", rows: 3, bytes: 1, cached: false },
    ],
  };
  assert.deepEqual(shardsFor(release, ["gss", "stackoverflow"]), ["0004", "0005"]);
  assert.deepEqual(shardsFor(release, []), []);
  assert.deepEqual(leftOut(release, ["0005"], ["gss", "stackoverflow"]), { stackoverflow: 2 });
  assert.deepEqual(leftOut(release, ["0004", "0005"], ["gss", "stackoverflow"]), {});
});

test("the scale defaults to one that passed its check, never to whatever was first", () => {
  const catalogue: AnchorCatalogue = { anchors: [], defaults: ["purchase_intent=v2"] };
  assert.equal(defaultAnchor(catalogue), "purchase_intent=v2");
  assert.equal(defaultAnchor({ anchors: [], defaults: [] }), "");
  assert.equal(defaultAnchor(null), "");
});

test("a real study's mistakes are named before anything is sent", () => {
  assert.deepEqual(problems(form()), []);
  assert.match(problems(form({ model: "" })).join(" "), /chat model/);
  assert.match(problems(form({ shards: [] })).join(" "), /shard/);
  assert.match(problems(form({ sources: [] })).join(" "), /source/);
  assert.match(problems(form({ priceChatIn: "0.035", priceChatOut: "" })).join(" "), /both/);
  assert.match(problems(form({ priceEmbedIn: "-1" })).join(" "), /negative/);
  assert.match(problems(form({ populationSeed: "abc" })).join(" "), /seed/);
  assert.match(problems(form({ populationSeed: "-3" })).join(" "), /seed/);
});

test("replicate seeds are read as the numbers they are", () => {
  assert.deepEqual(parseSeeds("4021, 917731,"), [4021, 917731]);
});

test("every channel a study can tick says why one would choose it, and the survey room is not offered", () => {
  assert.deepEqual(Object.keys(CHANNEL_GUIDE).sort(), [...CHANNELS].sort());
  assert.deepEqual([...CHANNELS].sort(), ["forum", "social_feed", "wom"]);
  assert.match(CHANNEL_GUIDE.social_feed.use, /spreads/);
  assert.match(CHANNEL_GUIDE.forum.use, /polarization/);
  assert.match(CHANNEL_GUIDE.wom.use, /launch reach/);
});

test("the launch body carries the ticked channels, the survey interval and the feed's ranking model", () => {
  const body = studyRequest(form(), "b", null);
  assert.deepEqual(body.channels, ["social_feed"]);
  assert.equal(body.survey_every, 2);
  assert.equal(body.recsys_embed_model, "twhin-bert-base");
  assert.equal("launch_reach" in body, false);
  assert.equal("elicits" in body, false);
  assert.equal("channel" in body, false);
});

test("the launch reach is sent only for word of mouth alone", () => {
  assert.equal(womAlone(["wom"]), true);
  assert.equal(womAlone(["wom", "forum"]), false);
  assert.equal(studyRequest(form({ channels: ["wom"], launchReach: "0.2" }), "b", null).launch_reach, 0.2);
  assert.equal("launch_reach" in studyRequest(form({ channels: ["wom", "forum"], launchReach: "0.2" }), "b", null), false);
  assert.equal("recsys_embed_model" in studyRequest(form({ channels: ["forum"] }), "b", null), false);
});

test("a feed without its ranking model, or a launch reach that is no share, is named before anything is sent", () => {
  assert.deepEqual(problems(form()), []);
  assert.match(problems(form({ recsysEmbedModel: " " })).join(" "), /ranks by its own model/);
  assert.deepEqual(problems(form({ channels: ["forum"], recsysEmbedModel: "" })), []);
  assert.match(problems(form({ channels: ["wom"], launchReach: "1.5" })).join(" "), /launch reach/);
  assert.deepEqual(problems(form({ channels: [], launchReach: "1.5" })), [], "a hidden field is never a problem");
});
