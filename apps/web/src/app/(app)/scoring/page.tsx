"use client";

import { useState } from "react";

import { IcpProfileEditor } from "@/components/scoring/icp-editor";
import { ScoringProfileEditor } from "@/components/scoring/scoring-editor";
import { RequireOrganization } from "@/components/require-organization";
import { Button } from "@/components/ui/button";
import { Alert, Badge, Card, EmptyState, PageHeader } from "@/components/ui/surface";
import { api, errorMessage, type Profile } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

export default function ScoringPage() {
  return (
    <>
      <PageHeader
        title="Scoring configuration"
        description="Scoring profiles set how leads are weighted; ICP profiles describe your ideal customer. Changes create a new version and apply when leads are re-scored."
      />
      <RequireOrganization>
        <Configuration />
      </RequireOrganization>
    </>
  );
}

function Configuration() {
  const { membership } = useSession();
  const canEdit = membership?.role === "owner";
  const scoring = useApi(() => api.GET("/api/v1/scoring-profiles"), []);
  const icp = useApi(() => api.GET("/api/v1/icp-profiles"), []);
  return (
    <div className="space-y-10">
      {!canEdit ? <Alert tone="info">Only organization owners can change profiles. You can view them here.</Alert> : null}
      <ProfileSection
        kind="scoring"
        title="Scoring profiles"
        profiles={scoring.data}
        error={scoring.data ? null : scoring.error}
        loading={scoring.loading}
        canEdit={canEdit}
        reload={scoring.reload}
      />
      <ProfileSection
        kind="icp"
        title="ICP profiles"
        profiles={icp.data}
        error={icp.data ? null : icp.error}
        loading={icp.loading}
        canEdit={canEdit}
        reload={icp.reload}
      />
    </div>
  );
}

function ProfileSection({
  kind,
  title,
  profiles,
  error,
  loading,
  canEdit,
  reload,
}: {
  kind: "scoring" | "icp";
  title: string;
  profiles: Profile[] | null;
  error: string | null;
  loading: boolean;
  canEdit: boolean;
  reload: () => void;
}) {
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const path = kind === "scoring" ? "/api/v1/scoring-profiles" : "/api/v1/icp-profiles";
  const itemPath = kind === "scoring" ? "/api/v1/scoring-profiles/{profile_id}" : "/api/v1/icp-profiles/{profile_id}";

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setPending(true);
    setActionError(null);
    try {
      const { data, error: apiError } = await api.POST(path, { body: { name: name.trim() } });
      if (!data) setActionError(errorMessage(apiError, "Could not create the profile."));
      else {
        setName("");
        setOpenId(data.id);
        reload();
      }
    } catch {
      setActionError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  async function makeDefault(id: string) {
    setPending(true);
    setActionError(null);
    try {
      const { data, error: apiError } = await api.PATCH(itemPath, { params: { path: { profile_id: id } }, body: { is_default: true } });
      if (!data) setActionError(errorMessage(apiError, "Could not change the default profile."));
      else reload();
    } catch {
      setActionError("Cannot reach the server. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const headingId = `${kind}-profiles`;
  return (
    <section aria-labelledby={headingId} className="space-y-4">
      <h2 id={headingId} className="text-lg font-medium text-white">
        {title}
      </h2>
      {error ? <Alert>{error}</Alert> : null}
      {loading ? <p className="text-sm text-slate-400">Loading…</p> : null}
      {profiles && profiles.length === 0 ? <EmptyState title="No profiles">Profiles are created with sensible defaults the first time you open this page.</EmptyState> : null}
      {actionError ? <Alert>{actionError}</Alert> : null}
      {profiles?.map((p) => (
        <Card key={p.id} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="font-medium text-slate-100">
                {p.name} <span className="text-sm font-normal text-slate-400">version {p.version}</span>
              </h3>
              {p.description ? <p className="mt-1 text-sm text-slate-400">{p.description}</p> : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {p.is_default ? <Badge tone="accent">Default</Badge> : null}
              {canEdit && !p.is_default ? (
                <Button variant="secondary" disabled={pending} onClick={() => void makeDefault(p.id)} aria-label={`Make ${p.name} the default ${kind} profile`}>
                  Make default
                </Button>
              ) : null}
              <Button variant="ghost" aria-expanded={openId === p.id} onClick={() => setOpenId(openId === p.id ? null : p.id)}>
                {openId === p.id ? "Hide" : canEdit ? "Edit" : "View"}
              </Button>
            </div>
          </div>
          {openId === p.id ? (
            kind === "scoring" ? (
              <ScoringProfileEditor key={p.id} profile={p} canEdit={canEdit} onSaved={reload} />
            ) : (
              <IcpProfileEditor key={p.id} profile={p} canEdit={canEdit} onSaved={reload} />
            )
          ) : null}
        </Card>
      ))}
      {canEdit ? (
        <form onSubmit={(e) => void create(e)} className="flex flex-wrap items-end gap-3" aria-label={`Create ${kind} profile`}>
          <label className="block text-sm font-medium text-slate-200">
            <span className="mb-1.5 block">New {kind === "scoring" ? "scoring" : "ICP"} profile name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              className="block w-64 rounded-md border border-line bg-navy-900 px-3 py-2 text-sm text-slate-100 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
            />
          </label>
          <Button type="submit" variant="secondary" disabled={pending || !name.trim()}>
            Create profile
          </Button>
        </form>
      ) : null}
    </section>
  );
}
