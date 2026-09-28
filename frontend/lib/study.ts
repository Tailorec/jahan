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

/* The environments a study runs on. `wom` is a channel a message is delivered on, not one a study runs on. */
export const CHANNELS = ["survey_room", "social_feed", "forum"] as const;
export type ChannelName = (typeof CHANNELS)[number];

/* Why one would choose each environment. The architecture has a world run these together — a persona reacting once per
   channel per tick — but this build runs one platform per world, so a study picks one. Word of mouth is not a
   choice: in a feed or a forum it rides beside the platform, when a persona reacts strongly enough and is close enough
   to a peer, and the peer meets it on a later tick. */
export const ONE_ENVIRONMENT_NOTE =
  "This version runs one environment per study; running them together is designed but not built.";

export const CHANNEL_GUIDE: Record<ChannelName, { summary: string; use: string }> = {
  survey_room: {
    summary: "measure purchase intent, concept alone",
    use: "Each persona is shown the concept alone and answers. Nothing spreads between personas, so word of mouth is zero by construction. Choose this to measure purchase intent by audience against a clean baseline.",
  },
  social_feed: {
    summary: "a feed: reactions can spread",
    use: "Personas scroll a feed holding the concept and each other's posts, and can like, comment, follow, buy or ask a peer. A persona who reacts strongly to a peer they are close to passes it on, so reach grows over the ticks. Choose this to see how a reaction spreads and whether social proof moves intent.",
  },
  forum: {
    summary: "threads: discussion and disagreement form",
    use: "Personas read and reply in threads, and can upvote, downvote, reply or buy. Discussion forms and communities can drift apart, so polarization is measured. Choose this to see how the concept is argued over, not only how each persona feels.",
  },
};

export interface StudyForm {
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
  return found;
}

/* The request that starts a study: its models, the corpus it draws from, the draw's seed and what the models
   cost. The interface only starts real studies; a fake one is the command line's, for tests. */
export function studyRequest(form: StudyForm, briefYaml: string, evidence: unknown): Record<string, unknown> {
  const body: Record<string, unknown> = {
    brief_yaml: briefYaml, evidence_json: evidence,
    n: Number(form.n), horizon: Number(form.horizon), tick_unit: form.tickUnit, seeds: form.seeds,
    budget: Number(form.budget), channel: form.channel, fake: false,
    elicits: form.elicits,
    model: form.model.trim(), embed_model: form.embedModel.trim(), shards: form.shards, sources: form.sources,
  };
  if (form.anchorVersion.trim()) body.anchor_versions = [form.anchorVersion.trim()];
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
