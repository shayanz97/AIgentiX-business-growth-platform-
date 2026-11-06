"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { CompanyForm } from "@/components/forms/company-form";
import { CsvImport } from "@/components/research/csv-import";
import { RequireOrganization } from "@/components/require-organization";
import { cn } from "@/components/ui/cn";
import { Alert, Card, PageHeader } from "@/components/ui/surface";

type Tab = "single" | "csv";

export default function NewCompanyPage() {
  return (
    <>
      <PageHeader title="Add companies" description="Add one company by website, or import many from a CSV file." />
      <RequireOrganization>
        <Suspense fallback={<p className="text-sm text-slate-400">Loading…</p>}>
          <AddCompanies />
        </Suspense>
      </RequireOrganization>
    </>
  );
}

function AddCompanies() {
  const router = useRouter();
  const params = useSearchParams();
  const project = params.get("project") ?? "";
  const [tab, setTab] = useState<Tab>("single");
  const [existing, setExisting] = useState<{ id: string; name: string } | null>(null);

  return (
    <Card className="max-w-3xl">
      <div role="tablist" aria-label="Add companies" className="mb-6 flex gap-1 border-b border-line">
        {(
          [
            ["single", "Single website"],
            ["csv", "CSV import"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`panel-${key}`}
            onClick={() => setTab(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium",
              tab === key ? "border-accent text-white" : "border-transparent text-slate-400 hover:text-slate-100",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="space-y-4">
        {tab === "single" ? (
          <>
            {existing ? <Alert tone="info">{existing.name} already exists in your workspace. Opening it now…</Alert> : null}
            <CompanyForm
              initialProjectId={project}
              onCreated={(company, created) => {
                if (!created) setExisting({ id: company.id, name: company.name });
                router.push(`/companies/${company.id}${created ? "" : "?existing=1"}`);
              }}
            />
          </>
        ) : (
          <CsvImport initialProjectId={project} />
        )}
      </div>
    </Card>
  );
}
