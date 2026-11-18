"use client";

import { useState } from "react";

import { control } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, writeErrorMessage, type ProposalDetail, type ProposalRevision, type ProposalUpdate } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { downloadText, fromLocalInput, parseLines, proposalActions, PROPOSAL_STATUS_LABELS, sectionStatusLabel, toLocalInput } from "@/lib/sales";
import { useApi } from "@/lib/use-api";

/** Loads one proposal and shows its editor, preview, revisions and status actions. */
export function ProposalEditor({ proposalId, onChanged }: { proposalId: string; onChanged: () => void }) {
  const detail = useApi(() => api.GET("/api/v1/sales/proposals/{proposal_id}", { params: { path: { proposal_id: proposalId } } }), [proposalId]);
  const revisions = useApi(() => api.GET("/api/v1/sales/proposals/{proposal_id}/revisions", { params: { path: { proposal_id: proposalId } } }), [proposalId]);
  if (detail.loading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (!detail.data) return <Alert>{detail.error ?? "Could not load the proposal."}</Alert>;
  return (
    <ProposalBody
      key={detail.data.version}
      proposal={detail.data}
      revisions={revisions.data ?? []}
      onChanged={() => {
        detail.reload();
        revisions.reload();
        onChanged();
      }}
    />
  );
}

function ProposalBody({ proposal, revisions, onChanged }: { proposal: ProposalDetail; revisions: ProposalRevision[]; onChanged: () => void }) {
  const editable = proposal.status === "draft" || proposal.status === "ready";
  const [bodies, setBodies] = useState<Record<string, string>>(Object.fromEntries(proposal.sections.map((s) => [s.key, s.body])));
  const [statuses, setStatuses] = useState<Record<string, string>>(Object.fromEntries(proposal.sections.map((s) => [s.key, s.status])));
  const [assumptions, setAssumptions] = useState(proposal.assumptions.join("\n"));
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  async function patch(body: ProposalUpdate, failure: string) {
    setError(null);
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.PATCH("/api/v1/sales/proposals/{proposal_id}", {
        params: { path: { proposal_id: proposal.id } },
        body,
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, failure));
      else onChanged();
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  function saveRevision(e: React.FormEvent) {
    e.preventDefault();
    const sections = proposal.sections
      .filter((s) => bodies[s.key] !== s.body || statuses[s.key] !== s.status)
      .map((s) => ({ key: s.key, body: bodies[s.key] ?? s.body, status: (statuses[s.key] ?? s.status) as "draft" | "needs_input" }));
    const newAssumptions = parseLines(assumptions);
    const assumptionsChanged = newAssumptions.join("\n") !== proposal.assumptions.join("\n");
    if (sections.length === 0 && !assumptionsChanged) return setError("Change a section or the assumptions first.");
    void patch(
      {
        expected_version: proposal.version,
        sections: sections.length > 0 ? sections : null,
        assumptions: assumptionsChanged || sections.length > 0 ? newAssumptions : null,
        note: note.trim() || null,
      },
      "Could not save the revision.",
    );
  }

  async function exportMarkdown() {
    setExporting(true);
    setError(null);
    try {
      const { data: md, error: apiError } = await api.GET("/api/v1/sales/proposals/{proposal_id}/export", {
        params: { path: { proposal_id: proposal.id } },
        parseAs: "text",
      });
      if (typeof md !== "string") setError(errorMessage(apiError, "Could not export the proposal."));
      else downloadText(md, `${proposal.title.replace(/[^\w.-]+/g, "-").slice(0, 60) || "proposal"}.md`, "text/markdown;charset=utf-8");
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-4 rounded-md border border-line bg-navy-950/50 p-4" data-testid="proposal-editor">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <Badge tone="neutral">{PROPOSAL_STATUS_LABELS[proposal.status] ?? proposal.status}</Badge>
        <span data-testid="proposal-revision">Revision {proposal.current_revision}</span>
        {proposal.revision_origin ? <Badge tone="muted">{proposal.revision_origin === "ai" ? "AI draft" : "Edited by a person"}</Badge> : null}
        {proposal.model ? <span>Model: {proposal.model}</span> : null}
        {proposal.generation_version ? <span>Prompt version: {proposal.generation_version}</span> : null}
      </div>
      {proposal.quality_flags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Quality flags">
          {proposal.quality_flags.map((f) => (
            <Badge key={f} tone="warning">
              {f.replace(/_/g, " ")}
            </Badge>
          ))}
        </div>
      ) : null}
      {!editable ? <Alert tone="info">This proposal is {proposal.status}; its content can no longer be edited. Draft a new proposal to change it.</Alert> : null}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" aria-pressed={preview} onClick={() => setPreview((v) => !v)}>
          {preview ? "Back to editor" : "Preview"}
        </Button>
        <Button variant="secondary" onClick={() => void exportMarkdown()} disabled={exporting}>
          {exporting ? "Exporting…" : "Export Markdown"}
        </Button>
      </div>

      {preview ? (
        <article aria-label="Proposal preview" className="space-y-4">
          <h3 className="text-base font-semibold text-white">{proposal.title}</h3>
          {proposal.sections.map((s) => (
            <div key={s.key}>
              <h4 className="text-sm font-medium text-slate-200">
                {s.title} {s.status === "needs_input" ? <Badge tone="warning">Needs input</Badge> : null}
              </h4>
              <p className="whitespace-pre-wrap text-sm text-slate-300">{bodies[s.key]}</p>
            </div>
          ))}
        </article>
      ) : (
        <form onSubmit={saveRevision} aria-label="Edit proposal" className="space-y-4">
          {proposal.sections.map((s) => (
            <div key={s.key} className="space-y-1.5" data-testid={`section-${s.key}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor={`sec-${s.key}`} className="text-sm font-medium text-slate-200">
                  {s.title}
                </label>
                <div className="flex items-center gap-2">
                  {statuses[s.key] === "needs_input" ? <Badge tone="warning">{sectionStatusLabel("needs_input")}</Badge> : null}
                  {editable ? (
                    <select
                      aria-label={`Status of ${s.title}`}
                      className="rounded-md border border-line bg-navy-900 px-2 py-1 text-xs text-slate-200"
                      value={statuses[s.key]}
                      onChange={(e) => setStatuses({ ...statuses, [s.key]: e.target.value })}
                    >
                      <option value="draft">{sectionStatusLabel("draft")}</option>
                      <option value="needs_input">{sectionStatusLabel("needs_input")}</option>
                    </select>
                  ) : null}
                </div>
              </div>
              <textarea
                id={`sec-${s.key}`}
                className={`${control} min-h-24`}
                value={bodies[s.key]}
                maxLength={10000}
                readOnly={!editable}
                onChange={(e) => setBodies({ ...bodies, [s.key]: e.target.value })}
              />
            </div>
          ))}
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-200">Assumptions the customer must confirm (one per line)</span>
            <textarea className={`${control} min-h-20`} value={assumptions} readOnly={!editable} onChange={(e) => setAssumptions(e.target.value)} />
          </label>
          {editable ? (
            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-200">Revision note (optional)</span>
                <input className={control} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
              </label>
              <Button type="submit" disabled={pending}>
                {pending ? "Saving…" : "Save revision"}
              </Button>
            </div>
          ) : null}
        </form>
      )}

      {error ? <Alert>{error}</Alert> : null}
      <StatusActions proposal={proposal} busy={pending} onChange={patch} />

      <details className="rounded-md border border-line p-3 text-sm">
        <summary className="cursor-pointer text-slate-300">Revision history ({revisions.length})</summary>
        <ol aria-label="Revision history" className="mt-2 space-y-2">
          {revisions.map((r) => (
            <li key={r.id} className="text-slate-300" data-testid="revision-entry">
              <span className="font-medium">Revision {r.revision}</span> · {r.origin === "ai" ? "AI draft" : "Edited by a person"} · {formatDate(r.created_at)}
              {r.model ? ` · ${r.model}` : ""}
              {r.note ? <span className="block text-xs text-slate-400">Note: {r.note}</span> : null}
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function StatusActions({ proposal, busy, onChange }: { proposal: ProposalDetail; busy: boolean; onChange: (body: ProposalUpdate, failure: string) => Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [sentAt, setSentAt] = useState(toLocalInput(new Date()));
  const [dateError, setDateError] = useState<string | null>(null);
  const actions = proposalActions(proposal.status);
  if (actions.length === 0) return null;

  function markSent(e: React.FormEvent) {
    e.preventDefault();
    const iso = fromLocalInput(sentAt);
    if (!confirmed) return setDateError("Confirm that you sent this proposal outside AIgentiX.");
    if (!iso || new Date(iso).getTime() > Date.now() + 60_000) return setDateError("Enter the date you sent it (not in the future).");
    setDateError(null);
    void onChange({ status: "sent", sent_at: iso, expected_version: proposal.version }, "Could not mark the proposal as sent.");
  }

  const labels = { draft: "Back to draft", ready: "Mark as ready", sent: "Mark as sent…", accepted: "Mark as accepted", declined: "Mark as declined" } as const;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Proposal status">
        {actions.map((a) => (
          <Button
            key={a}
            variant="secondary"
            disabled={busy}
            aria-expanded={a === "sent" ? confirming : undefined}
            onClick={() => (a === "sent" ? setConfirming((v) => !v) : void onChange({ status: a, expected_version: proposal.version }, "Could not change the status."))}
          >
            {labels[a]}
          </Button>
        ))}
      </div>
      {confirming && actions.includes("sent") ? (
        <form onSubmit={markSent} role="group" aria-label="Confirm sent" className="space-y-3 rounded-md border border-amber-400/40 bg-amber-400/5 p-3">
          <p className="text-sm text-slate-200">AIgentiX does not send proposals. Record only what really happened.</p>
          <label className="flex items-start gap-2 text-sm text-slate-200">
            <input type="checkbox" className="mt-1" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I sent this outside AIgentiX
          </label>
          <label className="block text-sm">
            <span className="mb-1.5 block font-medium text-slate-200">Sent on</span>
            <input type="datetime-local" className={control} max={toLocalInput(new Date())} value={sentAt} onChange={(e) => setSentAt(e.target.value)} />
          </label>
          {dateError ? <Alert>{dateError}</Alert> : null}
          <Button type="submit" disabled={busy}>
            Confirm: mark as sent
          </Button>
        </form>
      ) : null}
    </div>
  );
}
