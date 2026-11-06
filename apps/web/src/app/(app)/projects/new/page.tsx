"use client";

import { useRouter } from "next/navigation";

import { ProjectForm } from "@/components/forms/project-form";
import { RequireOrganization } from "@/components/require-organization";
import { Card, PageHeader } from "@/components/ui/surface";

export default function NewProjectPage() {
  const router = useRouter();
  return (
    <>
      <PageHeader title="New research project" description="Projects are visible to every member of your organization." />
      <RequireOrganization>
        <Card className="max-w-2xl">
          <ProjectForm onCreated={(p) => router.push(`/projects/${p.id}`)} />
        </Card>
      </RequireOrganization>
    </>
  );
}
