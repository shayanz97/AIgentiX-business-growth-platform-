"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { activeOrganization, api, type Me, type Membership } from "@/lib/api";

type SessionState = {
  me: Me;
  membership: Membership | null;
  selectOrganization: (id: string) => void;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

function pickMembership(me: Me, preferred: string | null): Membership | null {
  return me.memberships.find((m) => m.organization.id === preferred) ?? me.memberships[0] ?? null;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async () => {
    const { data, response } = await api.GET("/api/v1/me");
    if (response.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
      return;
    }
    if (!data) {
      setFailed(true);
      return;
    }
    const chosen = pickMembership(data, activeOrganization.get());
    activeOrganization.set(chosen?.organization.id ?? null);
    setOrgId(chosen?.organization.id ?? null);
    setMe(data);
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial session load from the API
    void refresh();
  }, [refresh]);

  const selectOrganization = useCallback((id: string) => {
    activeOrganization.set(id);
    setOrgId(id);
  }, []);

  const signOut = useCallback(async () => {
    await api.POST("/api/v1/auth/logout");
    activeOrganization.set(null);
    router.replace("/login");
    router.refresh();
  }, [router]);

  const value = useMemo<SessionState | null>(() => {
    if (!me) return null;
    const membership = me.memberships.find((m) => m.organization.id === orgId) ?? null;
    return { me, membership, selectOrganization, refresh, signOut };
  }, [me, orgId, selectOrganization, refresh, signOut]);

  if (failed) {
    return (
      <div role="alert" className="p-8 text-sm text-red-300">
        The API is unavailable. Check that the backend is running and reload the page.
      </div>
    );
  }
  if (!value) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-400" aria-busy="true">
        Loading workspace…
      </div>
    );
  }
  // Re-mount tenant-scoped pages when the organization changes so no stale tenant data is shown.
  return (
    <SessionContext.Provider value={value}>
      <div key={orgId ?? "none"} className="contents">
        {children}
      </div>
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
