"use client";

import Link from "next/link";
import { useState } from "react";

import { BasisBadge, capitalize, ConfidenceBadge } from "@/components/research/badges";
import { ExternalLink } from "@/components/research/external-link";
import { Button } from "@/components/ui/button";
import { TextAreaField } from "@/components/ui/field";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, type Opportunity, type OpportunityStatus } from "@/lib/api";
import { qualityFlagText } from "@/lib/research";

const STATUS_TONE: Record<OpportunityStatus, "neutral" | "accent" | "danger" | "warning"> = {
  proposed: "neutral",
  under_review: "warning",
  approved: "accent",
  rejected: "danger",
};

export function OpportunityStatusBadge({ status }: { status: OpportunityStatus }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{capitalize(status)}</Badge>;
}

const ACTIONS: { label: string; status: OpportunityStatus }[] = [
  { label: "Mark for review", status: "under_review" },
  { label: "Approve for investigation", status: "approved" },
  { label: "Reject", status: "rejected" },
];

/** One AI opportunity with its evidence and review controls. All text comes from a model and is rendered as plain text. */
export function OpportunityCard({
  opportunity,
  showCompany = false,
  onUpdated,
}: {
  opportunity: Opportunity;
  showCompany?: boolean;
  onUpdated?: (updated: Opportunity) => void;
}) {
  const [op, setOp] = useState(opportunity);
  const [note, setNote] = useState(opportunity.reviewer_note ?? "");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function patch(body: { status?: OpportunityStatus; reviewer_note?: string }, message: string) {
    setPending(true);
    setError(null);
    setSaved(null);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/opportunities/{opportunity_id}", {
        params: { path: { opportunity_id: op.id } },
        body,
      });
      if (!data) {
        setError(errorMessage(apiError, "Could not update the opportunity."));
        return;
      }
      setOp(data);
      setNote(data.reviewer_note ?? "");
      setSaved(message);
      onUpdated?.(data);
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const headingId = `opp-${op.id}`;
  return (
    <article aria-labelledby={headingId} className="space-y-5 rounded-lg border border-line bg-navy-900/70 p-5 sm:p-6">
      <header className="space-y-2">
        {showCompany ? (
          <p className="text-sm">
            <Link href={`/companies/${op.company_id}`} className="text-accent hover:underline">
              {op.company_name}
            </Link>
          </p>
        ) : null}
        <h3 id={headingId} className="text-lg font-semibold text-white">
          {op.title}
        </h3>
        <div className="flex flex-wrap gap-2">
          <OpportunityStatusBadge status={op.status} />
          <ConfidenceBadge confidence={op.confidence} />
          <Badge>{capitalize(op.implementation_complexity)} complexity</Badge>
        </div>
      </header>

      {op.quality_flags.length > 0 ? (
        <ul className="space-y-2" aria-label="Quality warnings">
          {op.quality_flags.map((flag) => (
            <li key={flag}>
              <Alert tone="warning">{qualityFlagText(flag)}</Alert>
            </li>
          ))}
        </ul>
      ) : null}

      <dl className="grid gap-4 text-sm sm:grid-cols-2">
        <Item label="Observed context">{op.observed_context}</Item>
        <Item label="Hypothesis">{op.problem_hypothesis}</Item>
        <Item label="Proposed solution">{op.proposed_ai_solution}</Item>
        <Item label="Expected benefit">{op.estimated_business_impact}</Item>
        <Item label="Next step">{op.next_step}</Item>
      </dl>

      {op.assumptions.length > 0 ? <TextList title="Assumptions" items={op.assumptions} /> : null}
      {op.validation_questions.length > 0 ? <TextList title="Validation questions" items={op.validation_questions} /> : null}

      {op.evidence.length > 0 ? (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">Cited evidence</h4>
          <ul className="mt-2 space-y-3">
            {op.evidence.map((ev) => (
              <li key={ev.id} className="rounded-md border border-line bg-navy-950/50 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{ev.label}</Badge>
                  <span className="text-xs text-slate-400">{capitalize(ev.evidence_type)}</span>
                  <BasisBadge basis={ev.basis} />
                </div>
                <p className="mt-2 text-slate-200">{ev.observed_fact}</p>
                <blockquote className="mt-2 border-l-2 border-accent/40 pl-3 text-slate-400">{ev.supporting_excerpt}</blockquote>
                {ev.source_url ? (
                  <p className="mt-2 text-xs">
                    <ExternalLink href={ev.source_url}>{ev.source_url}</ExternalLink>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="space-y-3 border-t border-line pt-4">
        <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">Review</h4>
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map((a) => (
            <Button
              key={a.status}
              variant={a.status === "approved" ? "primary" : "secondary"}
              disabled={pending || op.status === a.status}
              onClick={() => void patch({ status: a.status }, `Status changed to ${capitalize(a.status).toLowerCase()}.`)}
            >
              {a.label}
            </Button>
          ))}
        </div>
        <TextAreaField label="Reviewer note" value={note} maxLength={5000} onChange={(e) => setNote(e.target.value)} />
        <Button variant="secondary" disabled={pending || note === (op.reviewer_note ?? "")} onClick={() => void patch({ reviewer_note: note }, "Note saved.")}>
          Save note
        </Button>
        {error ? <Alert>{error}</Alert> : null}
        {saved ? (
          <p role="status" className="text-sm text-accent">
            {saved}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function Item({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 whitespace-pre-wrap text-slate-200">{children || "—"}</dd>
    </div>
  );
}

function TextList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">{title}</h4>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-slate-300">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
