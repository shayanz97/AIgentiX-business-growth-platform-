"use client";

import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, writeErrorMessage, type Deal, type Stage } from "@/lib/api";
import { allowedNextStages, STAGE_LABELS, STAGE_REQUIREMENTS } from "@/lib/sales";

/**
 * Accessible stage controls: a "Move to…" select listing only the allowed next stages, plus Close (won/lost)
 * for open deals and Reopen for closed ones. The API enforces the rules; its message is shown inline.
 */
export function StageControls({ deal, onChanged }: { deal: Deal; onChanged: (deal: Deal) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [panel, setPanel] = useState<"close" | "reopen" | null>(null);
  const next = allowedNextStages(deal.stage);
  const closed = deal.status !== "open";

  async function move(stage: Stage) {
    setError(null);
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/stage", {
        params: { path: { deal_id: deal.id } },
        body: { stage, expected_version: deal.version },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not change the stage."));
      else onChanged(data);
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        {!closed ? (
          <label className="block min-w-0 flex-1 text-xs text-slate-400">
            <span className="sr-only">Move {deal.title} to stage</span>
            <select
              aria-label={`Move ${deal.title} to…`}
              className={control}
              value=""
              disabled={pending}
              onChange={(e) => e.target.value && void move(e.target.value as Stage)}
            >
              <option value="">Move to…</option>
              {next.map((s) => (
                <option key={s} value={s}>
                  {STAGE_LABELS[s]}
                  {STAGE_REQUIREMENTS[s] ? ` (${STAGE_REQUIREMENTS[s]})` : ""}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {!closed ? (
          <Button variant="secondary" aria-label={`Close ${deal.title}`} onClick={() => setPanel(panel === "close" ? null : "close")} aria-expanded={panel === "close"}>
            Close…
          </Button>
        ) : (
          <Button variant="secondary" aria-label={`Reopen ${deal.title}`} onClick={() => setPanel(panel === "reopen" ? null : "reopen")} aria-expanded={panel === "reopen"}>
            Reopen…
          </Button>
        )}
      </div>
      {error ? <Alert>{error}</Alert> : null}
      {panel === "close" ? <CloseForm deal={deal} onDone={(d) => { setPanel(null); onChanged(d); }} /> : null}
      {panel === "reopen" ? <ReopenForm deal={deal} onDone={(d) => { setPanel(null); onChanged(d); }} /> : null}
    </div>
  );
}

function CloseForm({ deal, onDone }: { deal: Deal; onDone: (deal: Deal) => void }) {
  const [outcome, setOutcome] = useState<"won" | "lost">("won");
  const [wonValue, setWonValue] = useState("");
  const [lostReason, setLostReason] = useState("");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (outcome === "won" && wonValue.trim() && !(Number(wonValue) >= 0)) return setError("The won value must be a number of 0 or more.");
    if (outcome === "lost" && !lostReason.trim()) return setError("Record why the deal was lost.");
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/close", {
        params: { path: { deal_id: deal.id } },
        body: {
          outcome,
          expected_version: deal.version,
          won_value: outcome === "won" && wonValue.trim() ? wonValue.trim() : null,
          lost_reason: outcome === "lost" ? lostReason.trim() : null,
          note: note.trim() || null,
        },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not close the opportunity."));
      else onDone(data);
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Close opportunity" className="space-y-3 rounded-md border border-line bg-navy-950/50 p-3">
      <label className="block">
        <span className={labelText}>Outcome</span>
        <select className={control} value={outcome} onChange={(e) => setOutcome(e.target.value as "won" | "lost")}>
          <option value="won">Won</option>
          <option value="lost">Lost</option>
        </select>
      </label>
      {outcome === "won" ? (
        <label className="block">
          <span className={labelText}>Won value ({deal.currency}, optional)</span>
          <input className={control} inputMode="decimal" value={wonValue} onChange={(e) => setWonValue(e.target.value)} />
        </label>
      ) : (
        <label className="block">
          <span className={labelText}>Lost reason</span>
          <input className={control} value={lostReason} maxLength={500} onChange={(e) => setLostReason(e.target.value)} />
        </label>
      )}
      <label className="block">
        <span className={labelText}>Note (optional)</span>
        <input className={control} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error ? <Alert>{error}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Confirm close"}
      </Button>
    </form>
  );
}

function ReopenForm({ deal, onDone }: { deal: Deal; onDone: (deal: Deal) => void }) {
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!reason.trim()) return setError("A reason is required to reopen a closed deal.");
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/reopen", {
        params: { path: { deal_id: deal.id } },
        body: { reason: reason.trim(), expected_version: deal.version },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not reopen the opportunity."));
      else onDone(data);
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Reopen opportunity" className="space-y-3 rounded-md border border-line bg-navy-950/50 p-3">
      <label className="block">
        <span className={labelText}>Reason for reopening</span>
        <input className={control} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </label>
      {error ? <Alert>{error}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Confirm reopen"}
      </Button>
    </form>
  );
}
