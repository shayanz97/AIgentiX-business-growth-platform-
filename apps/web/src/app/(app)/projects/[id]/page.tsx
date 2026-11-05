"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";

import { RequireOrganization } from "@/components/require-organization";
import { ButtonLink } from "@/components/ui/button";
import { Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
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
        <Card>
          <h2 className="font-medium text-slate-100">Research</h2>
          <p className="mt-2 text-sm text-slate-400">
            Automated company research, opportunity audit and scoring are not available yet. They will appear here once
            released.
          </p>
        </Card>
      </div>
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
