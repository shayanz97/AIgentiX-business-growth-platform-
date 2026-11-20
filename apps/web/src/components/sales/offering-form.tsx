"use client";

import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Offering } from "@/lib/api";

/** Owner-only create/edit form for a service offering. The API also enforces ownership. */
export function OfferingForm({ offering, onSaved, onCancel }: { offering?: Offering; onSaved: () => void; onCancel?: () => void }) {
  const [name, setName] = useState(offering?.name ?? "");
  const [description, setDescription] = useState(offering?.description ?? "");
  const [category, setCategory] = useState(offering?.solution_category ?? "");
  const [amount, setAmount] = useState(offering?.price_amount ?? "");
  const [unit, setUnit] = useState(offering?.price_unit ?? "");
  const [currency, setCurrency] = useState(offering?.currency ?? "EUR");
  const [approved, setApproved] = useState(offering?.price_approved ?? false);
  const [active, setActive] = useState(offering?.active ?? true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (!name.trim()) return setError("Enter a name.");
    if (amount.trim() && !(Number(amount) >= 0)) return setError("The price must be a number of 0 or more.");
    if (!/^[A-Za-z]{3}$/.test(currency)) return setError("Use a 3-letter currency code.");
    if (approved && !amount.trim()) return setError("A price must be entered before it can be approved for proposals.");
    const body = {
      name: name.trim(),
      description: description.trim(),
      solution_category: category.trim() || null,
      price_amount: amount.trim() || null,
      price_unit: unit.trim() || null,
      currency: currency.toUpperCase(),
      price_approved: approved,
      active,
    };
    setPending(true);
    try {
      const result = offering
        ? await api.PATCH("/api/v1/sales/services/{offering_id}", { params: { path: { offering_id: offering.id } }, body })
        : await api.POST("/api/v1/sales/services", { body });
      if (!result.data) setError(errorMessage(result.error, "Could not save the service."));
      else {
        setSaved(true);
        if (!offering) {
          setName("");
          setDescription("");
          setCategory("");
          setAmount("");
          setUnit("");
          setApproved(false);
        }
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label={offering ? `Edit ${offering.name}` : "New service"} className="grid gap-4 sm:grid-cols-2">
      <label className="block">
        <span className={labelText}>Name</span>
        <input className={control} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Category (optional)</span>
        <input className={control} value={category} maxLength={60} onChange={(e) => setCategory(e.target.value)} />
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Description</span>
        <textarea className={`${control} min-h-20`} value={description} maxLength={5000} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Price amount (optional)</span>
        <input className={control} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Price unit (e.g. per month)</span>
        <input className={control} value={unit} maxLength={60} onChange={(e) => setUnit(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Currency</span>
        <input className={control} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />
      </label>
      <div className="space-y-2 self-end text-sm text-slate-200">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
          Price approved for proposals
        </label>
        {offering ? (
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active
          </label>
        ) : null}
      </div>
      <div className="space-y-2 sm:col-span-2">
        {error ? <Alert>{error}</Alert> : null}
        {saved ? (
          <p role="status" className="text-sm text-slate-300">
            Saved.
          </p>
        ) : null}
        <div className="flex gap-2">
          <Button type="submit" disabled={pending}>
            {pending ? "Saving…" : offering ? "Save changes" : "Create service"}
          </Button>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          ) : null}
        </div>
      </div>
    </form>
  );
}
