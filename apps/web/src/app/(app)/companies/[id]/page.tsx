"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { EnrichmentActions } from "@/components/leads/enrichment-actions";
import { BasisBadge, capitalize, ConfidenceBadge, StatusBadge } from "@/components/research/badges";
import { ExternalLink } from "@/components/research/external-link";
import { OpportunityCard } from "@/components/research/opportunity-card";
import { StartFeedback } from "@/components/research/start-feedback";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage, type CompanyDetail, type Evidence, type ResearchRun, type ResearchRunStartResult } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { isActiveStatus, parseProfile, usesFixtureModel } from "@/lib/research";
import { useApi, usePolling } from "@/lib/use-api";

export default function CompanyDetailPage() {
  return (
    <RequireOrganization>
      <CompanyPage />
    </RequireOrganization>
  );
}

function CompanyPage() {
  const { id } = useParams<{ id: string }>();
  const { data: company, error, loading, reload } = useApi(
    () => api.GET("/api/v1/companies/{company_id}", { params: { path: { company_id: id } } }),
    [id],
  );
  usePolling(reload, isActiveStatus(company?.research_status), 3000);

  if (loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!company)
    return (
      <EmptyState title="Company not found" action={<ButtonLink href="/companies">Back to companies</ButtonLink>}>
        {error ? "It may have been removed, or it belongs to a different organization." : "Not available."}
      </EmptyState>
    );
  return <CompanyView company={company} reload={reload} />;
}

function ExistingNotice() {
  const params = useSearchParams();
  if (params.get("existing") !== "1") return null;
  return <Alert tone="info">This company already existed in your workspace, so no duplicate was created.</Alert>;
}

