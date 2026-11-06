"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { StatusBadge } from "@/components/research/badges";
import { StartFeedback } from "@/components/research/start-feedback";
import { RequireOrganization } from "@/components/require-organization";
import { Button, ButtonLink } from "@/components/ui/button";
import { Alert, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage, type ResearchRunStartResult } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const PAGE_SIZE = 20;

export default function CompaniesPage() {
  return (
    <>
      <PageHeader
        title="Companies"
        description="Lead Intelligence · every company in your workspace"
        actions={<ButtonLink href="/companies/new">Add companies</ButtonLink>}
      />
      <RequireOrganization>
        <Companies />
      </RequireOrganization>
    </>
  );
}

function Companies() {
  const [offset, setOffset] = useState(0);
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<ResearchRunStartResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi(
    () => api.GET("/api/v1/companies", { params: { query: { limit: PAGE_SIZE, offset, q: q || undefined } } }),
    [offset, q],
  );

  const selectedIds = Object.keys(selected);
  const names = useMemo(() => selected, [selected]);

  function search(event: FormEvent) {
    event.preventDefault();
    setOffset(0);
    setQ(draft.trim());
  }

  function toggle(id: string, name: string) {
    setSelected((prev) => {
      const next = { ...prev };
      if (id in next) delete next[id];
      else next[id] = name;
      return next;
    });
  }

  async function researchSelected() {
    setPending(true);
    setActionError(null);
    setFeedback(null);
    try {
      const { data: result, error: apiError } = await api.POST("/api/v1/research-runs", { body: { company_ids: selectedIds } });
      if (!result) {
        setActionError(errorMessage(apiError, "Could not start research."));
        return;
      }
      setFeedback(result);
      setSelected({});
      reload();
    } catch {
      setActionError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <form onSubmit={search} role="search" className="flex gap-2">
          <div>
            <label htmlFor="company-search" className="sr-only">
              Search companies
            </label>
            <input
              id="company-search"
              type="search"
              value={draft}
              maxLength={100}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search by name or domain"
              className="block w-full min-w-0 rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30 sm:w-72"
            />
          </div>
          <Button type="submit" variant="secondary">
            Search
          </Button>
        </form>
        <Button onClick={() => void researchSelected()} disabled={pending || selectedIds.length === 0}>
          {pending ? "Starting…" : "Research selected"}
          {selectedIds.length > 0 && !pending ? ` (${selectedIds.length})` : ""}
        </Button>
      </div>

      {actionError ? <Alert>{actionError}</Alert> : null}
      {feedback ? <StartFeedback result={feedback} names={names} /> : null}

      {error && !data ? <Alert>{error}</Alert> : null}
      {loading || (!data && !error) ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {data && data.total === 0 ? (
        q ? (
          <EmptyState title="No companies match your search">Try a different name or domain.</EmptyState>
        ) : (
          <EmptyState title="No companies yet" action={<ButtonLink href="/companies/new">Add companies</ButtonLink>}>
            Add a company website or import a CSV list to start researching.
          </EmptyState>
        )
      ) : null}

      {data && data.total > 0 ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-line bg-navy-900/70">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Companies</caption>
              <thead className="border-b border-line text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label="Select all companies on this page"
                      checked={data.items.length > 0 && data.items.every((c) => c.id in selected)}
                      onChange={(e) =>
                        setSelected((prev) => {
                          const next = { ...prev };
                          for (const c of data.items) {
                            if (e.target.checked) next[c.id] = c.name;
                            else delete next[c.id];
                          }
                          return next;
                        })
                      }
                      className="size-4 accent-[var(--color-accent)]"
                    />
                  </th>
                  <th scope="col" className="px-2 py-3 font-medium">
                    Name
                  </th>
                  <th scope="col" className="hidden px-2 py-3 font-medium sm:table-cell">
                    Domain
                  </th>
                  <th scope="col" className="hidden px-2 py-3 font-medium md:table-cell">
                    Industry
                  </th>
                  <th scope="col" className="px-2 py-3 font-medium">
                    Research status
                  </th>
                  <th scope="col" className="hidden px-2 py-3 font-medium lg:table-cell">
                    Last research
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((c) => (
                  <tr key={c.id} className="hover:bg-navy-800/40">
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label={`Select ${c.name}`}
                        checked={c.id in selected}
                        onChange={() => toggle(c.id, c.name)}
                        className="size-4 accent-[var(--color-accent)]"
                      />
                    </td>
                    <td className="max-w-[12rem] px-2 py-3 sm:max-w-xs">
                      <Link href={`/companies/${c.id}`} className="block truncate font-medium text-slate-100 hover:text-accent">
                        {c.name}
                      </Link>
                      <span className="block truncate text-xs text-slate-400 sm:hidden">{c.canonical_domain}</span>
                    </td>
                    <td className="hidden px-2 py-3 text-slate-300 sm:table-cell">{c.canonical_domain ?? "—"}</td>
                    <td className="hidden px-2 py-3 text-slate-300 md:table-cell">{c.industry ?? "—"}</td>
                    <td className="px-2 py-3">
                      <StatusBadge status={c.research_status} />
                    </td>
                    <td className="hidden px-2 py-3 text-slate-400 lg:table-cell">{c.last_researched_at ? formatDate(c.last_researched_at) : "Never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
        </>
      ) : null}
    </div>
  );
}
