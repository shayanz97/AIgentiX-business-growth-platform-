import type { Activity, Deal, Priority, ProposalSection, SalesMetrics, Stage } from "@/lib/api";

export const STAGES: Stage[] = ["qualified", "researching", "contact_planned", "in_conversation", "proposal_sent", "won", "lost"];
export const OPEN_STAGES: Stage[] = STAGES.slice(0, 5);

export const STAGE_LABELS: Record<Stage, string> = {
  qualified: "Qualified",
  researching: "Researching",
  contact_planned: "Contact planned",
  in_conversation: "In conversation",
  proposal_sent: "Proposal sent",
  won: "Won",
  lost: "Lost",
};

/** Mirrors the backend transition table (domain/pipeline.py). Won/lost are reached only through Close. */
const TRANSITIONS: Record<Stage, Stage[]> = {
  qualified: ["researching", "contact_planned"],
  researching: ["qualified", "contact_planned"],
  contact_planned: ["researching", "in_conversation"],
  in_conversation: ["contact_planned", "proposal_sent"],
  proposal_sent: ["in_conversation"],
  won: [],
  lost: [],
};

export function allowedNextStages(stage: Stage): Stage[] {
  return TRANSITIONS[stage];
}

/** Gate hints shown next to a stage option; the API remains the authority and returns the real message. */
export const STAGE_REQUIREMENTS: Partial<Record<Stage, string>> = {
  in_conversation: "needs a recorded call, meeting or e-mail",
  proposal_sent: "needs a proposal marked as sent",
};

export const PRIORITIES: Priority[] = ["low", "medium", "high"];

export function humanizeKey(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatMoney(amount: string | number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === "") return "No value";
  const n = Number(amount);
  if (!Number.isFinite(n)) return "No value";
  return `${currency} ${n.toLocaleString("en", { maximumFractionDigits: 2 })}`;
}

/** One entry per currency, sorted; empty when nothing has been recorded. Amounts are never summed across currencies. */
export function formatPerCurrency(values: Record<string, string>): string[] {
  return Object.keys(values)
    .sort()
    .map((currency) => formatMoney(values[currency], currency));
}

/** Rates are fractions (0..1) or null when the denominator is zero: null is shown as an em dash, never as 0%. */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toLocaleString("en", { maximumFractionDigits: 1 })}%`;
}

export function pipelineNote(metrics: Pick<SalesMetrics, "open_without_value">): string | null {
  const n = metrics.open_without_value;
  if (n <= 0) return null;
  return `${n} ${n === 1 ? "deal" : "deals"} without value not included`;
}

export const TASK_VIEWS = [
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Today" },
  { value: "upcoming", label: "Upcoming" },
  { value: "completed", label: "Completed" },
  { value: "mine", label: "Assigned to me" },
] as const;
export type TaskTab = (typeof TASK_VIEWS)[number]["value"];

export function taskTabLabel(tab: TaskTab): string {
  return TASK_VIEWS.find((t) => t.value === tab)?.label ?? tab;
}

/** Query for GET /sales/tasks per dashboard tab ("mine" shows open tasks assigned to the current user). */
export function taskQuery(tab: TaskTab): { view: "overdue" | "today" | "upcoming" | "completed" | "open"; mine: boolean } {
  return tab === "mine" ? { view: "open", mine: true } : { view: tab, mine: false };
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export const SECTION_STATUS_LABELS: Record<ProposalSection["status"], string> = {
  draft: "Draft",
  needs_input: "Needs input",
};

export function sectionStatusLabel(status: ProposalSection["status"]): string {
  return SECTION_STATUS_LABELS[status] ?? humanizeKey(status);
}

export const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  generating: "Generating",
  draft: "Draft",
  ready: "Ready",
  sent: "Sent",
  accepted: "Accepted",
  declined: "Declined",
  failed: "Failed",
};

export function isGenerating(status: string | undefined | null): boolean {
  return status === "generating";
}

/** Proposal status moves a person can make (never automatic). "sent" needs a confirmed date. */
export function proposalActions(status: string): ("draft" | "ready" | "sent" | "accepted" | "declined")[] {
  switch (status) {
    case "draft":
      return ["ready"];
    case "ready":
      return ["draft", "sent"];
    case "sent":
      return ["accepted", "declined"];
    default:
      return [];
  }
}

export const ACTIVITY_TYPES: Exclude<Activity["activity_type"], "system" | "proposal_sent">[] = [
  "note",
  "call",
  "meeting",
  "email_sent",
  "email_received",
  "letter_sent",
  "other",
];

export function isSystemActivity(a: Pick<Activity, "activity_type">): boolean {
  return a.activity_type === "system" || a.activity_type === "proposal_sent";
}

export function isClosed(deal: Pick<Deal, "status">): boolean {
  return deal.status !== "open";
}

export function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
}

/** A brief statement is either plain text (human edit) or {text, evidence, basis} (AI content). */
export type BriefStatement = { text: string; evidence: string[]; basis: "observed" | "hypothesis" | null };

export function toStatement(value: unknown): BriefStatement | null {
  if (typeof value === "string") return value.trim() ? { text: value, evidence: [], basis: null } : null;
  if (value && typeof value === "object") {
    const v = value as { text?: unknown; evidence?: unknown; basis?: unknown };
    if (typeof v.text !== "string" || !v.text.trim()) return null;
    return {
      text: v.text,
      evidence: Array.isArray(v.evidence) ? v.evidence.filter((e): e is string => typeof e === "string") : [],
      basis: v.basis === "observed" || v.basis === "hypothesis" ? v.basis : null,
    };
  }
  return null;
}

export function toStatements(value: unknown): BriefStatement[] {
  if (Array.isArray(value)) return value.map(toStatement).filter((s): s is BriefStatement => s !== null);
  const one = toStatement(value);
  return one ? [one] : [];
}

/** Brief sections: `kind` says how the editable text is split (single text vs one item per line). */
export const BRIEF_SECTIONS = [
  { key: "main_opportunity_title", label: "Main opportunity title", kind: "text" },
  { key: "company_summary", label: "Company summary", kind: "text" },
  { key: "observed_situation", label: "Observed situation", kind: "list" },
  { key: "main_opportunity", label: "Main opportunity", kind: "text" },
  { key: "supporting_evidence", label: "Supporting evidence", kind: "list" },
  { key: "assumptions_and_uncertainty", label: "Assumptions and uncertainty", kind: "list" },
  { key: "potential_impact", label: "Potential impact (qualitative)", kind: "list" },
  { key: "suggested_solution", label: "Suggested solution", kind: "text" },
  { key: "implementation_requirements", label: "Implementation requirements", kind: "list" },
  { key: "discovery_questions", label: "Discovery questions", kind: "list" },
  { key: "recommended_next_action", label: "Recommended next action (internal)", kind: "text" },
] as const;
export type BriefSectionKey = (typeof BRIEF_SECTIONS)[number]["key"];

/** The text a person sees/edits for a section: the human edit when present, otherwise the AI content. */
export function sectionText(content: Record<string, unknown> | null | undefined, key: string, kind: "text" | "list"): string {
  const value = content?.[key];
  if (kind === "text") return toStatements(value).map((s) => s.text).join("\n");
  if (Array.isArray(value)) return value.map((v) => toStatement(v)?.text ?? "").filter(Boolean).join("\n");
  return toStatements(value).map((s) => s.text).join("\n");
}

export function downloadText(text: string, filename: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Local date-time input value ("YYYY-MM-DDTHH:mm") for an ISO instant. */
export function toLocalInput(iso: Date | string): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
