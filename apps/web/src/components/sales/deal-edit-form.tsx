"use client";

import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, writeErrorMessage, type Deal, type Member, type Priority } from "@/lib/api";
import { parseLines, PRIORITIES } from "@/lib/sales";

export function DealEditForm({ deal, members, onSaved }: { deal: Deal; members: Member[]; onSaved: (deal: Deal) => void }) {
  const [title, setTitle] = useState(deal.title);
  const [description, setDescription] = useState(deal.description);
  const [value, setValue] = useState(deal.estimated_value ?? "");
  const [currency, setCurrency] = useState(deal.currency);
  const [priority, setPriority] = useState<Priority>(deal.priority);
  const [closeDate, setCloseDate] = useState(deal.expected_close_date ?? "");
  const [owner, setOwner] = useState(deal.owner_user_id ?? "");
  const [requirements, setRequirements] = useState(deal.confirmed_requirements.join("\n"));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (!title.trim()) return setError("Enter a title.");
    if (value.trim() && !(Number(value) >= 0)) return setError("The value must be a number of 0 or more.");
    if (!/^[A-Za-z]{3}$/.test(currency)) return setError("Use a 3-letter currency code.");
    setPending(true);
    try {
      const { data, response, error: apiError } = await api.PATCH("/api/v1/sales/opportunities/{deal_id}", {
        params: { path: { deal_id: deal.id } },
        body: {
          expected_version: deal.version,
          title: title.trim(),
          description: description.trim(),
          estimated_value: value.trim() || null,
          currency: currency.toUpperCase(),
          priority,
          expected_close_date: closeDate || null,
          owner_user_id: owner || null,
          confirmed_requirements: parseLines(requirements),
        },
      });
      if (!data) setError(writeErrorMessage(response?.status, apiError, "Could not save the changes."));
      else {
        setSaved(true);
        onSaved(data);
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Edit opportunity" className="grid gap-4 rounded-lg border border-line bg-navy-900/70 p-4 sm:grid-cols-2">
      <label className="block sm:col-span-2">
        <span className={labelText}>Title</span>
        <input className={control} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Description</span>
        <textarea className={`${control} min-h-20`} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Estimated value (optional)</span>
        <input className={control} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Currency</span>
        <input className={control} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Priority</span>
        <select className={control} value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Expected close date</span>
        <input type="date" className={control} value={closeDate} onChange={(e) => setCloseDate(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Owner</span>
        <select className={control} value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value="">Unassigned</option>
          {members.map((m) => (
            <option key={m.user.id} value={m.user.id}>
              {m.user.full_name || m.user.email}
            </option>
          ))}
        </select>
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Confirmed requirements (one per line)</span>
        <textarea className={`${control} min-h-24`} value={requirements} onChange={(e) => setRequirements(e.target.value)} />
        <span className="mt-1 block text-xs text-slate-400">Only list what the customer has confirmed. Proposals treat everything else as unknown.</span>
      </label>
      <div className="space-y-2 sm:col-span-2">
        {error ? <Alert>{error}</Alert> : null}
        {saved ? (
          <p role="status" className="text-sm text-slate-300">
            Changes saved.
          </p>
        ) : null}
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