function CompanyView({ company, reload }: { company: CompanyDetail; reload: () => void }) {
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ResearchRunStartResult | null>(null);
  const active = isActiveStatus(company.research_status);
  const researched = !!company.latest_run_id;

  async function startResearch() {
    setPending(true);
    setActionError(null);
    setFeedback(null);
    try {
      const { data, error } = await api.POST("/api/v1/research-runs", { body: { company_ids: [company.id] } });
      if (!data) {
        setActionError(errorMessage(error, "Could not start research."));
        return;
      }
      setFeedback(data);
      reload();
    } catch {
      setActionError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <PageHeader
        title={company.name}
        actions={
          <>
            {company.latest_run_id ? (
              <ButtonLink href={`/research-runs/${company.latest_run_id}`} variant="secondary">
                View research run
              </ButtonLink>
            ) : null}
            <Button onClick={() => void startResearch()} disabled={pending || active || !company.website_url}>
              {researched ? "Research again" : "Start research"}
            </Button>
          </>
        }
      />
      <div className="space-y-6">
        <div className="-mt-4 flex flex-wrap items-center gap-3 text-sm text-slate-400">
          {company.website_url ? (
            <ExternalLink href={company.website_url}>{company.canonical_domain ?? company.website_url}</ExternalLink>
          ) : (
            <span>No website saved</span>
          )}
          <StatusBadge status={company.research_status} />
          {company.last_researched_at ? <span>Last researched {formatDate(company.last_researched_at)}</span> : null}
        </div>
        <Suspense>
          <ExistingNotice />
        </Suspense>
        {!company.website_url ? <Alert tone="warning">This company has no website, so it cannot be researched.</Alert> : null}
        {actionError ? <Alert>{actionError}</Alert> : null}
        {feedback ? <StartFeedback result={feedback} names={{ [company.id]: company.name }} /> : null}
        <EnrichmentPanel company={company} />
        {company.latest_run_id ? (
          <Results key={`${company.latest_run_id}:${company.research_status}`} company={company} runId={company.latest_run_id} />
        ) : (
          <EmptyState title="Not researched yet">
            No research has been run for this company. Start research to fetch its public website, extract evidence and generate
            AI opportunity suggestions.
          </EmptyState>
        )}
      </div>
    </>
  );
}

function EnrichmentPanel({ company }: { company: CompanyDetail }) {
  const signals = useApi(() => api.GET("/api/v1/companies/{company_id}/signals", { params: { path: { company_id: company.id } } }), [company.id]);
  const run = signals.data?.enrichment_run ?? null;
  const active = isActiveStatus(run?.status);
  usePolling(signals.reload, active, 3000);
  return (
    <Card>
      <h2 className="text-lg font-medium text-white">Enrichment &amp; score</h2>
      <p className="mt-1 text-sm text-slate-400">Find dated growth triggers and buying intent on the public website, then score the lead.</p>
      <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Latest enrichment</dt>
          <dd className="mt-1">{signals.loading ? "…" : run ? <StatusBadge status={run.status} /> : <Badge tone="muted">Not enriched</Badge>}</dd>
        </div>
        {run ? (
          <div>
            <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Run</dt>
            <dd className="mt-1">
              <Link href={`/research-runs/${run.id}`} className="text-accent hover:underline">
                View enrichment run
              </Link>
            </dd>
          </div>
        ) : null}
        <div>
          <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Lead score</dt>
          <dd className="mt-1">
            <Link href={`/leads/${company.id}`} className="text-accent hover:underline">
              Open lead detail
            </Link>
          </dd>
        </div>
      </dl>
      {signals.error && !signals.data ? <div className="mt-4"><Alert>{signals.error}</Alert></div> : null}
      <div className="mt-4">
        <EnrichmentActions companyId={company.id} hasWebsite={!!company.website_url} busy={active} onDone={signals.reload} />
      </div>
    </Card>
  );
}

function Results({ company, runId }: { company: CompanyDetail; runId: string }) {
  const run = useApi(() => api.GET("/api/v1/research-runs/{run_id}", { params: { path: { run_id: runId } } }), [runId]);
  const evidence = useApi(() => api.GET("/api/v1/companies/{company_id}/evidence", { params: { path: { company_id: company.id } } }), [company.id]);
  const sources = useApi(() => api.GET("/api/v1/companies/{company_id}/sources", { params: { path: { company_id: company.id } } }), [company.id]);
  const opps = useApi(() => api.GET("/api/v1/companies/{company_id}/opportunities", { params: { path: { company_id: company.id } } }), [company.id]);

  const profile = parseProfile(company.profile);
  const finished = !!company.profile_run_id;
  const evidenceList = evidence.data ?? [];
  const labelById = Object.fromEntries(evidenceList.map((e) => [e.id, e.label]));
  const models = [...(run.data?.models_used ?? []), ...profile.models];

  return (
    <>
      {usesFixtureModel(models) ? (
        <Alert tone="warning">Results produced by the offline test double (fixture-rules-v1), not by a real AI model.</Alert>
      ) : null}

      <Card>
        <h2 className="text-lg font-medium text-white">Company profile</h2>
        {!finished || (!profile.hasContent && !company.short_description && !company.industry) ? (
          <p className="mt-3 text-sm text-slate-400">
            {isActiveStatus(company.research_status)
              ? "Research is in progress. The profile will appear when it finishes."
              : "No finished research yet, so there is no profile to show."}
          </p>
        ) : (
          <dl className="mt-4 grid gap-5 sm:grid-cols-2">
            {profile.fields.length === 0 ? (
              <>
                <Fact label="Description">{company.short_description}</Fact>
                <Fact label="Industry">{company.industry}</Fact>
                <Fact label="Location">{company.location}</Fact>
              </>
            ) : (
              profile.fields.map((f) => (
                <div key={f.key}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{f.label}</dt>
                  <dd className="mt-1 space-y-2 text-sm text-slate-200">
                    {f.values.map((v, i) => (
                      <div key={i}>
                        <p>{v.value}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          <BasisBadge basis={v.basis} />
                          <ConfidenceBadge confidence={v.confidence} />
                          {v.evidenceId && labelById[v.evidenceId] ? <Badge tone="muted">{labelById[v.evidenceId]}</Badge> : null}
                        </div>
                      </div>
                    ))}
                  </dd>
                </div>
              ))
            )}
          </dl>
        )}
        {finished && profile.unknownFields.length > 0 ? (
          <div className="mt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Unknown</h3>
            <ul className="mt-2 flex flex-wrap gap-2">
              {profile.unknownFields.map((f) => (
                <li key={f}>
                  <Badge tone="muted">{capitalize(f)}: Unknown</Badge>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {finished && profile.observedSignals.length > 0 ? (
          <div className="mt-5">
            <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Observed signals</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-300">
              {profile.observedSignals.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      <ResearchSummary run={run.data} error={run.error} />

      <Card>
        <h2 className="text-lg font-medium text-white">Evidence</h2>
        {evidence.error && !evidence.data ? <p className="mt-3 text-sm text-red-300">{evidence.error}</p> : null}
        {evidence.data && evidenceList.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">No evidence has been recorded for this company yet.</p>
        ) : null}
        {evidenceList.length > 0 ? (
          <ul className="mt-4 space-y-4">
            {evidenceList.map((ev) => (
              <EvidenceItem key={ev.id} evidence={ev} />
            ))}
          </ul>
        ) : null}
      </Card>

      <Card>
        <details>
          <summary className="cursor-pointer text-lg font-medium text-white">Sources{sources.data ? ` (${sources.data.length})` : ""}</summary>
          {sources.data && sources.data.length === 0 ? <p className="mt-3 text-sm text-slate-400">No pages were fetched.</p> : null}
          {sources.error && !sources.data ? <p className="mt-3 text-sm text-red-300">{sources.error}</p> : null}
          <ul className="mt-4 divide-y divide-line">
            {sources.data?.map((s) => (
              <li key={s.id} className="flex flex-col gap-1 py-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={s.extraction_status === "extracted" ? "accent" : s.extraction_status === "failed" ? "danger" : "muted"}>
                    {capitalize(s.extraction_status)}
                  </Badge>
                  <span className="text-xs text-slate-400">{capitalize(s.page_category)}</span>
                  {s.http_status ? <span className="text-xs text-slate-500">HTTP {s.http_status}</span> : null}
                </div>
                {s.page_title ? <p className="text-slate-200">{s.page_title}</p> : null}
                <ExternalLink href={s.source_url}>{s.source_url}</ExternalLink>
                {s.extraction_error ? <p className="text-xs text-red-300">{s.extraction_error}</p> : null}
              </li>
            ))}
          </ul>
        </details>
      </Card>

      <section aria-labelledby="ai-opps" className="space-y-4">
        <h2 id="ai-opps" className="text-lg font-medium text-white">
          AI opportunities
        </h2>
        {opps.error && !opps.data ? <Alert>{opps.error}</Alert> : null}
        {opps.data && opps.data.length === 0 ? (
          <EmptyState title="No AI opportunities">
            {run.data?.audit_summary ??
              (run.data?.ai_status === "unavailable"
                ? "The AI audit did not run because no AI provider is configured."
                : "The audit did not produce evidence-backed opportunities for this company.")}
          </EmptyState>
        ) : null}
        {opps.data?.map((op) => <OpportunityCard key={op.id} opportunity={op} />)}
      </section>
    </>
  );
}

function ResearchSummary({ run, error }: { run: ResearchRun | null; error: string | null }) {
  return (
    <Card>
      <h2 className="text-lg font-medium text-white">Research summary</h2>
      {error && !run ? <p className="mt-3 text-sm text-red-300">{error}</p> : null}
      {run ? (
        <>
          <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Latest run</dt>
              <dd className="mt-1">
                <StatusBadge status={run.status} />
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">Pages fetched</dt>
              <dd className="mt-1 text-slate-200">{run.pages_fetched}</dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">AI status</dt>
              <dd className="mt-1 text-slate-200">{capitalize(run.ai_status)}</dd>
            </div>
          </dl>
          {run.ai_status === "unavailable" ? (
            <div className="mt-4">
              <Alert tone="warning">AI analysis unavailable — no AI provider is configured. Only deterministic website research was performed.</Alert>
            </div>
          ) : null}
          {run.audit_summary ? <p className="mt-4 whitespace-pre-wrap text-sm text-slate-300">{run.audit_summary}</p> : null}
        </>
      ) : null}
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: string | null }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-200">{children || "Unknown"}</dd>
    </div>
  );
}

function EvidenceItem({ evidence: ev }: { evidence: Evidence }) {
  return (
    <li className="rounded-md border border-line bg-navy-950/50 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">{ev.label}</Badge>
        <span className="text-xs text-slate-400">{capitalize(ev.evidence_type)}</span>
        <BasisBadge basis={ev.basis} />
        <ConfidenceBadge confidence={ev.confidence} />
        <Badge tone="muted">{ev.origin === "llm" ? "AI extraction" : "Deterministic parser"}</Badge>
      </div>
      <p className="mt-2 text-slate-100">{ev.observed_fact}</p>
      <blockquote className="mt-2 border-l-2 border-accent/40 pl-3 text-slate-400">{ev.supporting_excerpt}</blockquote>
      {ev.source_url ? (
        <p className="mt-2 text-xs">
          Source: <ExternalLink href={ev.source_url}>{ev.source_url}</ExternalLink>
        </p>
      ) : null}
    </li>
  );
}
