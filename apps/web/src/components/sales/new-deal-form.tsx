"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage } from "@/lib/api";
import { useApi } from "@/lib/use-api";

/** Manual opportunity for an existing company. Normally opportunities come from converting a reviewed lead. */
export function NewDealForm() {
  const router = useRouter();
  const companies = useApi(() => api.GET("/api/v1/companies", { params: { query: { limit: 100 } } }), []);
  const [companyId, setCompanyId] = useState("");
  const [title, setTitle] = useState("");
  const [value, setValue] = useState("");
  const [currency, setCurrency] = useState("EUR");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!companyId) return setError("Choose a company.");
    if (!title.trim()) return setError("Enter a title.");
    if (value.trim() && !(Number(value) >= 0)) return setError("The value must be a number of 0 or more.");
    if (!/^[A-Za-z]{3}$/.test(currency)) return setError("Use a 3-letter currency code.");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/opportunities", {
        body: { company_id: companyId, title: title.trim(), estimated_value: value.trim() || null, currency: currency.toUpperCase() },
      });
      if (!data) setError(errorMessage(apiError, "Could not create the opportunity."));
      else router.push(`/sales/opportunities/${data.id}`);
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="New opportunity" className="grid gap-4 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2">
      <p className="text-sm text-slate-400 sm:col-span-2">
        The usual way to create an opportunity is to convert a reviewed lead from its lead page. Use this form for a company you already work with.
      </p>
      <label className="block">
        <span className={labelText}>Company</span>
        <select className={control} value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">Select a company…</option>
          {(companies.data?.items ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Title</span>
        <input className={control} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Estimated value (optional)</span>
        <input className={control} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Currency</span>
        <input className={control} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
      </label>
      <div className="sm:col-span-2">
        {companies.error && !companies.data ? <Alert>{companies.error}</Alert> : null}
        {error ? <Alert>{error}</Alert> : null}
      </div>
      <div className="sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create opportunity"}
        </Button>
      </div>
    </form>
  );
}
