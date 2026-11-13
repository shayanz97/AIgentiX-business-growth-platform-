import { splitList, type WeightKey, WEIGHT_KEYS } from "@/lib/leads";

export const SOLUTION_CATEGORIES = [
  "customer_service_automation",
  "document_processing",
  "workflow_automation",
  "knowledge_assistant",
  "appointment_scheduling",
  "sales_crm_automation",
] as const;

export const COMPANY_TYPES = ["b2b", "b2c"] as const;

type Obj = Record<string, unknown>;

function obj(v: unknown): Obj {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {};
}
function num(v: unknown, fallback: number): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
function strs(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

export type ScoringForm = {
  weights: Record<WeightKey, string>;
  bands: { recent: string; moderate: string; older: string };
  factors: { recent: string; moderate: string; older: string; historical: string; unknown: string };
  thresholds: { high: string; medium: string };
  minCoverage: string;
};

/** Reads the free-form `config` JSON defensively; missing keys fall back to the documented defaults. */
export function scoringFormFromConfig(config: unknown): ScoringForm {
  const c = obj(config);
  const w = obj(c.weights);
  const b = obj(c.freshness_bands);
  const f = obj(c.freshness_factors);
  const t = obj(c.thresholds);
  return {
    weights: { opportunity: String(num(w.opportunity, 35)), fit: String(num(w.fit, 25)), triggers: String(num(w.triggers, 20)), intent: String(num(w.intent, 20)) },
    bands: { recent: String(num(b.recent, 30)), moderate: String(num(b.moderate, 90)), older: String(num(b.older, 180)) },
    factors: {
      recent: String(num(f.recent, 1)),
      moderate: String(num(f.moderate, 0.7)),
      older: String(num(f.older, 0.4)),
      historical: String(num(f.historical, 0.1)),
      unknown: String(num(f.unknown, 0.3)),
    },
    thresholds: { high: String(num(t.high, 60)), medium: String(num(t.medium, 35)) },
    minCoverage: String(num(c.min_coverage, 0.75)),
  };
}

export function parseWeights(form: ScoringForm): Record<WeightKey, number> {
  const out = {} as Record<WeightKey, number>;
  for (const k of WEIGHT_KEYS) out[k] = form.weights[k].trim() === "" ? NaN : Number(form.weights[k]);
  return out;
}

/** Complete config for PATCH; the server validates ranges and ordering and returns readable messages. */
export function scoringConfigFromForm(form: ScoringForm): Obj {
  const n = (s: string) => Number(s);
  return {
    weights: parseWeights(form),
    freshness_bands: { recent: n(form.bands.recent), moderate: n(form.bands.moderate), older: n(form.bands.older) },
    freshness_factors: {
      recent: n(form.factors.recent),
      moderate: n(form.factors.moderate),
      older: n(form.factors.older),
      historical: n(form.factors.historical),
      unknown: n(form.factors.unknown),
    },
    thresholds: { high: n(form.thresholds.high), medium: n(form.thresholds.medium) },
    min_coverage: n(form.minCoverage),
  };
}

export type IcpForm = {
  countries: string;
  minEmployees: string;
  maxEmployees: string;
  targetIndustries: string;
  excludedIndustries: string;
  categories: string[];
  companyTypes: string[];
};

export function icpFormFromConfig(config: unknown): IcpForm {
  const c = obj(config);
  return {
    countries: strs(c.countries).join(", "),
    minEmployees: c.min_employees == null ? "" : String(c.min_employees),
    maxEmployees: c.max_employees == null ? "" : String(c.max_employees),
    targetIndustries: strs(c.target_industries).join(", "),
    excludedIndustries: strs(c.excluded_industries).join(", "),
    categories: strs(c.solution_categories),
    companyTypes: strs(c.company_types),
  };
}

export function icpConfigFromForm(form: IcpForm): Obj {
  const opt = (s: string) => (s.trim() === "" ? null : Number(s));
  return {
    countries: splitList(form.countries).map((s) => s.toUpperCase()),
    company_types: form.companyTypes,
    min_employees: opt(form.minEmployees),
    max_employees: opt(form.maxEmployees),
    target_industries: splitList(form.targetIndustries),
    excluded_industries: splitList(form.excludedIndustries),
    solution_categories: form.categories,
  };
}
