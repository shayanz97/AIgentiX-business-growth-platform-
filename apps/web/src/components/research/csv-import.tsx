"use client";

import Link from "next/link";
import { useId, useState, type ChangeEvent } from "react";

import { ProjectSelect } from "@/components/research/project-select";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card } from "@/components/ui/surface";
import { api, errorMessage, type ImportResult, type ImportRow } from "@/lib/api";

export const MAX_CSV_BYTES = 512 * 1024;

const ROW_STATUS: Record<ImportRow["status"], { label: string; tone: "accent" | "neutral" | "warning" | "danger" }> = {
  new: { label: "New", tone: "accent" },
  existing: { label: "Already exists", tone: "neutral" },
  duplicate_in_file: { label: "Duplicate in file", tone: "warning" },
  invalid: { label: "Invalid", tone: "danger" },
};

export function CsvImport({ initialProjectId = "" }: { initialProjectId?: string }) {
  const fileId = useId();
  const [csvText, setCsvText] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [projectId, setProjectId] = useState(initialProjectId);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [report, setReport] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function reset() {
    setPreview(null);
    setReport(null);
    setError(null);
  }

  async function onFile(event: ChangeEvent<HTMLInputElement>) {
    reset();
    setCsvText(null);
    setFileName(null);
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_CSV_BYTES) {
      setError("This file is larger than 512 KB. Split it into smaller files of up to 100 companies.");
      return;
    }
    try {
      setCsvText(await file.text());
      setFileName(file.name);
    } catch {
      setError("The file could not be read.");
    }
  }

  async function run(dryRun: boolean) {
    if (csvText === null) return;
    setPending(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/companies/import", {
        body: { csv_text: csvText, dry_run: dryRun, project_id: projectId || null },
      });
      if (!data) {
        setError(errorMessage(apiError, "The import failed."));
        return;
      }
      if (dryRun) setPreview(data);
      else {
        setReport(data);
        setPreview(null);
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const importable = preview ? preview.new : 0;
  return (
    <div className="space-y-6">
      <div className="rounded-md border border-line bg-navy-950/50 p-4 text-sm text-slate-300">
        <p className="font-medium text-slate-100">Expected format</p>
        <p className="mt-1">
          A CSV file with a header row containing <code className="text-accent">name</code> and/or <code className="text-accent">website</code>{" "}
          columns. Up to 100 rows and 512 KB per file. Rows are checked first; nothing is saved until you confirm.
        </p>
        <pre className="mt-2 overflow-x-auto text-xs text-slate-400">{"name,website\nAcme Ltd,acme.example\nGlobex,https://globex.example"}</pre>
      </div>

      {error ? <Alert>{error}</Alert> : null}

      <div>
        <label htmlFor={fileId} className="mb-1.5 block text-sm font-medium text-slate-200">
          CSV file
        </label>
        <input
          id={fileId}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => void onFile(e)}
          className="block w-full text-sm text-slate-300 file:mr-3 file:rounded-md file:border file:border-line file:bg-navy-800 file:px-3 file:py-2 file:text-sm file:text-slate-100"
        />
        {fileName ? <p className="mt-1.5 text-xs text-slate-400">Selected: {fileName}</p> : null}
      </div>

      <ProjectSelect
        value={projectId}
        onChange={(id) => {
          setProjectId(id);
          reset();
        }}
      />

      <Button onClick={() => void run(true)} disabled={pending || csvText === null}>
        {pending && !preview ? "Checking…" : "Preview import"}
      </Button>

      {preview ? (
        <Card className="space-y-4 p-4 sm:p-6">
          <h3 className="font-medium text-slate-100">Import preview</h3>
          <Summary
            items={[
              ["Rows", preview.total_rows],
              ["New", preview.new],
              ["Already exist", preview.existing],
              ["Duplicates in file", preview.duplicates],
              ["Invalid", preview.invalid],
            ]}
          />
          <RowsTable rows={preview.rows} />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void run(false)} disabled={pending || (importable === 0 && !projectId)}>
              {pending ? "Importing…" : "Import companies"}
            </Button>
            {importable === 0 ? (
              <span className="text-sm text-slate-400">
                {projectId ? "No new companies; existing ones will be linked to the project." : "There are no new companies to import."}
              </span>
            ) : null}
          </div>
        </Card>
      ) : null}

      {report ? (
        <Card className="space-y-4 p-4 sm:p-6">
          <div role="status">
            <h3 className="font-medium text-slate-100">Import complete</h3>
            <Summary
              items={[
                ["Created", report.created],
                ["Already existed", report.existing],
                ["Linked to project", report.linked_to_project],
                ["Skipped (duplicates or invalid)", report.duplicates + report.invalid],
              ]}
            />
          </div>
          <Link href={projectId ? `/projects/${projectId}` : "/companies"} className="inline-block text-sm text-accent hover:underline">
            {projectId ? "Go to the project" : "View companies"}
          </Link>
          {projectId ? (
            <>
              {" "}
              <Link href="/companies" className="ml-4 inline-block text-sm text-accent hover:underline">
                View all companies
              </Link>
            </>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

function Summary({ items }: { items: [string, number][] }) {
  return (
    <dl className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-5">
      {items.map(([label, value]) => (
        <div key={label} className="rounded-md border border-line px-3 py-2">
          <dt className="text-xs text-slate-400">{label}</dt>
          <dd className="text-lg font-semibold text-white">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RowsTable({ rows }: { rows: ImportRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[32rem] text-left text-sm">
        <caption className="sr-only">Import preview rows</caption>
        <thead className="text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th scope="col" className="py-2 pr-3 font-medium">
              Line
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Name
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Website
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Status
            </th>
            <th scope="col" className="py-2 font-medium">
              Errors
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => {
            const meta = ROW_STATUS[row.status] ?? { label: row.status, tone: "neutral" as const };
            return (
              <tr key={`${row.line}-${row.website_url ?? row.name}`} className="align-top">
                <td className="py-2 pr-3 text-slate-400">{row.line}</td>
                <td className="py-2 pr-3 text-slate-100">{row.name || "—"}</td>
                <td className="break-all py-2 pr-3 text-slate-300">{row.canonical_domain ?? row.website_url ?? "—"}</td>
                <td className="py-2 pr-3">
                  <Badge tone={meta.tone}>{meta.label}</Badge>
                </td>
                <td className="py-2 text-red-300">{row.errors.length > 0 ? row.errors.join("; ") : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
