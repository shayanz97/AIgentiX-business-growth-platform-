"use client";

import { ProjectList } from "@/components/project-list";
import { RequireOrganization } from "@/components/require-organization";
import { ButtonLink } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

export default function DashboardPage() {
  const { me, membership } = useSession();
  return (
    <>
      <PageHeader
        title={`Welcome${me.user.full_name ? `, ${me.user.full_name}` : ""}`}
        description={membership ? `${membership.organization.name} · ${membership.role}` : undefined}
        actions={membership ? <ButtonLink href="/projects/new">New research project</ButtonLink> : undefined}
      />
      <RequireOrganization>
        <Overview />
      </RequireOrganization>
    </>
  );
}

function Overview() {
  const projects = useApi(() => api.GET("/api/v1/projects", { params: { query: { limit: 5 } } }));
  const runs = useApi(() => api.GET("/api/v1/workflows", { params: { query: { limit: 1 } } }));
  const modules = useApi(() => api.GET("/api/v1/modules"));

  return (
    <div className="space-y-8">
      {projects.error ? <Alert>{projects.error}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <p className="text-sm text-slate-400">Research projects</p>
          <p className="mt-2 text-3xl font-semibold text-white" data-testid="project-count">
            {projects.data ? projects.data.total : "—"}
          </p>
        </Card>
        <Card>
          <p className="text-sm text-slate-400">Workflow runs</p>
          <p className="mt-2 text-3xl font-semibold text-white">{runs.data ? runs.data.total : "—"}</p>
          <p className="mt-1 text-xs text-slate-500">Automated research runs arrive in a later release.</p>
        </Card>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Recent projects</h2>
        {projects.loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : projects.data && projects.data.items.length > 0 ? (
          <ProjectList projects={projects.data.items} />
        ) : (
          <EmptyState title="No research projects yet" action={<ButtonLink href="/projects/new">Create your first project</ButtonLink>}>
            A research project collects a target company and, in upcoming releases, its research, opportunity audit and score.
          </EmptyState>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Modules</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {modules.data?.map((m) => (
            <Card key={m.key} className="p-5">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-medium text-slate-100">{m.name}</h3>
                <Badge tone={m.status === "available" ? "accent" : "muted"}>
                  {m.status === "available" ? "Available" : "Planned"}
                </Badge>
              </div>
              <p className="mt-2 text-sm text-slate-400">{m.description}</p>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
