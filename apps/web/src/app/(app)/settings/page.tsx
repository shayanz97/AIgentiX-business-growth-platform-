"use client";

import { OrganizationNameForm } from "@/components/forms/organization-form";
import { Badge, Card, PageHeader } from "@/components/ui/surface";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

export default function SettingsPage() {
  const { me, membership, refresh, selectOrganization } = useSession();

  return (
    <>
      <PageHeader title="Settings" description="Organization and account settings" />
      <div className="grid gap-6 lg:grid-cols-2">
        {membership ? (
          <Card>
            <h2 className="mb-1 font-medium text-slate-100">Organization</h2>
            <p className="mb-5 text-sm text-slate-400">
              Your role: <Badge tone={membership.role === "owner" ? "accent" : "neutral"}>{membership.role}</Badge>
            </p>
            {membership.role === "owner" ? (
              <OrganizationNameForm
                label="Organization name"
                submitLabel="Save name"
                defaultValue={membership.organization.name}
                onSubmit={async (name) => {
                  const { error, response } = await api.PATCH("/api/v1/organizations/{organization_id}", {
                    params: { path: { organization_id: membership.organization.id } },
                    body: { name },
                  });
                  if (response.ok) await refresh();
                  return { ok: response.ok, error };
                }}
              />
            ) : (
              <p className="text-sm text-slate-300">
                {membership.organization.name}
                <span className="mt-2 block text-xs text-slate-500">Only owners can change organization settings.</span>
              </p>
            )}
            <Members organizationId={membership.organization.id} />
          </Card>
        ) : null}

        <div className="space-y-6">
          <Card>
            <h2 className="mb-4 font-medium text-slate-100">Create an organization</h2>
            <OrganizationNameForm
              label="New organization name"
              submitLabel="Create organization"
              onSubmit={async (name) => {
                const { data, error, response } = await api.POST("/api/v1/organizations", { body: { name } });
                if (data) {
                  selectOrganization(data.organization.id);
                  await refresh();
                }
                return { ok: response.ok, error };
              }}
            />
          </Card>
          <Card>
            <h2 className="mb-2 font-medium text-slate-100">Account</h2>
            <p className="text-sm text-slate-300">{me.user.full_name || "—"}</p>
            <p className="text-sm text-slate-400">{me.user.email}</p>
          </Card>
        </div>
      </div>
    </>
  );
}

function Members({ organizationId }: { organizationId: string }) {
  const { data } = useApi(
    () => api.GET("/api/v1/organizations/{organization_id}/members", { params: { path: { organization_id: organizationId } } }),
    [organizationId],
  );
  if (!data) return null;
  return (
    <div className="mt-8">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Members</h3>
      <ul className="divide-y divide-line rounded-md border border-line">
        {data.map((m) => (
          <li key={m.user.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <span className="text-slate-200">{m.user.email}</span>
            <Badge>{m.role}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}
