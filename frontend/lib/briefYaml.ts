/* The brief the form describes, as the YAML the engine's intake reads — and back.

   The form must say exactly what the engine will read: nothing the brief stated is dropped on
   the way in (its competitors, its currency, the source of each assumption) and nothing is
   rewritten on the way out (an assumption stays assumed; a name that looks like a number stays
   a name). Emission is js-yaml's own, under the YAML 1.1 schema PyYAML reads with, so a value
   is quoted whenever the engine's parser would otherwise read it as something else. Plain
   functions over plain data, so it can be tested by itself. */

import { dump, load, YAML11_SCHEMA } from "js-yaml";
import type { Brief, ClaimSource } from "./engine";

export interface FormClaim { text: string; source: ClaimSource; evidence_url: string }
/* The three ways the engine reads an audience's filter on one attribute: the value it is, any of
   several, or the ordinal bands from one to another. A form that holds only a string per attribute
   cannot hold the other two, and quietly turns them into something else. */
export type FilterSpec =
  | { kind: "exactly"; value: string | number }
  | { kind: "one_of"; values: (string | number)[] }
  | { kind: "range"; first: string; last: string };

export interface FormAudience { name: string; share: string; filters: Record<string, FilterSpec> }
export interface FormCompetitor { name: string; price: string; currency: string; claims: string }
export interface FormAssumption { text: string; source: ClaimSource }

export interface BriefForm {
  product: { name: string; category: string; description: string };
  price: string;
  currency: string;
  claims: FormClaim[];
  competitors: FormCompetitor[];
  target: string;
  audiences: FormAudience[];
  assumptions: FormAssumption[];
  ontologyVersion: string;
}

export function briefToYaml(form: BriefForm): string {
  const currency = form.currency.trim() || "USD";
  const brief = {
    product: { name: form.product.name, category: form.product.category, description: form.product.description },
    price: { amount: Number(form.price), currency },
    claims: form.claims.map((c) => ({
      text: c.text, source: c.source, ...(c.evidence_url ? { evidence_url: c.evidence_url } : {}),
    })),
    competitors: form.competitors.map((c) => ({
      name: c.name,
      ...(c.price.trim() !== "" ? { price: { amount: Number(c.price), currency: c.currency.trim() || currency } } : {}),
      ...(c.claims.trim() ? { claims: c.claims.split("\n").map((l) => l.trim()).filter(Boolean) } : {}),
    })),
    target_market: form.target,
    audiences: form.audiences.map((a) => ({
      name: a.name,
      ...(a.share.trim() !== "" ? { share: Number(a.share) } : {}),
      attribute_filters: Object.fromEntries(
        Object.entries(a.filters).map(([attribute, spec]) => [attribute, filterToYaml(spec)]),
      ),
    })),
    assumptions: form.assumptions.filter((a) => a.text.trim()).map((a) => ({ text: a.text, source: a.source })),
    ontology_version: form.ontologyVersion,
  };
  return dump(brief, { schema: YAML11_SCHEMA, lineWidth: -1 });
}

function filterToYaml(spec: FilterSpec): unknown {
  if (spec.kind === "one_of") return spec.values;
  if (spec.kind === "range") return { range: [spec.first, spec.last] };
  return spec.value;
}

/* An audience's filter as the brief stated it, whichever of the three forms that was. */
export function filterFromBrief(raw: unknown): FilterSpec {
  if (Array.isArray(raw)) return { kind: "one_of", values: raw.map((v) => (typeof v === "number" ? v : String(v))) };
  if (raw && typeof raw === "object" && Array.isArray((raw as { range?: unknown }).range)) {
    const [first, last] = (raw as { range: unknown[] }).range;
    return { kind: "range", first: String(first ?? ""), last: String(last ?? "") };
  }
  return { kind: "exactly", value: typeof raw === "number" ? raw : String(raw ?? "") };
}

/* Read back a comma-separated list the way it was typed: no blanks, no padding. */
export function splitList(text: string): string[] {
  return text.split(",").map((v) => v.trim()).filter(Boolean);
}

export function formFromBrief(brief: Brief): BriefForm {
  return {
    product: {
      name: brief.product.name, category: brief.product.category, description: brief.product.description,
    },
    price: String(brief.price.amount),
    currency: brief.price.currency,
    claims: brief.claims.map((c) => ({ text: c.text, source: c.source, evidence_url: c.evidence_url ?? "" })),
    competitors: brief.competitors.map((c) => ({
      name: c.name, price: c.price ? String(c.price.amount) : "", currency: c.price?.currency ?? "",
      claims: (c.claims ?? []).join("\n"),
    })),
    target: brief.target_market,
    audiences: brief.audiences.map((a) => ({
      name: a.name,
      share: a.share != null ? String(a.share) : "",
      filters: Object.fromEntries(
        Object.entries(a.attribute_filters as Record<string, unknown>).map(([k, v]) => [k, filterFromBrief(v)]),
      ),
    })),
    assumptions: brief.assumptions.map((a) => ({ text: a.text, source: a.source })),
    ontologyVersion: brief.ontology_version,
  };
}

/* What a YAML text says, for a test that wants to compare it with what was meant. */
export function parseBriefYaml(text: string): unknown {
  return load(text, { schema: YAML11_SCHEMA });
}
