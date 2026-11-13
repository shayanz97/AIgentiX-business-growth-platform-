"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Profile } from "@/lib/api";
import { humanize } from "@/lib/leads";
import { COMPANY_TYPES, icpConfigFromForm, icpFormFromConfig, SOLUTION_CATEGORIES, type IcpForm } from "@/lib/profiles";

const control =
  "block w-full rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:opacity-60";

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** ICP (ideal customer profile) editor. Read-only for non-owners. */
export function IcpProfileEditor({ profile, canEdit, onSaved }: { profile: Profile; canEdit: boolean; onSaved: () => void }) {
  const [form, setForm] = useState<IcpForm>(() => icpFormFromConfig(profile.config));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const disabled = !canEdit;

  function patch<K extends keyof IcpForm>(key: K, value: IcpForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  const noCategory = form.categories.length === 0;
  const noType = form.companyTypes.length === 0;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (noCategory || noType) return;
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/icp-profiles/{profile_id}", {
        params: { path: { profile_id: profile.id } },
        body: { config: icpConfigFromForm(form) },
      });
      if (!data) setError(errorMessage(apiError, "Could not save the ICP profile."));
      else {
        setSaved(true);
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void save(e)} className="space-y-6" aria-label={`Edit ICP profile ${profile.name}`}>
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="block text-sm font-medium text-slate-200 sm:col-span-3">
          <span className="mb-1.5 block">Countries (ISO codes, comma-separated)</span>
          <input value={form.countries} disabled={disabled} onChange={(e) => patch("countries", e.target.value)} className={control} placeholder="DE, AT, CH" />
        </label>
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Minimum employees</span>
          <input type="number" min={1} value={form.minEmployees} disabled={disabled} onChange={(e) => patch("minEmployees", e.target.value)} className={control} />
        </label>
        <label className="block text-sm font-medium text-slate-200">
          <span className="mb-1.5 block">Maximum employees</span>
          <input type="number" min={1} value={form.maxEmployees} disabled={disabled} onChange={(e) => patch("maxEmployees", e.target.value)} className={control} />
        </label>
        <label className="block text-sm font-medium text-slate-200 sm:col-span-3">
          <span className="mb-1.5 block">Target industries (comma-separated, empty = any)</span>
          <input value={form.targetIndustries} disabled={disabled} onChange={(e) => patch("targetIndustries", e.target.value)} className={control} />
        </label>
        <label className="block text-sm font-medium text-slate-200 sm:col-span-3">
          <span className="mb-1.5 block">Excluded industries (comma-separated)</span>
          <input value={form.excludedIndustries} disabled={disabled} onChange={(e) => patch("excludedIndustries", e.target.value)} className={control} />
        </label>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-white">Solution categories</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {SOLUTION_CATEGORIES.map((c) => (
            <label key={c} className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={form.categories.includes(c)} disabled={disabled} onChange={() => patch("categories", toggle(form.categories, c))} />
              {humanize(c)}
            </label>
          ))}
        </div>
        {noCategory ? <p className="text-xs text-amber-300">Select at least one solution category.</p> : null}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-white">Company types</legend>
        <div className="flex gap-6">
          {COMPANY_TYPES.map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={form.companyTypes.includes(t)} disabled={disabled} onChange={() => patch("companyTypes", toggle(form.companyTypes, t))} />
              {t.toUpperCase()}
            </label>
          ))}
        </div>
        {noType ? <p className="text-xs text-amber-300">Select at least one company type.</p> : null}
      </fieldset>

      {canEdit ? (
        <div className="space-y-3">
          <Button type="submit" disabled={pending || noCategory || noType}>
            {pending ? "Saving…" : "Save ICP profile"}
          </Button>
          {error ? <Alert>{error}</Alert> : null}
          {saved ? (
            <Alert tone="info">
              <span role="status">Saved as a new version. Re-score leads to apply it.</span>
            </Alert>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
