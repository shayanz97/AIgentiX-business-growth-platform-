"use client";

import { useState } from "react";

import { ProjectList } from "@/components/project-list";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 20;

export default function ProjectsPage() {
  return (
    <>
      <PageHeader
        title="Research projects"
        description="Lead Intelligence · companies you are researching"
        actions={<ButtonLink href="/projects/new">New project</ButtonLink>}
      />
      <RequireOrganization>
        <Projects />
      </RequireOrganization>
    </>
  );
}

function Projects() {
  const [offset, setOffset] = useState(0);
  const { data, error, loading } = useApi(
    () => api.GET("/api/v1/projects", { params: { query: { limit: PAGE_SIZE, offset } } }),
    [offset],
  );

  if (error) return <Alert>{error}</Alert>;
  if (loading || !data) return <p className="text-sm text-slate-400">Loading…</p>;
  if (data.total === 0)
    return (
      <EmptyState title="No research projects yet" action={<ButtonLink href="/projects/new">Create a project</ButtonLink>}>
        Start by adding a company you want to research.
      </EmptyState>
    );

  return (
    <div className="space-y-4">
      <ProjectList projects={data.items} />
      <div className="flex items-center justify-between text-sm text-slate-400">
        <span>
          {offset + 1}–{offset + data.items.length} of {data.total}
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            Previous
          </Button>
          <Button variant="secondary" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
