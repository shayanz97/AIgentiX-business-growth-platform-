"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { EnrichmentActions } from "@/components/leads/enrichment-actions";
import { IntentBadge, PriorityBadge, ProvisionalBadge, ReviewBadge, ScoreSummary } from "@/components/leads/lead-badges";
import { ScoreBreakdown, type EvidenceLike } from "@/components/leads/score-breakdown";
import { TriggerTimeline } from "@/components/leads/trigger-timeline";
import { StatusBadge } from "@/components/research/badges";
import { ExternalLink } from "@/components/research/external-link";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import {
  api,
  errorMessage,
  type CompanySignals,
  type FirstPartyIntentCreate,
  type Intent,
  type LeadDetail,
  type ReviewStatus,
} from "@/lib/api";
import { formatDate } from "@/lib/format";
import { formatCoverage, formatScoreRange, humanize, provisionalExplanation, REVIEW_STATUSES } from "@/lib/leads";
import { isActiveStatus } from "@/lib/research";
import { useApi, usePolling } from "@/lib/use-api";

const control =
  "block w-full rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";

export default function LeadDetailPage() {
  return (
    <RequireOrganization>
      <LeadPage />
    </RequireOrganization>
  );
}

function LeadPage() {
  const { id } = useParams<{ id: string }>();
  const company = useApi(() => api.GET("/api/v1/companies/{company_id}", { params: { path: { company_id: id } } }), [id]);
  const lead = useApi(() => api.GET("/api/v1/leads/{company_id}", { params: { path: { company_id: id } } }), [id]);
  const signals = useApi(() => api.GET("/api/v1/companies/{company_id}/signals", { params: { path: { company_id: id } } }), [id]);
  const evidence = useApi(() => api.GET("/api/v1/companies/{company_id}/evidence", { params: { path: { company_id: id } } }), [id]);
  const history = useApi(() => api.GET("/api/v1/companies/{company_id}/scores", { params: { path: { company_id: id }, query: { limit: 50 } } }), [id]);

  const enriching = isActiveStatus(signals.data?.enrichment_run?.status);
  function reloadAll() {
    lead.reload();
    signals.reload();
    evidence.reload();
    history.reload();
  }
  usePolling(reloadAll, enriching, 3000);

  if (company.loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!company.data)
    return (
      <EmptyState title="Lead not found" action={<ButtonLink href="/leads">Back to ranked leads</ButtonLink>}>
        It may have been removed, or it belongs to a different organization.
      </EmptyState>
    );
  const c = company.data;
  const score = lead.data?.lead?.score ?? null;

  const evidenceById: Record<string, EvidenceLike> = {};
  for (const ev of evidence.data ?? []) evidenceById[ev.id] = ev;
  for (const s of signals.data?.signals ?? []) for (const ev of s.evidence) evidenceById[ev.id] = ev;
  for (const i of signals.data?.intents ?? []) for (const ev of i.evidence) evidenceById[ev.id] = ev;

  return (
    <>
      <PageHeader
        title={c.name}
        description="Lead detail: score, evidence, growth triggers, buying intent and review."
        actions={
          <>
            <ButtonLink href={`/companies/${c.id}`} variant="secondary">
              Company page
            </ButtonLink>
            <ButtonLink href="/leads" variant="secondary">
              Ranked leads
            </ButtonLink>
          </>
        }
      />
      <div className="space-y-8">
        <div className="-mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-400">
          {c.website_url ? <ExternalLink href={c.website_url}>{c.canonical_domain ?? c.website_url}</ExternalLink> : <span>No website saved</span>}
          {signals.data?.enrichment_run ? <StatusBadge status={signals.data.enrichment_run.status} /> : null}
        </div>
        {lead.error && !lead.data ? <Alert>{lead.error}</Alert> : null}

        {lead.loading ? <p className="text-sm text-slate-400">Loading score…</p> : null}
        {!lead.loading && !score ? (
          <Card>
            <h2 className="text-lg font-medium text-white">Not scored yet</h2>
            <p className="mt-2 text-sm text-slate-400">
              This company has no lead score. Enrich it to collect growth triggers and buying intent from its website; it is scored automatically
              afterwards.
            </p>
            <div className="mt-4">
              <EnrichmentActions companyId={c.id} hasWebsite={!!c.website_url} busy={enriching} onDone={reloadAll} />
            </div>
          </Card>
        ) : null}

        {score && lead.data ? (
          <>
            <Summary detail={lead.data} />
            <section aria-labelledby="breakdown" className="space-y-3">
              <h2 id="breakdown" className="text-lg font-medium text-white">
                Score breakdown
              </h2>
              <p className="text-sm text-slate-400">{score.explanation}</p>
              {score.exclusion_reasons.length > 0 ? (
                <Alert tone="warning">Outside the ideal customer profile: {score.exclusion_reasons.join("; ")}</Alert>
              ) : null}
              <ScoreBreakdown components={score.components} evidence={evidenceById} />
              <CitedEvidence ids={score.evidence_ids} evidence={evidenceById} />
            </section>
          </>
        ) : null}

        <section aria-labelledby="triggers" className="space-y-3">
          <h2 id="triggers" className="text-lg font-medium text-white">
            Trigger timeline
          </h2>
          {signals.error && !signals.data ? <Alert>{signals.error}</Alert> : null}
          {signals.data ? (
            signals.data.enrichment_run || signals.data.signals.length > 0 ? (
              <TriggerTimeline signals={signals.data.signals} />
            ) : (
              <p className="text-sm text-slate-400">Not checked yet. Enrich this company to look for growth triggers.</p>
            )
          ) : null}
        </section>

        {signals.data ? <IntentSection companyId={c.id} signals={signals.data} onChanged={reloadAll} /> : null}

        {score && lead.data ? (
          <>
            <ReviewSection companyId={c.id} detail={lead.data} onChanged={lead.reload} />
            <section aria-labelledby="actions" className="space-y-3">
              <h2 id="actions" className="text-lg font-medium text-white">
                Actions
              </h2>
              <EnrichmentActions companyId={c.id} hasWebsite={!!c.website_url} busy={enriching} onDone={reloadAll} />
            </section>
          </>
        ) : null}

        <section aria-labelledby="history" className="space-y-3">
          <h2 id="history" className="text-lg font-medium text-white">
            Score history
          </h2>
          {history.data && history.data.items.length === 0 ? <p className="text-sm text-slate-400">No score snapshots yet.</p> : null}
          {history.data && history.data.items.length > 0 ? (
            <ol aria-label="Score history entries" className="divide-y divide-line rounded-lg border border-line bg-navy-900/70">
              {history.data.items.map((h) => (
                <li key={h.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-sm" data-testid="history-entry">
                  <span className="text-slate-200">{formatDate(h.created_at)}</span>
                  <span className="font-medium text-white">{formatScoreRange(h.score_low, h.score_high)}</span>
                  <span className="text-xs text-slate-400">coverage {formatCoverage(h.coverage)}</span>
                  <ProvisionalBadge provisional={h.provisional} />
                  <span className="text-xs text-slate-500">
                    scoring profile v{h.scoring_profile_version} · ICP v{h.icp_profile_version}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
        </section>
      </div>
    </>
  );
}

function Summary({ detail }: { detail: LeadDetail }) {
  const lead = detail.lead;
  if (!lead) return null;
  const s = lead.score;
  const why = provisionalExplanation(s);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Conservative score – upper bound</p>
          <ScoreSummary low={s.score_low} high={s.score_high} coverage={s.coverage} provisional={s.provisional} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PriorityBadge band={s.priority_band} />
          <IntentBadge status={s.intent_status} />
          <ReviewBadge status={lead.review_status} />
          <Badge tone="neutral">{humanize(s.confidence_level)} confidence</Badge>
        </div>
      </div>
      {why ? <Alert tone="warning">{why}</Alert> : null}
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Recommended next step</p>
        <p className="mt-1 text-sm text-slate-100">{s.next_step_text}</p>
      </div>
      <p className="text-xs text-slate-500">
        Scored on {s.reference_date} · {s.scoring_version} · scoring profile v{s.scoring_profile_version} · ICP profile v{s.icp_profile_version}
      </p>
    </Card>
  );
}

function CitedEvidence({ ids, evidence }: { ids: string[]; evidence: Record<string, EvidenceLike> }) {
  const items = ids.map((id) => evidence[id]).filter((e): e is EvidenceLike => !!e);
  if (items.length === 0) return null;
  return (
    <details className="rounded-lg border border-line bg-navy-900/70 p-4">
      <summary className="cursor-pointer text-sm font-medium text-slate-100">Cited evidence ({items.length})</summary>
      <ul className="mt-3 space-y-3">
        {items.map((ev) => (
          <li key={ev.id} className="text-sm">
            <Badge tone="accent">{ev.label}</Badge>
            <blockquote className="mt-1 border-l-2 border-accent/40 pl-3 text-slate-400">{ev.supporting_excerpt}</blockquote>
            {ev.source_url ? (
              <p className="mt-1 text-xs">
                Source: <ExternalLink href={ev.source_url}>{ev.source_url}</ExternalLink>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

function IntentItem({ intent: i }: { intent: Intent }) {
  return (
    <li className="rounded-md border border-line bg-navy-950/50 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">{humanize(i.strength)}</Badge>
        <Badge tone="neutral">{humanize(i.source_type)}</Badge>
        <Badge tone={i.active ? "accent" : "muted"}>{i.active ? "Active" : "Expired"}</Badge>
        {i.solution_category ? <Badge tone="muted">{humanize(i.solution_category)}</Badge> : null}
        {i.observed_on ? <span className="text-xs text-slate-400">Observed {i.observed_on}</span> : <span className="text-xs text-slate-400">Date unknown</span>}
        {i.deadline_on ? <span className="text-xs text-slate-400">Deadline {i.deadline_on}</span> : null}
      </div>
      <p className="mt-2 font-medium text-slate-100">{i.title}</p>
      {i.summary ? <p className="mt-1 whitespace-pre-wrap text-slate-300">{i.summary}</p> : null}
      {i.source_url ? (
        <p className="mt-1 text-xs">
          Source: <ExternalLink href={i.source_url}>{i.source_url}</ExternalLink>
        </p>
      ) : null}
      {i.evidence.map((ev) => (
        <blockquote key={ev.id} className="mt-2 border-l-2 border-accent/40 pl-3 text-xs text-slate-400">
          <Badge tone="muted">{ev.label}</Badge> {ev.supporting_excerpt}
        </blockquote>
      ))}
    </li>
  );
}

function IntentSection({ companyId, signals, onChanged }: { companyId: string; signals: CompanySignals; onChanged: () => void }) {
  return (
    <section aria-labelledby="intent" className="space-y-3">
      <h2 id="intent" className="text-lg font-medium text-white">
        Buying intent
      </h2>
      <div className="flex items-center gap-2">
        <IntentBadge status={signals.intent_status} />
      </div>
      {signals.intent_status === "none_verified" ? (
        <Alert tone="info">
          No verified buying intent found in the checked sources ({signals.sources_checked.length > 0 ? signals.sources_checked.map(humanize).join(", ") : "none listed"}) —
          this is not evidence that there is no need.
        </Alert>
      ) : null}
      {signals.intent_status === "unknown" ? <Alert tone="info">Not checked yet.</Alert> : null}
      {signals.intents.length > 0 ? (
        <ul className="space-y-3" aria-label="Buying intent signals">
          {signals.intents.map((i) => (
            <IntentItem key={i.id} intent={i} />
          ))}
        </ul>
      ) : null}
      {signals.ignored.length > 0 ? (
        <details className="rounded-md border border-line p-3 text-sm">
          <summary className="cursor-pointer text-slate-300">Ignored records ({signals.ignored.length})</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-400">
            {signals.ignored.map((t, idx) => (
              <li key={idx}>{t}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <FirstPartyForm companyId={companyId} onSaved={onChanged} />
    </section>
  );
}

const CHANNELS: FirstPartyIntentCreate["channel"][] = ["contact_form", "email", "phone", "event", "referral", "other"];
const CATEGORIES = [
  "customer_service_automation",
  "document_processing",
  "workflow_automation",
  "knowledge_assistant",
  "appointment_scheduling",
  "sales_crm_automation",
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function FirstPartyForm({ companyId, onSaved }: { companyId: string; onSaved: () => void }) {
  const [channel, setChannel] = useState<FirstPartyIntentCreate["channel"]>("contact_form");
  const [receivedOn, setReceivedOn] = useState(todayIso());
  const [summary, setSummary] = useState("");
  const [category, setCategory] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (!summary.trim()) return setError("Describe the inquiry.");
    if (!receivedOn || receivedOn > todayIso()) return setError("The received date must be today or earlier.");
    setPending(true);
    try {
      const { response, error: apiError } = await api.POST("/api/v1/companies/{company_id}/intent-signals", {
        params: { path: { company_id: companyId } },
        body: { channel, received_on: receivedOn, summary: summary.trim(), solution_category: category || null },
      });
      if (!response.ok) setError(errorMessage(apiError, "Could not save the inquiry."));
      else {
        setSaved(true);
        setSummary("");
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <details className="rounded-lg border border-line bg-navy-900/70 p-4">
      <summary className="cursor-pointer text-sm font-medium text-slate-100">Record a first-party inquiry</summary>
      <form onSubmit={(e) => void submit(e)} className="mt-4 grid gap-4 sm:grid-cols-2" aria-label="Record a first-party inquiry">
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Channel</span>
          <select value={channel} onChange={(e) => setChannel(e.target.value as FirstPartyIntentCreate["channel"])} className={control}>
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Received on</span>
          <input type="date" max={todayIso()} value={receivedOn} onChange={(e) => setReceivedOn(e.target.value)} className={control} />
        </label>
        <label className="block text-sm font-medium text-slate-200 sm:col-span-2">
          <span className="mb-1.5 block">Summary</span>
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={2000} className={`${control} min-h-20`} />
        </label>
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Solution category (optional)</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={control}>
            <option value="">Not specified</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save inquiry"}
          </Button>
        </div>
        <div className="sm:col-span-2">
          {error ? <Alert>{error}</Alert> : null}
          {saved ? (
            <p role="status" className="text-sm text-slate-300">
              Inquiry saved. Re-score to include it in the score.
            </p>
          ) : null}
        </div>
      </form>
    </details>
  );
}

function ReviewSection({ companyId, detail, onChanged }: { companyId: string; detail: LeadDetail; onChanged: () => void }) {
  const current = detail.lead?.review_status ?? "new";
  const [status, setStatus] = useState<ReviewStatus>(current);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/leads/{company_id}/review", {
        params: { path: { company_id: companyId } },
        body: { status, note: note.trim() || null },
      });
      if (!data) setError(errorMessage(apiError, "Could not save the review."));
      else {
        setSaved(true);
        setNote("");
        onChanged();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="review" className="space-y-3">
      <h2 id="review" className="text-lg font-medium text-white">
        Review
      </h2>
      <p className="text-sm text-slate-300">
        Current status: <ReviewBadge status={current} />
      </p>
      <form onSubmit={(e) => void save(e)} className="grid gap-4 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2" aria-label="Update review">
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Review status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value as ReviewStatus)} className={control}>
            {REVIEW_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Note (optional)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} className={control} />
        </label>
        <div className="sm:col-span-2">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Save review"}
          </Button>
        </div>
        <div className="sm:col-span-2">
          {error ? <Alert>{error}</Alert> : null}
          {saved ? (
            <p role="status" className="text-sm text-slate-300">
              Review saved.
            </p>
          ) : null}
        </div>
      </form>
      {detail.reviews.length > 0 ? (
        <ol aria-label="Review history" className="divide-y divide-line rounded-lg border border-line bg-navy-900/70">
          {detail.reviews.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <ReviewBadge status={r.status} />
              <span className="text-xs text-slate-400">{formatDate(r.created_at)}</span>
              {r.note ? <span className="text-slate-300">{r.note}</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

