"use client";

import { api, type Member } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useApi } from "@/lib/use-api";

/** Members of the active organization (for assignee / owner pickers). */
export function useMembers(): { members: Member[]; nameOf: (userId: string | null | undefined) => string } {
  const { membership } = useSession();
  const orgId = membership?.organization.id ?? "";
  const { data } = useApi(
    () => (orgId ? api.GET("/api/v1/organizations/{organization_id}/members", { params: { path: { organization_id: orgId } } }) : Promise.resolve({ data: [] as Member[] })),
    [orgId],
  );
  const members = data ?? [];
  const nameOf = (userId: string | null | undefined) => {
    if (!userId) return "Unassigned";
    const m = members.find((x) => x.user.id === userId);
    return m ? m.user.full_name || m.user.email : "Unknown member";
  };
  return { members, nameOf };
}
