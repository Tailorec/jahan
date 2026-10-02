/* The population gate in words a person can check: what each gate asks, what the draw showed, and the rule
   it was held to. Every number still comes from the gate report; this only says what it means. */

import type { FieldOrigin, GateReference, GateResult, Relaxation } from "./engine";

export interface GateWords {
  title: string;    // what is checked
  question: string; // the question the gate answers
  result: string;   // what this draw showed
  rule: string;     // what passing needs
  raw: string;      // the statistic, for recomputing the call
  failed?: string;  // what a failure means
}

const pct = (x: number) => (x > 0 && x < 0.001 ? "less than 0.1%" : `${(x * 100).toFixed(x < 0.1 ? 1 : 0).replace(/\.0$/, "")}%`);

export function explainGate(r: GateResult, label: (id: string) => string = (id) => id): GateWords {
  if (r.kind === "categorical") {
    const name = label(r.attribute ?? "");
    const alpha = r.significance_level ?? 0.05;
    return {
      title: name,
      question: `Does ${name} among the drawn personas look like it does among the people they were drawn from?`,
      result: r.p_value === undefined ? "Not measured." : `A gap this size would turn up by chance ${pct(r.p_value)} of the time${r.adjusted_p_value != null ? `; ${pct(r.adjusted_p_value)} once every attribute tested is counted` : ""}.`,
      rule: r.adjusted_p_value != null
        ? `Passes when that chance, adjusted for testing every attribute at once (Holm), is above ${pct(alpha)}.`
        : `Passes when that chance is above ${pct(alpha)}.`,
      raw: `χ² ${r.chi_square?.toFixed(2) ?? "—"} · dof ${r.degrees_of_freedom ?? "—"} · p ${r.p_value?.toFixed(3) ?? "—"}`,
      failed: `The draw's ${name} differs from its pools by more than chance explains: the sample is skewed.`,
    };
  }
  if (r.kind === "ordinal") {
    const name = label(r.attribute ?? "");
    const threshold = r.similarity_threshold ?? 0.8;
    return {
      title: name,
      question: `Is ${name}, an ordered scale, spread across its bands the way it is among the people drawn from?`,
      result: r.ks_similarity === undefined ? "Not measured."
        : `Similarity ${r.ks_similarity.toFixed(2)}: the two spreads are never more than ${pct(r.ks_statistic ?? 0)} apart.`,
      rule: `Passes at similarity ${threshold.toFixed(2)} or more.`,
      raw: `KS D ${r.ks_statistic?.toFixed(3) ?? "—"} · similarity ${r.ks_similarity?.toFixed(2) ?? "—"}`,
      failed: `The draw piles up in some bands of ${name} more than its pools do: the sample is skewed.`,
    };
  }
  const measured = r.measured ?? 0;
  const floor = r.threshold ?? 0;
  const raw = `measured ${r.measured ?? "—"} · floor ${r.threshold ?? "—"}`;
  if (r.check === "connectivity") {
    return {
      title: "Social network: connected", question: "Is the personas' social network one connected whole, so word can travel?",
      result: `${pct(measured)} of personas are in the largest connected group.`, rule: `Needs at least ${pct(floor)}.`, raw,
      failed: "Too many personas are cut off from the rest: word of mouth could not reach them.",
    };
  }
  if (r.check === "clustering") {
    return {
      title: "Social network: clustering", question: "Do a persona's contacts also know each other, as in real circles of friends?",
      result: `Clustering ${measured.toFixed(2)} (0 = contacts never know each other, 1 = always).`, rule: `Needs at least ${floor.toFixed(2)}.`, raw,
      failed: "Contacts rarely know each other: the network is too random to behave like real social circles.",
    };
  }
  return {
    title: "Social network: hubs", question: "Does the network have a few well-connected people, as real networks do?",
    result: `The best-connected persona has ${measured.toFixed(1)}× the average number of ties.`, rule: `Needs at least ${floor.toFixed(1)}×.`, raw,
    failed: "Everyone has about the same number of ties: there are no hubs for word to spread through.",
  };
}

/* Where a result sits against its pass line, for a meter: every gate passes when its number reaches the line —
   a chance above the significance level, a similarity or a network measure at or above its floor. */
export interface GateMeter { value: number; line: number; max: number; short: string }

export function gateMeter(r: GateResult): GateMeter {
  if (r.kind === "categorical") {
    // The adjusted chance is what decides the gate (ADR 0049); older reports carry only the raw one.
    const value = r.adjusted_p_value ?? r.p_value ?? 0;
    const line = r.significance_level ?? 0.05;
    return { value, line, max: 1, short: `chance ${pct(value)} · needs above ${pct(line)}` };
  }
  if (r.kind === "ordinal") {
    const value = r.ks_similarity ?? 0;
    const line = r.similarity_threshold ?? 0.8;
    return { value, line, max: 1, short: `similarity ${value.toFixed(2)} · needs ${line.toFixed(2)}+` };
  }
  const value = r.measured ?? 0;
  const line = r.threshold ?? 0;
  const share = r.check === "connectivity";
  const show = (x: number) => (share ? pct(x) : r.check === "degree_shape" ? `${x.toFixed(1)}×` : x.toFixed(2));
  return { value, line, max: share ? 1 : Math.max(value, line) * 1.25 || 1, short: `${show(value)} · needs ${show(line)}+` };
}

export const REFERENCE_WORDS: Record<GateReference, string> = {
  design: "Judged against the study's own design: each audience's pool of eligible people, weighted by the shares you asked for. A pass means the random draw came out as designed — not that it matches the whole market.",
  category_targets: "Judged against the category's measured population, since this study declared no audiences: a pass means the sample resembles the category as surveyed.",
};

export function explainRelaxation(r: Relaxation, label: (id: string) => string = (id) => id): string {
  const what = r.rung === "widen_ordinal" ? `widened ${label(r.attribute ?? "a filter")} by one band`
    : r.rung === "drop_filter" ? `dropped the ${label(r.attribute ?? "")} filter`
      : "accepted fewer people than asked";
  return `${r.audience}: ${what} to find enough people — ${r.rows_before.toLocaleString("en-US")} → ${r.rows_after.toLocaleString("en-US")} eligible, ${pct(r.share_achieved)} of its share reached.`;
}

export const ORIGIN_WORDS: Record<FieldOrigin, string> = {
  measured: "measured — the person gave this answer in a survey",
  extracted: "extracted — a model read it from text the person wrote",
  calibrated: "calibrated — corrected against measured data",
  synthesized: "synthesized — filled in by a model, with no source behind it",
};
