"use client";

import Link from "next/link";

import { PermissionBadges, RestrictionBadge } from "@/components/sales/contact-badges";
import { CreateContactForm, EligibilityReviewForm, OptOutForm } from "@/components/sales/contact-forms";
import { RequireOrganization } from "@/components/require-organization";
import { Alert, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { humanizeKey } from "@/lib/sales";
import { useApi } from "@/lib/use-api";

export default function ContactsPage() {
  return (
    <>
      <PageHeader title="Contacts" description="People at your companies, where each contact came from and which channels a person has cleared." />
      <RequireOrganization>
        <Contacts />
      </RequireOrganization>
    </>
  );
}

function Contacts() {
  const contacts = useApi(() => api.GET("/api/v1/sales/contacts", { params: { query: {} } }), []);
  const companies = useApi(() => api.GET("/api/v1/companies", { params: { query: { limit: 100 } } }), []);
  const nameOfCompany = (id: string) => companies.data?.items.find((c) => c.id === id)?.name ?? "Company";
  const list = contacts.data ?? [];

  return (
    <div className="space-y-8">
      <Alert tone="info">
        AIgentiX never sends messages. A public business address alone does not permit advertising e-mails: record a source and an eligibility review before
        anyone contacts a person.
      </Alert>

      {contacts.error && !contacts.data ? <Alert>{contacts.error}</Alert> : null}
      {contacts.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {contacts.data && list.length === 0 ? <EmptyState title="No contacts yet">Add a contact below to record its source and channel permissions.</EmptyState> : null}
      {list.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Contacts">
          {list.map((c) => (
            <li key={c.id} className="space-y-2 px-4 py-3 text-sm" data-testid="contact-row">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-slate-100">
                  {c.name}
                  {c.role ? <span className="font-normal text-slate-400"> · {c.role}</span> : null}
                </p>
                <RestrictionBadge status={c.restriction_status} />
              </div>
              <p className="text-xs text-slate-400">
                <Link href={`/leads/${c.company_id}`} className="text-accent hover:underline">
                  {nameOfCompany(c.company_id)}
                </Link>
                {" · "}Source: {humanizeKey(c.source)}
                {" · "}Legal basis: {humanizeKey(c.lawful_basis)}
                {c.lawful_basis_reference ? ` (${c.lawful_basis_reference})` : ""}
              </p>
              <PermissionBadges permissions={c.permissions} />
            </li>
          ))}
        </ul>
      ) : null}

      <Card className="space-y-4">
        <h2 className="text-lg font-medium text-white">Add a contact</h2>
        <CreateContactForm companies={companies.data?.items ?? []} onSaved={contacts.reload} />
      </Card>
      <Card className="space-y-4">
        <h2 className="text-lg font-medium text-white">Record eligibility review</h2>
        <EligibilityReviewForm contacts={list} onSaved={contacts.reload} />
      </Card>
      <Card className="space-y-4">
        <h2 className="text-lg font-medium text-white">Record an opt-out</h2>
        <OptOutForm onSaved={contacts.reload} />
      </Card>
    </div>
  );
}
