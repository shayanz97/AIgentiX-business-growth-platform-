"use client";

import { useState } from "react";

import { OfferingForm } from "@/components/sales/offering-form";
import { RequireOrganization } from "@/components/require-organization";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, type Offering } from "@/lib/api";
import { formatMoney } from "@/lib/sales";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

export default function ServicesPage() {
  return (
    <>
      <PageHeader
        title="Services"
        description="The offerings proposals may refer to. Proposals only quote prices that an owner has approved here."
      />
      <RequireOrganization>
        <Services />
      </RequireOrganization>
    </>
  );
}

function priceText(o: Offering): string {
  if (o.price_amount === null) return "No price";
  return `${formatMoney(o.price_amount, o.currency)}${o.price_unit ? ` ${o.price_unit}` : ""}`;
}

function Services() {
  const { membership } = useSession();
  const isOwner = membership?.role === "owner";
  const list = useApi(() => api.GET("/api/v1/sales/services", { params: { query: {} } }), []);
  const [editing, setEditing] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      {!isOwner ? <Alert tone="info">Only organization owners can create or edit services.</Alert> : null}
      {list.error && !list.data ? <Alert>{list.error}</Alert> : null}
      {list.loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {list.data && list.data.length === 0 ? <EmptyState title="No services yet">Without approved services, proposals leave prices as placeholders.</EmptyState> : null}
      {list.data && list.data.length > 0 ? (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-navy-900/70" aria-label="Service offerings">
          {list.data.map((o) => (
            <li key={o.id} className="space-y-3 px-4 py-3 text-sm" data-testid="service-row">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium text-slate-100">{o.name}</p>
                  {o.solution_category ? <p className="text-xs text-slate-400">{o.solution_category}</p> : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-200">{priceText(o)}</span>
                  <Badge tone={o.price_approved ? "accent" : "muted"}>{o.price_approved ? "Price approved" : "Price not approved"}</Badge>
                  {!o.active ? <Badge tone="warning">Inactive</Badge> : null}
                  {isOwner ? (
                    <Button variant="secondary" aria-label={`Edit ${o.name}`} onClick={() => setEditing(editing === o.id ? null : o.id)}>
                      Edit
                    </Button>
                  ) : null}
                </div>
              </div>
              {o.description ? <p className="whitespace-pre-wrap text-slate-300">{o.description}</p> : null}
              {isOwner && editing === o.id ? (
                <OfferingForm
                  offering={o}
                  onSaved={() => {
                    list.reload();
                    setEditing(null);
                  }}
                  onCancel={() => setEditing(null)}
                />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {isOwner ? (
        <Card className="space-y-4">
          <h2 className="text-lg font-medium text-white">Add a service</h2>
          <OfferingForm onSaved={list.reload} />
        </Card>
      ) : null}
    </div>
  );
}
