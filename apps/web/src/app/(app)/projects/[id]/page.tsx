"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";

import { StatusBadge } from "@/components/research/badges";
import { StartFeedback } from "@/components/research/start-feedback";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage, type Company, type ResearchRunStartResult } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export default function ProjectDetailPage() {
  return (
    <RequireOrganization>
      <ProjectDetail />
    </RequireOrganization>
  );
}

function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: project, error, loading } = useApi(
    () => api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: id } } }),
    [id],
  );

  const companies = useApi(
    () => api.GET("/api/v1/projects/{project_id}/companies", { params: { path: { project_id: id }, query: { limit: 50 } } }),
    [id],
  );

  if (loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (error || !project)
    return (
      <EmptyState title="Project not found" action={<ButtonLink href="/projects">Back to projects</ButtonLink>}>
        It may have been removed, or it belongs to a different organization.
      </EmptyState>
    );

  return (
    <>
      <PageHeader title={project.name} actions={<ButtonLink href="/projects" variant="secondary">All projects</ButtonLink>} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <dl className="grid gap-5 sm:grid-cols-2">
            <Detail label="Status">
              <Badge>{project.status}</Badge>
            </Detail>
            <Detail label="Company website">
              {project.target_url ? (
                <a href={project.target_url} target="_blank" rel="noopener noreferrer nofollow" className="text-accent hover:underline">
                  {project.target_url}
                </a>
              ) : (
                "—"
              )}
            </Detail>
            <Detail label="Created">{formatDate(project.created_at)}</Detail>
            <Detail label="Last updated">{formatDate(project.updated_at)}</Detail>
            <div className="sm:col-span-2">
              <Detail label="Notes">
                <p className="whitespace-pre-wrap">{project.description || "—"}</p>
              </Detail>
            </div>
          </dl>
        </Card>
        <Card className="space-y-3">
          <h2 className="font-medium text-slate-100">Research</h2>
          <p className="text-sm text-slate-400">Research every company in this project, or add more companies to it.</p>
          <ProjectResearchActions projectId={project.id} companies={companies.data?.items ?? []} total={companies.data?.total ?? 0} onStarted={companies.reload} />
        </Card>
      </div>
      <ProjectCompanies projectId={project.id} companies={companies.data?.items ?? []} total={companies.data?.total ?? 0} loading={companies.loading} error={companies.data ? null : companies.error} />
    </>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 text-sm text-slate-200">{children}</dd>
    </div>
  );
}

function ProjectResearchActions({
  projectId,
  companies,
  total,
  onStarted,
}: {
  projectId: string;
  companies: Company[];
  total: number;
  onStarted: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResearchRunStartResult | null>(null);

  async function researchAll() {
    setPending(true);
    setError(null);
    setResult(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/research-runs", { body: { project_id: projectId } });
      if (!data) {
        setError(errorMessage(apiError, "Could not start research."));
        return;
      }
      setResult(data);
      onStarted();
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-col items-start gap-3">
        <Button onClick={() => void researchAll()} disabled={pending || total === 0}>
          {pending ? "Starting…" : "Research all companies"}
        </Button>
        <Link href={`/companies/new?project=${projectId}`} className="text-sm text-accent hover:underline">
          Import companies into this project
        </Link>
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {result ? <StartFeedback result={result} names={Object.fromEntries(companies.map((c) => [c.id, c.name]))} /> : null}
    </div>
  );
}

function ProjectCompanies({
  projectId,
  companies,
  total,
  loading,
  error,
}: {
  projectId: string;
  companies: Company[];
  total: number;
  loading: boolean;
  error: string | null;
}) {
  return (
    <section aria-labelledby="project-companies" className="mt-8 space-y-3">
      <h2 id="project-companies" className="text-lg font-medium text-white">
        Companies in this project
      </h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {!loading && !error && total === 0 ? (
        <EmptyState title="No companies in this project" action={<ButtonLink href={`/companies/new?project=${projectId}`}>Add companies</ButtonLink>}>
          Add a company or import a CSV list into this project to research them together.
        </EmptyState>
      ) : null}
      {companies.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Companies in this project">
          {companies.map((c) => (
            <li key={c.id}>
              <Link href={`/companies/${c.id}`} className="flex flex-col gap-1 px-5 py-4 hover:bg-navy-800/60 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-100">{c.name}</p>
                  <p className="truncate text-sm text-slate-400">{c.canonical_domain ?? "No website"}</p>
                </div>
                <StatusBadge status={c.research_status} />
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {total > companies.length ? <p className="text-sm text-slate-400">Showing the first {companies.length} of {total} companies.</p> : null}
    </section>
  );
}
