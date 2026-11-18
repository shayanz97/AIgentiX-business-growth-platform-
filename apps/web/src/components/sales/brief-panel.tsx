"use client";

import { useState } from "react";

import { control } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, writeErrorMessage, type Brief, type BriefEdit } from "@/lib/api";
import { BRIEF_SECTIONS, humanizeKey, isGenerating, parseLines, sectionText, toStatements } from "@/lib/sales";
import { useApi, usePolling } from "@/lib/use-api";

function mergedContent(brief: Brief): Record<string, unknown> {
  return { ...brief.content, ...(brief.edited_content ?? {}) };
}

function BriefStatusBadge({ status }: { status: Brief["status"] }) {
  const tone = status === "approved" ? "accent" : status === "failed" ? "danger" : status === "generating" ? "warning" : "neutral";
  return <Badge tone={tone}>{humanizeKey(status)}</Badge>;
}

/** Sales brief (Sales Intelligence). AI content and human edits are kept apart; nothing is approved automatically. */
export function BriefPanel({ dealId, closed }: { dealId: string; closed: boolean }) {
  const briefs = useApi(() => api.GET("/api/v1/sales/opportunities/{deal_id}/briefs", { params: { path: { deal_id: dealId } } }), [dealId]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const list = briefs.data ?? [];
  const current = list.find((b) => b.status !== "superseded") ?? null;
  const generating = list.some((b) => isGenerating(b.status));
  usePolling(briefs.reload, generating, 2000);

  async function generate() {
    setError(null);
    setStarting(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/briefs", { params: { path: { deal_id: dealId } } });
      if (!data) setError(errorMessage(apiError, "Could not start the brief."));
      else briefs.reload();
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section aria-labelledby="brief" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="brief" className="text-lg font-medium text-white">
          Sales brief
        </h2>
        <Button variant="secondary" onClick={() => void generate()} disabled={starting || generating || closed}>
          {generating ? "Generating…" : current ? "Regenerate brief" : "Generate brief"}
        </Button>
      </div>
      <p className="text-sm text-slate-400">
        An AI-drafted summary of what the research evidence shows. Observed statements cite evidence; hypotheses are interpretation. Review it before relying on it.
      </p>
      {error ? <Alert>{error}</Alert> : null}
      {briefs.error && !briefs.data ? <Alert>{briefs.error}</Alert> : null}
      {briefs.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {briefs.data && !current ? <p className="text-sm text-slate-400">No brief yet.</p> : null}
      {current ? <BriefView key={`${current.id}-${current.version}`} brief={current} onChanged={briefs.reload} /> : null}
    </section>
  );
}

function BriefView({ brief, onChanged }: { brief: Brief; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const content = mergedContent(brief);
  const edited = brief.edited_content ?? {};
  const usable = brief.status === "draft" || brief.status === "approved";

  async function approve() {
    setError(null);
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.PATCH("/api/v1/sales/briefs/{brief_id}", {
        params: { path: { brief_id: brief.id } },
        body: { status: "approved", expected_version: brief.version },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not approve the brief."));
      else onChanged();
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-line bg-navy-900/70 p-4" data-testid="brief">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <BriefStatusBadge status={brief.status} />
        {brief.model ? <span data-testid="brief-model">Model: {brief.model}</span> : null}
        <span>Prompt version: {brief.generation_version}</span>
        {brief.edited_by_user_id ? <Badge tone="neutral">Edited by a person</Badge> : null}
      </div>

      {isGenerating(brief.status) ? (
        <p role="status" className="text-sm text-slate-300">
          Generating the brief… {brief.workflow ? `${brief.workflow.progress}%` : ""}
        </p>
      ) : null}
      {brief.status === "failed" ? <Alert>{brief.message ?? brief.workflow?.error_message ?? "Brief generation failed."}</Alert> : null}
      {brief.status !== "failed" && brief.message ? <Alert tone="info">{brief.message}</Alert> : null}
      {brief.quality_flags.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5" aria-label="Quality flags">
          {brief.quality_flags.map((f) => (
            <Badge key={f} tone="warning">
              {humanizeKey(f)}
            </Badge>
          ))}
        </div>
      ) : null}

      {usable && !editing ? (
        <>
          <div className="space-y-4">
            {BRIEF_SECTIONS.map((s) => {
              const items = toStatements(content[s.key]);
              if (items.length === 0) return null;
              return (
                <div key={s.key}>
                  <h3 className="text-sm font-medium text-slate-200">
                    {s.label}
                    {s.key in edited ? <span className="ml-2 text-xs font-normal text-slate-500">edited</span> : null}
                  </h3>
                  <ul className="mt-1 space-y-1.5">
                    {items.map((st, i) => (
                      <li key={i} className="text-sm text-slate-300">
                        <span className="whitespace-pre-wrap">{st.text}</span>{" "}
                        {st.basis ? <Badge tone={st.basis === "observed" ? "accent" : "muted"}>{st.basis === "observed" ? "Observed" : "Hypothesis"}</Badge> : null}{" "}
                        {st.evidence.map((e) => (
                          <Badge key={e} tone="neutral">
                            {e}
                          </Badge>
                        ))}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Edit brief
            </Button>
            {brief.status === "draft" ? (
              <Button onClick={() => void approve()} disabled={pending}>
                {pending ? "Approving…" : "Approve brief"}
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
      {usable && editing ? <BriefEditor brief={brief} onCancel={() => setEditing(false)} onSaved={onChanged} /> : null}
      {error ? <Alert>{error}</Alert> : null}
    </div>
  );
}

function BriefEditor({ brief, onCancel, onSaved }: { brief: Brief; onCancel: () => void; onSaved: () => void }) {
  const content = mergedContent(brief);
  const initial: Record<string, string> = {};
  for (const s of BRIEF_SECTIONS) initial[s.key] = sectionText(content, s.key, s.kind);
  const [values, setValues] = useState(initial);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // PATCH replaces edited_content, so keep earlier human edits and add the sections changed now.
    const next: Record<string, unknown> = { ...(brief.edited_content ?? {}) };
    for (const s of BRIEF_SECTIONS) {
      const v = values[s.key] ?? "";
      if (v === initial[s.key]) continue;
      next[s.key] = s.kind === "text" ? v.trim() : parseLines(v);
    }
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.PATCH("/api/v1/sales/briefs/{brief_id}", {
        params: { path: { brief_id: brief.id } },
        body: { edited_content: next as BriefEdit, expected_version: brief.version },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not save the brief."));
      else {
        onSaved();
        onCancel();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void save(e)} aria-label="Edit sales brief" className="space-y-4">
      <p className="text-xs text-slate-400">Your edits are saved separately; the AI-generated content is kept unchanged. List sections take one item per line.</p>
      {BRIEF_SECTIONS.map((s) => (
        <label key={s.key} className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-200">{s.label}</span>
          <textarea
            className={`${control} ${s.kind === "list" ? "min-h-28" : "min-h-16"}`}
            value={values[s.key]}
            onChange={(e) => setValues({ ...values, [s.key]: e.target.value })}
          />
        </label>
      ))}
      {error ? <Alert>{error}</Alert> : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save edits"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
