/* Telling runs apart: a name, what it was, and when — never just an id. */

/* When a run began, as the engine read it from the run's first file: run ids are random and say nothing of time. */
export function runWhen(run: { created_at?: string | null }): string {
  if (!run.created_at) return "";
  const t = new Date(run.created_at);
  return Number.isNaN(t.getTime()) ? "" : t.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const CHANNEL_SHORT: Record<string, string> = { social_feed: "feed", forum: "forum", wom: "word of mouth" };

export interface RunLike {
  run_id: string;
  status: string;
  has_report?: boolean;
  fake?: boolean;
  product?: string | null;
  category?: string | null;
  personas?: number | null;
  created_at?: string | null;
  scenarios?: { channels?: string[] }[];
}

/* What the run was: a study over these channels, a concept test, or only a population draw. */
export function runKind(run: RunLike): string {
  const scenario = run.scenarios?.[0];
  if (!scenario) return "population draw";
  const channels = scenario.channels ?? [];
  return channels.length ? channels.map((c) => CHANNEL_SHORT[c] ?? c).join(" + ") : "concept test";
}

/* The run's name: its product, else its category, else that nothing names it. */
export function runName(run: RunLike): string {
  return run.product || (run.category ? run.category.replace(/_/g, " ") : "") || "unnamed run";
}

/* One line that tells this run from every other. */
export function runLabel(run: RunLike): string {
  const parts = [runName(run), runKind(run)];
  if (run.personas) parts.push(`${run.personas} personas`);
  const when = runWhen(run);
  if (when) parts.push(when);
  parts.push(run.status === "completed" ? "done" : run.status);
  return parts.join(" · ");
}
