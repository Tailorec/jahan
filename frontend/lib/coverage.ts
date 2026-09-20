/* How an attribute's coverage is put in front of someone choosing it. The engine counts and serves the shares;
   this only names them. Which attribute an audience is defined by decides whether the study can be drawn at all
   — `habit_budget_tracking` sounds right and is populated for 0.04% of the recorded personas. */

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

export type Density = "dense" | "thin" | "sparse" | "unknown";

/* The bands the guide states: an attribute is dense above half, and below a tenth an audience built on it is
   rarely drawable. */
export const DENSE_FROM = 0.5;
export const THIN_FROM = 0.1;

export function density(cell: CoverageCell | undefined): Density {
  if (!cell || cell.share === null) return "unknown";
  if (cell.share >= DENSE_FROM) return "dense";
  if (cell.share >= THIN_FROM) return "thin";
  return "sparse";
}

export function percent(share: number): string {
  const value = share * 100;
  if (value === 0) return "0%";
  if (value < 1) return `${value.toFixed(2)}%`;
  return `${value.toFixed(value < 10 ? 1 : 0)}%`;
}

export function coverageLabel(cell: CoverageCell | undefined): string {
  if (!cell || cell.share === null) return "coverage unknown";
  return `${percent(cell.share)} populated · ${cell.present.toLocaleString("en-US")} of ${cell.total.toLocaleString("en-US")} recorded personas`;
}

export const DENSITY_NOTE: Record<Density, string> = {
  dense: "",
  thin: "Populated for a minority of personas: an audience built on it will be a small slice of the corpus.",
  sparse: "Nearly empty. An audience defined on this is unlikely to be drawn, and the study will be refused at its gate.",
  unknown: "",
};

/* Poll only while the engine is still counting; every other state is final until asked again. */
export function shouldPoll(info: CoverageInfo | null): boolean {
  return info === null || info.state === "building";
}
