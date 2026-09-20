/* What a person configures to launch a study, and how it becomes the request the engine takes.

   Kept apart from the page so the mapping from a form to the API is a plain function that can be tested,
   the way `briefYaml` is. The inputs are the ones the command line takes for a study: who can be drawn
   (shards, sources, the draw's seed), which models answer and what they cost, and what is asked. The endpoint
   and its key are the server's environment and are never a field here. */

export interface CorpusShard { id: string; rows: number | null; bytes: number | null; cached: boolean }
export interface CorpusInfo {
  available: boolean;
  shards: CorpusShard[];
  sources: Record<string, number>;
  measured_sources: string[];
}
export interface AnchorInfo {
  construct: string;
  version: string;
  anchor_set_id: string | null;
  embed_model_id: string | null;
  checked: boolean;
  passed: boolean;
  unchanged_since_check: boolean | null;
  detail: string;
}
export interface AnchorCatalogue { anchors: AnchorInfo[]; defaults: string[] }

export const CHANNELS = ["survey_room", "social_feed", "forum", "wom"] as const;
export type ChannelName = (typeof CHANNELS)[number];

export interface StudyForm {
  mode: "fake" | "real";
  n: string;
  horizon: string;
  tickUnit: string;
  seeds: string;
  budget: string;
  channel: ChannelName;
  elicits: string;
  anchorVersion: string;
  model: string;
  embedModel: string;
  populationSeed: string;
  shards: string[];
  sources: string[];
  priceChatIn: string;
  priceChatOut: string;
  priceEmbedIn: string;
  validation: string;
}

/* Every shard that is actually cached: the draw reads only what the machine holds, named explicitly so the
   draw does not depend on which machine it ran on. */
export function cachedShards(corpus: CorpusInfo | null): string[] {
  return (corpus?.shards ?? []).filter((s) => s.cached).map((s) => s.id);
}

/* The sources a study can admit. A persona may not have synthesized demographics, so a draw that reaches
   synthetic rows is refused after it is built; the measured sources are the ones worth defaulting to. */
export function defaultSources(corpus: CorpusInfo | null): string[] {
  return corpus?.measured_sources ?? [];
}

/* The scale a study should start on: the newest version that passed its check. */
export function defaultAnchor(catalogue: AnchorCatalogue | null, construct = "purchase_intent"): string {
  const found = catalogue?.defaults.find((d) => d.startsWith(`${construct}=`));
  return found ?? "";
}

function number(value: string): number | undefined {
  const text = value.trim();
  if (text === "") return undefined;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function parseSeeds(value: string): number[] {
  return value.split(",").map((part) => part.trim()).filter(Boolean).map(Number);
}

/* What is wrong with a real study's inputs, in words, before anything is sent. The engine refuses the same
   things; saying so here saves a round trip and points at the field. Empty when the form is sound. */
export function problems(form: StudyForm): string[] {
  const found: string[] = [];
  if (form.mode === "fake") return found;
  if (!form.model.trim() || !form.embedModel.trim()) found.push("Name the chat model and the embedding model to pin.");
  if (form.shards.length === 0) found.push("Choose at least one cached shard to draw from.");
  if (form.sources.length === 0) found.push("Choose at least one persona source to admit.");
  const inRate = number(form.priceChatIn);
  const outRate = number(form.priceChatOut);
  if ((inRate === undefined) !== (outRate === undefined)) found.push("A chat price needs both its input and output rate.");
  for (const [label, value] of [["chat input price", inRate], ["chat output price", outRate], ["embedding price", number(form.priceEmbedIn)]] as const) {
    if (value !== undefined && value < 0) found.push(`The ${label} cannot be negative.`);
  }
  const seed = number(form.populationSeed);
  if (form.populationSeed.trim() !== "" && (seed === undefined || !Number.isInteger(seed) || seed < 0)) {
    found.push("The population seed is a whole number, zero or more.");
  }
  return found;
}

/* The request that starts a study. A fake study sends only what it always did; a real one also names the
   corpus it draws from, the draw's seed and what the models cost. */
export function studyRequest(form: StudyForm, briefYaml: string, evidence: unknown): Record<string, unknown> {
  const body: Record<string, unknown> = {
    brief_yaml: briefYaml, evidence_json: evidence,
    n: Number(form.n), horizon: Number(form.horizon), tick_unit: form.tickUnit, seeds: form.seeds,
    budget: Number(form.budget), channel: form.channel, fake: form.mode === "fake",
    elicits: form.elicits,
  };
  if (form.anchorVersion.trim()) body.anchor_versions = [form.anchorVersion.trim()];
  if (form.validation.trim()) body.validation = form.validation.trim();
  if (form.mode === "real") {
    body.model = form.model.trim();
    body.embed_model = form.embedModel.trim();
    body.shards = form.shards;
    body.sources = form.sources;
    const seed = number(form.populationSeed);
    if (seed !== undefined) body.population_seed = seed;
    const inRate = number(form.priceChatIn);
    const outRate = number(form.priceChatOut);
    if (inRate !== undefined && outRate !== undefined) {
      body.price_chat_in = inRate;
      body.price_chat_out = outRate;
    }
    const embed = number(form.priceEmbedIn);
    if (embed !== undefined) body.price_embed_in = embed;
  }
  return body;
}

/* The request that previews the population a study would draw. It follows the mode: a real study's preview
   reads the real corpus with the same pins and choices, because a preview drawn from anything else says
   nothing about the study it belongs to. */
export function gateRequest(form: StudyForm, briefYaml: string, evidence: unknown): Record<string, unknown> {
  const seed = number(form.populationSeed);
  const body: Record<string, unknown> = {
    brief_yaml: briefYaml, evidence_json: evidence, n: Number(form.n),
    seed: seed !== undefined ? seed : 4021, fake: form.mode === "fake",
  };
  if (form.mode === "real") {
    body.model = form.model.trim();
    body.embed_model = form.embedModel.trim();
    body.shards = form.shards;
    body.sources = form.sources;
  }
  return body;
}
