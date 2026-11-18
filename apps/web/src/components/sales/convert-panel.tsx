"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Opportunity } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/** Existing-opportunity id from a 409 conversion error (`error.details.existing_opportunity_id`). */
export function existingOpportunityId(error: unknown): string | null {
  const details = (error as { error?: { details?: { existing_opportunity_id?: unknown } } } | undefined)?.error?.details;
  return typeof details?.existing_opportunity_id === "string" ? details.existing_opportunity_id : null;
}

/**
 * "Convert to sales opportunity". One idempotency key per open of the form: retries reuse it, so a double click or a
 * network retry never creates two deals.
 */
export function ConvertPanel({ companyId }: { companyId: string }) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");

  function toggle() {
    if (!open) setKey(crypto.randomUUID());
    setOpen(!open);
  }

  return (
    <section aria-labelledby="convert" className="space-y-3">
      <h2 id="convert" className="text-lg font-medium text-white">
        Sales
      </h2>
      <p className="text-sm text-slate-400">This lead is ready for sales follow-up. Converting creates an opportunity in the pipeline; it does not contact anyone.</p>
      <Button onClick={toggle} aria-expanded={open}>
        Convert to sales opportunity
      </Button>
      {open ? <ConvertForm companyId={companyId} idempotencyKey={key} /> : null}
    </section>
  );
}

function ConvertForm({ companyId, idempotencyKey }: { companyId: string; idempotencyKey: string }) {
  const router = useRouter();
  const opportunities = useApi(() => api.GET("/api/v1/companies/{company_id}/opportunities", { params: { path: { company_id: companyId } } }), [companyId]);
  const [sourceId, setSourceId] = useState("");
  const [title, setTitle] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [existingId, setExistingId] = useState<string | null>(null);

  async function submit(allowAdditional: boolean) {
    setError(null);
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.POST("/api/v1/leads/{company_id}/convert", {
        params: { path: { company_id: companyId } },
        body: {
          idempotency_key: idempotencyKey,
          source_opportunity_id: sourceId || null,
          title: title.trim() || null,
          allow_additional: allowAdditional,
        },
      });
      if (data) {
        router.push(`/sales/opportunities/${data.opportunity.id}`);
        return;
      }
      if (response?.status === 409) {
        const id = existingOpportunityId(apiError);
        if (id) {
          setExistingId(id);
          setError(errorMessage(apiError, "This company already has a sales opportunity."));
          return;
        }
      }
      setError(errorMessage(apiError, "Could not convert the lead."));
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const list: Opportunity[] = opportunities.data ?? [];

  return (
    <form
      aria-label="Convert to sales opportunity"
      onSubmit={(e) => {
        e.preventDefault();
        void submit(false);
      }}
      className="grid gap-4 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2"
    >
      <label className="block">
        <span className={labelText}>Research opportunity (optional)</span>
        <select className={control} value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">None selected</option>
          {list.map((o) => (
            <option key={o.id} value={o.id}>
              {o.title}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Title (optional)</span>
        <input className={control} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <div className="space-y-3 sm:col-span-2">
        {error ? <Alert tone={existingId ? "warning" : "danger"}>{error}</Alert> : null}
        {existingId ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Link href={`/sales/opportunities/${existingId}`} className="text-accent hover:underline">
              Open the existing opportunity
            </Link>
            <Button variant="secondary" disabled={pending} onClick={() => void submit(true)}>
              Create an additional opportunity
            </Button>
          </div>
        ) : null}
        <Button type="submit" disabled={pending}>
          {pending ? "Converting…" : "Convert"}
        </Button>
      </div>
    </form>
  );
}
