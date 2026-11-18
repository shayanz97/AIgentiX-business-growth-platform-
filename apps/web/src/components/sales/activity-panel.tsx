"use client";

import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert, Badge } from "@/components/ui/surface";
import { api, errorMessage, type Contact } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { ACTIVITY_TYPES, fromLocalInput, humanizeKey, isSystemActivity, toLocalInput } from "@/lib/sales";
import { useApi } from "@/lib/use-api";

/** Manual activity record + timeline. System events (stage moves, approvals) are styled differently. */
export function ActivityPanel({ dealId, contacts, onChanged }: { dealId: string; contacts: Contact[]; onChanged: () => void }) {
  const activities = useApi(
    () => api.GET("/api/v1/sales/opportunities/{deal_id}/activities", { params: { path: { deal_id: dealId }, query: { include_system: true, limit: 100 } } }),
    [dealId],
  );
  const [type, setType] = useState<(typeof ACTIVITY_TYPES)[number]>("note");
  const [description, setDescription] = useState("");
  const [occurred, setOccurred] = useState(toLocalInput(new Date()));
  const [contactId, setContactId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const iso = fromLocalInput(occurred);
    if (!description.trim()) return setError("Describe what happened.");
    if (!iso || new Date(iso).getTime() > Date.now() + 60_000) return setError("The date must be now or earlier: record what already happened.");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/opportunities/{deal_id}/activities", {
        params: { path: { deal_id: dealId } },
        body: { activity_type: type, description: description.trim(), occurred_at: iso, contact_id: contactId || null },
      });
      if (!data) setError(errorMessage(apiError, "Could not record the activity."));
      else {
        setDescription("");
        setOccurred(toLocalInput(new Date()));
        activities.reload();
        onChanged();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const contactName = (id: string | null) => (id ? contacts.find((c) => c.id === id)?.name : undefined);

  return (
    <section aria-labelledby="activities" className="space-y-3">
      <h2 id="activities" className="text-lg font-medium text-white">
        Activities
      </h2>
      <form onSubmit={(e) => void submit(e)} aria-label="Record activity" className="grid gap-3 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2">
        <label className="block">
          <span className={labelText}>Type</span>
          <select className={control} value={type} onChange={(e) => setType(e.target.value as (typeof ACTIVITY_TYPES)[number])}>
            {ACTIVITY_TYPES.map((t) => (
              <option key={t} value={t}>
                {humanizeKey(t)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={labelText}>Occurred at</span>
          <input type="datetime-local" className={control} max={toLocalInput(new Date())} value={occurred} onChange={(e) => setOccurred(e.target.value)} />
        </label>
        <label className="block sm:col-span-2">
          <span className={labelText}>Description</span>
          <textarea className={`${control} min-h-20`} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="block">
          <span className={labelText}>Contact (optional)</span>
          <select className={control} value={contactId} onChange={(e) => setContactId(e.target.value)}>
            <option value="">No contact</option>
            {contacts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : "Record activity"}
          </Button>
        </div>
        {error ? (
          <div className="sm:col-span-2">
            <Alert>{error}</Alert>
          </div>
        ) : null}
      </form>

      {activities.error && !activities.data ? <Alert>{activities.error}</Alert> : null}
      {activities.data && activities.data.length === 0 ? <p className="text-sm text-slate-400">No activities recorded yet.</p> : null}
      {activities.data && activities.data.length > 0 ? (
        <ol aria-label="Activity timeline" className="space-y-2">
          {activities.data.map((a) => {
            const system = isSystemActivity(a);
            const who = contactName(a.contact_id);
            return (
              <li
                key={a.id}
                data-testid={system ? "activity-system" : "activity"}
                className={
                  system
                    ? "rounded-md border border-dashed border-line px-4 py-2 text-xs italic text-slate-500"
                    : "rounded-md border border-line bg-navy-900/70 px-4 py-3 text-sm text-slate-200"
                }
              >
                <div className="flex flex-wrap items-center gap-2">
                  {system ? <Badge tone="muted">System</Badge> : <Badge tone="accent">{humanizeKey(a.activity_type)}</Badge>}
                  <span className="text-xs text-slate-400 not-italic">{formatDate(a.occurred_at)}</span>
                  {who ? <span className="text-xs text-slate-400 not-italic">with {who}</span> : null}
                </div>
                <p className="mt-1 whitespace-pre-wrap">{a.description}</p>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
