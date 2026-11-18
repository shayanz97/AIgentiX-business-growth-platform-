import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@contracts/schema";

export type Schemas = components["schemas"];
export type Project = Schemas["ProjectRead"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type Membership = Schemas["MembershipRead"];
export type Me = Schemas["MeResponse"];
export type ModuleInfo = Schemas["ModuleRead"];
export type Member = Schemas["MemberRead"];
export type WorkflowRun = Schemas["WorkflowRunRead"];
export type Company = Schemas["CompanyRead"];
export type CompanyDetail = Schemas["CompanyDetail"];
export type ResearchRun = Schemas["ResearchRunRead"];
export type ResearchRunStartResult = Schemas["ResearchRunStartResult"];
export type SkippedCompany = Schemas["SkippedCompany"];
export type Opportunity = Schemas["OpportunityRead"];
export type OpportunityStatus = Schemas["OpportunityStatus"];
export type Evidence = Schemas["EvidenceRead"];
export type EvidenceRef = Schemas["EvidenceRef"];
export type Source = Schemas["SourceRead"];
export type ImportResult = Schemas["CompanyImportResult"];
export type ImportRow = Schemas["CompanyImportRow"];
export type LeadIntelligenceSummary = Schemas["LeadIntelligenceSummary"];

export type Profile = Schemas["ProfileRead"];
export type ProfileCreate = Schemas["ProfileCreate"];
export type ProfileUpdate = Schemas["ProfileUpdate"];
export type EnrichmentStartResult = Schemas["EnrichmentStartResult"];
export type CompanySignals = Schemas["CompanySignals"];
export type Signal = Schemas["SignalRead"];
export type Intent = Schemas["IntentRead"];
export type FirstPartyIntentCreate = Schemas["FirstPartyIntentCreate"];
export type LeadScore = Schemas["LeadScoreRead"];
export type ScoreComponent = Schemas["ComponentRead"];
export type ScoreCriterion = Schemas["CriterionRead"];
export type Lead = Schemas["LeadRead"];
export type LeadDetail = Schemas["LeadDetail"];
export type LeadReview = Schemas["LeadReviewRead"];
export type ReviewStatus = Schemas["ReviewStatus"];
export type ScoreRunResult = Schemas["ScoreRunResult"];

export const ORG_HEADER = "X-Organization-Id";
const ORG_STORAGE_KEY = "aigx.activeOrganization";

/** The active organization is a client preference only; the API verifies membership on every request. */
export const activeOrganization = {
  get(): string | null {
    try {
      return window.localStorage.getItem(ORG_STORAGE_KEY);
    } catch {
      return null;
    }
  },
  set(id: string | null): void {
    try {
      if (id) window.localStorage.setItem(ORG_STORAGE_KEY, id);
      else window.localStorage.removeItem(ORG_STORAGE_KEY);
    } catch {
      /* storage unavailable: selection lasts for this page only */
    }
  },
};

const orgHeader: Middleware = {
  onRequest({ request }) {
    const org = activeOrganization.get();
    if (org && !request.headers.has(ORG_HEADER)) request.headers.set(ORG_HEADER, org);
    return request;
  },
};

/** Typed client generated from the backend OpenAPI contract. Same-origin; Next.js proxies /api/v1. */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(orgHeader);

type ErrorPayload = { error?: { message?: string; details?: unknown } } | undefined;

export function errorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
  const message = (error as ErrorPayload)?.error?.message;
  return typeof message === "string" && message.length > 0 ? message : fallback;
}
