import type { SkippedCompany } from "@/lib/api";

export const ACTIVE_STATUSES = ["pending", "running"];

export function isActiveStatus(status: string | null | undefined): boolean {
  return !!status && ACTIVE_STATUSES.includes(status);
}

export const STEP_LABELS: Record<string, string> = {
  validate_input: "Validate input",
  fetch_website: "Fetch website",
  discover_relevant_pages: "Discover relevant pages",
  extract_information: "Extract information",
  save_evidence: "Save evidence",
  ai_opportunity_audit: "AI opportunity audit",
  persist_results: "Persist results",
  collect_sources: "Collect sources",
  extract_signals: "Extract growth signals",
  review_signals: "Review signals",
  verify_evidence: "Verify evidence",
  research_intent: "Research buying intent",
  score_lead: "Score lead",
};

export const SKIP_REASONS: Record<SkippedCompany["reason"], string> = {
  not_found: "company was not found",
  no_website: "no website is saved for this company",
  already_running: "research is already running for this company",
};

export const QUALITY_FLAG_TEXT: Record<string, string> = {
  unsupported_claim: "Contains a claim not supported by the cited evidence — confidence lowered",
  confidence_capped: "Confidence was capped because the evidence is limited",
  cited_unknown_evidence: "Cited evidence that does not exist — those citations were dropped",
  external_link_removed: "An external link in the model output was removed",
  inferred_evidence_only: "Based only on inferred evidence, not directly observed facts",
  missing_validation_questions: "No validation questions were provided — confirm assumptions before acting",
};

export function qualityFlagText(flag: string): string {
  return QUALITY_FLAG_TEXT[flag] ?? flag.replace(/_/g, " ");
}

/** Only http(s) links are rendered as anchors; anything else (javascript:, data:) is shown as text. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export type ProfileValue = { value: string; basis: string | null; confidence: string | null; evidenceId: string | null };
export type ProfileField = { key: string; label: string; values: ProfileValue[] };
export type ParsedProfile = {
  fields: ProfileField[];
  unknownFields: string[];
  observedSignals: string[];
  models: string[];
  hasContent: boolean;
};

export const FIELD_LABELS: Record<string, string> = {
  description: "Description",
  industry: "Industry",
  service: "Services",
  target_customer: "Target customers",
  business_model: "Business model",
  customer_interaction: "Customer interaction",
  document_workflow: "Document workflow",
  operational_signal: "Operational signals",
  location: "Location",
};

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function strings(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && x !== "") : [];
}

/** The profile is a free-form JSON object in the API contract, so it is read defensively. */
export function parseProfile(profile: unknown): ParsedProfile {
  const root = profile && typeof profile === "object" && !Array.isArray(profile) ? (profile as Record<string, unknown>) : {};
  const rawFields = root.fields && typeof root.fields === "object" && !Array.isArray(root.fields) ? (root.fields as Record<string, unknown>) : {};
  const fields: ProfileField[] = [];
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const raw = rawFields[key];
    if (!Array.isArray(raw)) continue;
    const values: ProfileValue[] = [];
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const o = item as Record<string, unknown>;
      const value = str(o.value);
      if (!value) continue;
      values.push({ value, basis: str(o.basis), confidence: str(o.confidence), evidenceId: str(o.evidence_id) });
    }
    if (values.length > 0) fields.push({ key, label, values });
  }
  const generated = root.generated_by && typeof root.generated_by === "object" ? (root.generated_by as Record<string, unknown>) : {};
  const unknownFields = strings(root.unknown_fields);
  const observedSignals = strings(root.observed_signals);
  return {
    fields,
    unknownFields,
    observedSignals,
    models: strings(generated.models),
    hasContent: fields.length > 0 || unknownFields.length > 0 || observedSignals.length > 0,
  };
}

export function usesFixtureModel(...modelLists: string[][]): boolean {
  return modelLists.some((list) => list.some((m) => m.startsWith("fixture-")));
}
