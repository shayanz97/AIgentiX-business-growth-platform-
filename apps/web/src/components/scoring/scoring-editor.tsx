"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Profile } from "@/lib/api";
import { validateWeights, weightsSum, WEIGHT_KEYS, humanize } from "@/lib/leads";
import { parseWeights, scoringConfigFromForm, scoringFormFromConfig, type ScoringForm } from "@/lib/profiles";

const control =
  "block w-full rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:opacity-60";

function Num({ label, value, onChange, disabled, step }: { label: string; value: string; onChange: (v: string) => void; disabled: boolean; step?: string }) {
  return (
    <label className="block text-sm font-medium text-slate-200">
      <span className="mb-1.5 block">{label}</span>
      <input type="number" inputMode="decimal" step={step} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className={control} />
    </label>
  );
}

/** Scoring profile editor. Read-only for non-owners; weights must add up to 100 before saving. */
export function ScoringProfileEditor({ profile, canEdit, onSaved }: { profile: Profile; canEdit: boolean; onSaved: () => void }) {
  const [form, setForm] = useState<ScoringForm>(() => scoringFormFromConfig(profile.config));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const weights = parseWeights(form);
  const sum = weightsSum(weights);
  const weightError = validateWeights(weights);
  const disabled = !canEdit;

  function patch<K extends keyof ScoringForm>(key: K, value: ScoringForm[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (weightError) return;
    setPending(true);
    setError(null);
    setSaved(false);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/scoring-profiles/{profile_id}", {
        params: { path: { profile_id: profile.id } },
        body: { config: scoringConfigFromForm(form) },
      });
      if (!data) setError(errorMessage(apiError, "Could not save the scoring profile."));
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
    <form onSubmit={(e) => void save(e)} className="space-y-6" aria-label={`Edit scoring profile ${profile.name}`}>
      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-white">Component weights</legend>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {WEIGHT_KEYS.map((k) => (
            <Num
              key={k}
              label={`${humanize(k)} weight`}
              value={form.weights[k]}
              disabled={disabled}
              onChange={(v) => patch("weights", { ...form.weights, [k]: v })}
            />
          ))}
        </div>
        <p role="status" className={`text-sm ${weightError ? "text-amber-300" : "text-slate-300"}`} data-testid="weights-sum">
          Total: {sum} / 100{weightError ? ` — ${weightError}` : ""}
        </p>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-white">Freshness bands (days since the event)</legend>
        <div className="grid grid-cols-3 gap-4">
          {(["recent", "moderate", "older"] as const).map((k) => (
            <Num key={k} label={`${humanize(k)} up to (days)`} value={form.bands[k]} disabled={disabled} onChange={(v) => patch("bands", { ...form.bands, [k]: v })} />
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-white">Freshness factors (0 – 1)</legend>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {(["recent", "moderate", "older", "historical", "unknown"] as const).map((k) => (
            <Num
              key={k}
              label={`${humanize(k)} factor`}
              step="0.05"
              value={form.factors[k]}
              disabled={disabled}
              onChange={(v) => patch("factors", { ...form.factors, [k]: v })}
            />
          ))}
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-medium text-white">Priority thresholds and coverage</legend>
        <div className="grid grid-cols-3 gap-4">
          <Num label="High threshold" value={form.thresholds.high} disabled={disabled} onChange={(v) => patch("thresholds", { ...form.thresholds, high: v })} />
          <Num label="Medium threshold" value={form.thresholds.medium} disabled={disabled} onChange={(v) => patch("thresholds", { ...form.thresholds, medium: v })} />
          <Num label="Minimum coverage (0 – 1)" step="0.05" value={form.minCoverage} disabled={disabled} onChange={(v) => patch("minCoverage", v)} />
        </div>
        <p className="text-xs text-slate-400">Scores below the minimum coverage are labelled provisional.</p>
      </fieldset>

      {canEdit ? (
        <div className="space-y-3">
          <Button type="submit" disabled={pending || !!weightError}>
            {pending ? "Saving…" : "Save scoring profile"}
          </Button>
          {error ? <Alert>{error}</Alert> : null}
          {saved ? (
            <Alert tone="info">
              <span role="status">
                Saved as a new version. Existing scores update when you re-score (the Re-score buttons on company, lead and project pages) — no crawling needed.
              </span>
            </Alert>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}
