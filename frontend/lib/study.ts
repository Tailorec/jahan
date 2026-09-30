/* What a person configures to launch a study, and how it becomes the request the engine takes.

   Kept apart from the page so the mapping from a form to the API is a plain function that can be tested,
   the way `briefYaml` is. The inputs are the ones the command line takes for a study: who can be drawn
   (shards, sources, the draw's seed), which models answer and what they cost, and what is asked. The endpoint
   and its key are the server's environment and are never a field here. */

export interface CorpusShard { id: string; rows: number | null; bytes: number | null; cached: boolean; sources?: Record<string, number> }
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

/* The channels a study can tick: any combination, including none. The survey room is a wave's
   internal channel, never a choice. */
export const CHANNELS = ["social_feed", "forum", "wom"] as const;
export type ChannelName = (typeof CHANNELS)[number];

/* What each channel does, in a line. Word of mouth alone starts from a launch reach — a random
   share of personas who hear first-hand — without whom nobody has anything to pass on. */
export const CHANNEL_GUIDE: Record<ChannelName, { summary: string; use: string }> = {
  social_feed: {
    summary: "a feed: reactions can spread",
    use: "Personas scroll a feed holding the concept and each other's posts, and can like, comment, follow, buy or ask a peer. A persona who reacts strongly to a peer they are close to passes it on, so reach grows over the ticks. Choose this to see how a reaction spreads and whether social proof moves intent.",
  },
  forum: {
    summary: "threads: discussion and disagreement form",
    use: "Personas read and reply in threads, and can upvote, downvote, reply or buy. Discussion forms and communities can drift apart, so polarization is measured. Choose this to see how the concept is argued over, not only how each persona feels.",
  },
  wom: {
    summary: "word of mouth along social ties",
    use: "A persona who reacts strongly tells close ties, who hear on the next tick. Alone it starts from the launch reach below; beside a feed or a forum it carries what personas do there. Choose this to isolate what spreads person to person.",
  },
};

/* The wave ticks for a survey interval and horizon: {0, k, 2k, …} ∪ {horizon − 1}. */
export function waveTicks(surveyEvery: number, horizon: number): number[] {
  const ticks = new Set<number>();
  for (let t = 0; t < horizon; t += surveyEvery) ticks.add(t);
  ticks.add(horizon - 1);
  return [...ticks].sort((a, b) => a - b);
}

export interface StudyForm {
  n: string;
  horizon: string;
  tickUnit: string;
  seeds: string;
  budget: string;
  channels: ChannelName[];
  surveyEvery: string;
  launchReach: string;
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

/* The cached shards holding any of the chosen sources: a shard is a slice of rows, so a study's people are
   wherever its sources' rows happen to be. */
export function shardsFor(corpus: CorpusInfo | null, sources: string[]): string[] {
  return (corpus?.shards ?? []).filter((s) => s.cached && sources.some((src) => (s.sources?.[src] ?? 0) > 0)).map((s) => s.id);
}

/* People of the chosen sources in cached shards left unticked: who the draw will never reach. */
export function leftOut(corpus: CorpusInfo | null, shards: string[], sources: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const s of corpus?.shards ?? []) {
    if (!s.cached || shards.includes(s.id)) continue;
    for (const src of sources) if ((s.sources?.[src] ?? 0) > 0) out[src] = (out[src] ?? 0) + (s.sources?.[src] ?? 0);
  }
  return out;
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

/* What is wrong with a study's inputs, in words, before anything is sent. The engine refuses the same
   things; saying so here saves a round trip and points at the field. Empty when the form is sound. */
export function problems(form: StudyForm): string[] {
  const found: string[] = [];
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
  const every = number(form.surveyEvery);
  if (every !== undefined && (!Number.isInteger(every) || every < 1)) {
    found.push("Survey waves come every k ticks, k a whole number of one or more.");
  }
  const reach = number(form.launchReach);
  if (reach !== undefined && (reach < 0 || reach > 1)) {
    found.push("The launch reach is a share, between zero and one.");
  }
  if ((reach ?? 0.10) !== 0.10 && !(form.channels.length === 1 && form.channels[0] === "wom")) {
    found.push("The launch reach is only meaningful with word of mouth alone.");
  }
  return found;
}

/* The request that starts a study: its models, the corpus it draws from, the draw's seed and what the models
   cost. The interface only starts real studies; a fake one is the command line's, for tests. */
export function studyRequest(form: StudyForm, briefYaml: string, evidence: unknown): Record<string, unknown> {
  const body: Record<string, unknown> = {
    brief_yaml: briefYaml, evidence_json: evidence,
    n: Number(form.n), horizon: Number(form.horizon), tick_unit: form.tickUnit, seeds: form.seeds,
    budget: Number(form.budget), channels: [...form.channels], fake: false,
    model: form.model.trim(), embed_model: form.embedModel.trim(), shards: form.shards, sources: form.sources,
  };
  if (form.anchorVersion.trim()) body.anchor_versions = [form.anchorVersion.trim()];
  const every = number(form.surveyEvery);
  if (every !== undefined) body.survey_every = every;
  const reach = number(form.launchReach);
  if (reach !== undefined) body.launch_reach = reach;
  if (form.validation.trim()) body.validation = form.validation.trim();
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
  return body;
}

/* The request that previews the population a study would draw: the real corpus, with the same pins and
   choices, because a preview drawn from anything else says nothing about the study it belongs to. */
export function gateRequest(form: StudyForm, briefYaml: string, evidence: unknown): Record<string, unknown> {
  const seed = number(form.populationSeed);
  const body: Record<string, unknown> = {
    brief_yaml: briefYaml, evidence_json: evidence, n: Number(form.n),
    seed: seed !== undefined ? seed : 4021, fake: false,
    model: form.model.trim(), embed_model: form.embedModel.trim(), shards: form.shards, sources: form.sources,
  };
  return body;
}
