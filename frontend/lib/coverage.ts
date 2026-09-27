/* How an attribute's coverage is put in front of someone choosing it. The engine counts and serves the shares;
   this only names them. Which attribute an audience is defined by decides whether the study can be drawn at all
   — `habit_budget_tracking` sounds right and is populated for 0.04% of the recorded personas.
   The glossary avoids talking about how "full" the data is, so the chips speak of coverage. */

export interface CoverageCell { present: number; total: number; share: number | null }
export interface AttributeCoverage { recorded: CoverageCell; by_source: Record<string, CoverageCell> }
export type CoverageState = "ready" | "building" | "failed" | "no_corpus" | "no_shards";
export interface CoverageInfo {
  available: boolean;
  state: CoverageState;
  detail?: string;
  totals?: Record<string, number>;
  attributes?: Record<string, AttributeCoverage>;
}

export type CoverageBand = "most" | "some" | "few" | "unknown";

/* The bands the guide states: an attribute answered by most is above half, and below a tenth an audience
   built on it is rarely drawable. */
export const MOST_FROM = 0.5;
export const SOME_FROM = 0.1;

export function coverageBand(cell: CoverageCell | undefined): CoverageBand {
  if (!cell || cell.share === null) return "unknown";
  if (cell.share >= MOST_FROM) return "most";
  if (cell.share >= SOME_FROM) return "some";
  return "few";
}

export function percent(share: number): string {
  const value = share * 100;
  if (value === 0) return "0%";
  if (value < 1) return `${value.toFixed(2)}%`;
  return `${value.toFixed(value < 10 ? 1 : 0)}%`;
}

export function coverageLabel(cell: CoverageCell | undefined): string {
  if (!cell || cell.share === null) return "coverage unknown";
  const band = coverageBand(cell);
  const who = band === "most" ? "answered by most" : band === "some" ? "answered by some" : "answered by few";
  return `${who} · ${percent(cell.share)} populated · ${cell.present.toLocaleString("en-US")} of ${cell.total.toLocaleString("en-US")} recorded personas`;
}

export const COVERAGE_NOTE: Record<CoverageBand, string> = {
  most: "",
  some: "Populated for a minority of personas: an audience built on it will be a small slice of the corpus.",
  few: "Nearly empty. An audience defined on this is unlikely to be drawn, and the study will be refused at its gate.",
  unknown: "",
};

/* Poll only while the engine is still counting; every other state is final until asked again. */
export function shouldPoll(info: CoverageInfo | null): boolean {
  return info === null || info.state === "building";
}
