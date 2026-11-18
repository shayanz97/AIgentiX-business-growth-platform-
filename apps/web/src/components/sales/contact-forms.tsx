"use client";

import { useState } from "react";

import { control, labelText } from "@/components/sales/styles";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage, type Channel, type Company, type Contact, type ContactSource, type LawfulBasis } from "@/lib/api";
import { humanizeKey } from "@/lib/sales";

export const CONTACT_SOURCES: ContactSource[] = [
  "inbound_inquiry",
  "business_card",
  "event",
  "referral",
  "website_imprint",
  "website_contact_page",
  "existing_customer",
  "other",
];
export const LAWFUL_BASES: LawfulBasis[] = [
  "none",
  "explicit_consent",
  "existing_customer",
  "presumed_consent_b2b",
  "inbound_request",
  "legitimate_interest",
];
const CHANNELS: Channel[] = ["email", "phone", "letter", "linkedin"];

function Feedback({ error, saved }: { error: string | null; saved: string | null }) {
  return (
    <>
      {error ? <Alert>{error}</Alert> : null}
      {saved ? (
        <p role="status" className="text-sm text-slate-300">
          {saved}
        </p>
      ) : null}
    </>
  );
}

export function CreateContactForm({ companies, onSaved }: { companies: Company[]; onSaved: () => void }) {
  const [companyId, setCompanyId] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [source, setSource] = useState<ContactSource | "">("");
  const [sourceNote, setSourceNote] = useState("");
  const [basis, setBasis] = useState<LawfulBasis>("none");
  const [basisRef, setBasisRef] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    if (!companyId) return setError("Choose a company.");
    if (!name.trim()) return setError("Enter the contact's name.");
    if (!source) return setError("Record where this contact came from (source is required).");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/contacts", {
        body: {
          company_id: companyId,
          name: name.trim(),
          role: role.trim() || null,
          business_email: email.trim() || null,
          business_phone: phone.trim() || null,
          source,
          source_note: sourceNote.trim() || null,
          lawful_basis: basis,
          lawful_basis_reference: basisRef.trim() || null,
        },
      });
      if (!data) setError(errorMessage(apiError, "Could not save the contact."));
      else {
        setSaved("Contact saved.");
        setName("");
        setRole("");
        setEmail("");
        setPhone("");
        setSourceNote("");
        setBasisRef("");
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Add contact" className="grid gap-4 sm:grid-cols-2">
      <label className="block">
        <span className={labelText}>Company</span>
        <select className={control} value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">Select a company…</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Name</span>
        <input className={control} value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Role (optional)</span>
        <input className={control} value={role} maxLength={200} onChange={(e) => setRole(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Business e-mail (optional)</span>
        <input type="email" className={control} value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Business phone (optional)</span>
        <input className={control} value={phone} maxLength={60} onChange={(e) => setPhone(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Source (required)</span>
        <select className={control} value={source} onChange={(e) => setSource(e.target.value as ContactSource | "")}>
          <option value="">Select a source…</option>
          {CONTACT_SOURCES.map((s) => (
            <option key={s} value={s}>
              {humanizeKey(s)}
            </option>
          ))}
        </select>
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Source note (optional)</span>
        <input className={control} value={sourceNote} maxLength={500} onChange={(e) => setSourceNote(e.target.value)} />
      </label>
      <label className="block">
        <span className={labelText}>Legal basis</span>
        <select className={control} value={basis} onChange={(e) => setBasis(e.target.value as LawfulBasis)}>
          {LAWFUL_BASES.map((b) => (
            <option key={b} value={b}>
              {humanizeKey(b)}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Legal basis reference (optional)</span>
        <input className={control} value={basisRef} maxLength={500} onChange={(e) => setBasisRef(e.target.value)} />
      </label>
      <div className="space-y-2 sm:col-span-2">
        <Feedback error={error} saved={saved} />
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Save contact"}
        </Button>
      </div>
    </form>
  );
}

export function EligibilityReviewForm({ contacts, onSaved }: { contacts: Contact[]; onSaved: () => void }) {
  const [contactId, setContactId] = useState("");
  const [channel, setChannel] = useState<Channel>("email");
  const [decision, setDecision] = useState<"allowed" | "not_allowed">("not_allowed");
  const [basis, setBasis] = useState<LawfulBasis>("none");
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    if (!contactId) return setError("Choose a contact.");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/contacts/{contact_id}/reviews", {
        params: { path: { contact_id: contactId } },
        body: { channel, decision, lawful_basis: basis, note: note.trim() || null },
      });
      if (!data) setError(errorMessage(apiError, "Could not record the review."));
      else {
        setSaved("Eligibility review recorded.");
        setNote("");
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Record eligibility review" className="grid gap-4 sm:grid-cols-2">
      <label className="block">
        <span className={labelText}>Contact</span>
        <select className={control} value={contactId} onChange={(e) => setContactId(e.target.value)}>
          <option value="">Select a contact…</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Channel</span>
        <select className={control} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {humanizeKey(c)}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Decision</span>
        <select className={control} value={decision} onChange={(e) => setDecision(e.target.value as "allowed" | "not_allowed")}>
          <option value="allowed">Allowed</option>
          <option value="not_allowed">Not allowed</option>
        </select>
      </label>
      <label className="block">
        <span className={labelText}>Legal basis</span>
        <select className={control} value={basis} onChange={(e) => setBasis(e.target.value as LawfulBasis)}>
          {LAWFUL_BASES.map((b) => (
            <option key={b} value={b}>
              {humanizeKey(b)}
            </option>
          ))}
        </select>
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Note (optional)</span>
        <input className={control} value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="space-y-2 sm:col-span-2">
        <Feedback error={error} saved={saved} />
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Record review"}
        </Button>
      </div>
    </form>
  );
}

export function OptOutForm({ onSaved }: { onSaved: () => void }) {
  const [channel, setChannel] = useState<"email" | "phone">("email");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(null);
    if (!value.trim()) return setError("Enter the e-mail address or phone number that opted out.");
    setPending(true);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/sales/suppressions", {
        body: { channel, value: value.trim(), reason: reason.trim() || null },
      });
      if (!data) setError(errorMessage(apiError, "Could not record the opt-out."));
      else {
        setSaved(data.created ? "Opt-out recorded." : (data.detail ?? "This opt-out was already recorded."));
        setValue("");
        setReason("");
        onSaved();
      }
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} aria-label="Record opt-out" className="grid gap-4 sm:grid-cols-2">
      <p className="text-sm text-slate-400 sm:col-span-2">
        Only a one-way hash of the address or number is stored, so it can be recognised later without keeping the value itself. Matching contacts become
        suppressed.
      </p>
      <label className="block">
        <span className={labelText}>Channel</span>
        <select className={control} value={channel} onChange={(e) => setChannel(e.target.value as "email" | "phone")}>
          <option value="email">E-mail</option>
          <option value="phone">Phone</option>
        </select>
      </label>
      <label className="block">
        <span className={labelText}>E-mail address or phone number</span>
        <input className={control} value={value} maxLength={320} autoComplete="off" onChange={(e) => setValue(e.target.value)} />
      </label>
      <label className="block sm:col-span-2">
        <span className={labelText}>Reason (optional)</span>
        <input className={control} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="space-y-2 sm:col-span-2">
        <Feedback error={error} saved={saved} />
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Record opt-out"}
        </Button>
      </div>
    </form>
  );
}
