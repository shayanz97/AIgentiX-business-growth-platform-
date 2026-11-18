import type { Lead, LeadScore, Signal } from "@/lib/api";

export const REVIEW_STATUSES = ["new", "needs_research", "qualified_for_review", "reviewed", "rejected"] as const;
export const PRIORITY_BANDS = ["high", "medium", "low", "excluded"] as const;
export const INTENT_STATUSES = ["explicit", "strong", "indirect", "none_verified", "unknown"] as const;
export const SORTS = [
  { value: "score", label: "Score (conservative)" },
  { value: "score_high", label: "Score (upper bound)" },
  { value: "coverage", label: "Coverage" },
  { value: "latest_trigger", label: "Latest trigger" },
  { value: "intent", label: "Buying intent" },
  { value: "name", label: "Company name" },
  { value: "scored_at", label: "Scored at" },
] as const;
export const SIGNAL_TYPES = [
  "hiring",
  "expansion",
  "funding",
  "product_launch",
  "leadership_change",
  "technology_adoption",
  "digital_transformation",
  "operational_change",
  "public_project_request",
  "procurement_tender",
  "inbound_inquiry",
  "other",
] as const;

export const INTENT_LABELS: Record<string, string> = {
  explicit: "Explicit",
  strong: "Strong",
  indirect: "Indirect",
  none_verified: "None verified",
  unknown: "Not checked",
};

export const STATE_LABELS: Record<string, string> = {
  assessed: "Assessed",
  unknown: "Unknown",
  insufficient_evidence: "Insufficient evidence",
  not_applicable: "Not applicable",
};

export const FRESHNESS_LABELS: Record<string, string> = {
  recent: "Recent",
  moderate: "Moderate",
  older: "Older",
  historical: "Historical",
  unknown: "Date unknown",
};

export const PRECISION_LABELS: Record<string, string> = {
  day: "exact day",
  month: "month only",
  year: "year only",
  unknown: "no date",
};

/** Human-readable label for a snake_case value such as `qualified_for_review`. */
export function humanize(value: string): string {
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function round(n: number): number {
  return Math.round(n);
}

/** "54 – 79" (conservative to upper bound); a single number when both bounds agree. */
export function formatScoreRange(low: number, high: number): string {
  const a = round(low);
  const b = round(high);
  return a === b ? `${a}` : `${a} – ${b}`;
}

/** Coverage is a 0..1 share of the weight that could be assessed. */
export function formatCoverage(coverage: number): string {
  return `${Math.round(coverage * 100)}%`;
}

/** Why a score is provisional, for display next to the label. */
export function provisionalExplanation(score: Pick<LeadScore, "provisional" | "coverage" | "score_low" | "score_high">): string | null {
  if (!score.provisional) return null;
  return (
    `Only ${formatCoverage(score.coverage)} of the scoring weight could be assessed from the data collected so far. ` +
    `The true score lies between ${formatScoreRange(score.score_low, score.score_high)}; missing information counts as 0 in the lower bound.`
  );
}

/** "2026-03" for month precision, "2026" for year precision, otherwise the ISO day. */
export function formatEventDate(date: string | null, precision: Signal["date_precision"]): string {
  if (!date) return "Date unknown";
  if (precision === "month") return date.slice(0, 7);
  if (precision === "year") return date.slice(0, 4);
  return date;
}

export type SignalGroups = { dated: Signal[]; undated: Signal[] };

/** Dated signals newest first; signals without a date (or with conflicting dates) are never mixed into the timeline. */
export function groupSignals(signals: Signal[]): SignalGroups {
  const dated: Signal[] = [];
  const undated: Signal[] = [];
  for (const s of signals) {
    if (s.occurred_on && !s.date_conflict) dated.push(s);
    else undated.push(s);
  }
  dated.sort((a, b) => (b.occurred_on ?? "").localeCompare(a.occurred_on ?? "") || a.title.localeCompare(b.title));
  undated.sort((a, b) => a.title.localeCompare(b.title));
  return { dated, undated };
}

export const WEIGHT_KEYS = ["opportunity", "fit", "triggers", "intent"] as const;
export type WeightKey = (typeof WEIGHT_KEYS)[number];

export function weightsSum(weights: Record<WeightKey, number>): number {
  return WEIGHT_KEYS.reduce((sum, k) => sum + (Number.isFinite(weights[k]) ? weights[k] : 0), 0);
}

/** Returns an error message when the weights cannot be saved, otherwise null. */
export function validateWeights(weights: Record<WeightKey, number>): string | null {
  for (const k of WEIGHT_KEYS) {
    const v = weights[k];
    if (!Number.isInteger(v) || v < 0 || v > 100) return `The ${k} weight must be a whole number between 0 and 100.`;
  }
  const sum = weightsSum(weights);
  return sum === 100 ? null : `Weights must add up to 100 (currently ${sum}).`;
}

export function splitList(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function leadHref(lead: Pick<Lead, "company_id">): string {
  return `/leads/${lead.company_id}`;
}

export type LeadFilters = {
  q: string;
  review_status: string;
  priority_band: string;
  intent_status: string;
  signal_type: string;
  min_score: string;
  provisional: "" | "yes" | "no";
  hideExcluded: boolean;
  project_id: string;
  sort: string;
};

export const DEFAULT_FILTERS: LeadFilters = {
  q: "",
  review_status: "",
  priority_band: "",
  intent_status: "",
  signal_type: "",
  min_score: "",
  provisional: "",
  hideExcluded: false,
  project_id: "",
  sort: "score",
};

/** Query shared by the list and the CSV export so both always show the same leads. */
export function buildLeadQuery(f: LeadFilters) {
  const min = f.min_score.trim() === "" ? undefined : Number(f.min_score);
  return {
    q: f.q.trim() || undefined,
    review_status: (f.review_status || undefined) as (typeof REVIEW_STATUSES)[number] | undefined,
    priority_band: (f.priority_band || undefined) as (typeof PRIORITY_BANDS)[number] | undefined,
    intent_status: (f.intent_status || undefined) as (typeof INTENT_STATUSES)[number] | undefined,
    signal_type: f.signal_type || undefined,
    min_score: min !== undefined && Number.isFinite(min) ? min : undefined,
    provisional: f.provisional === "" ? undefined : f.provisional === "yes",
    include_excluded: !f.hideExcluded,
    project_id: f.project_id || undefined,
    sort: f.sort as (typeof SORTS)[number]["value"],
  };
}
