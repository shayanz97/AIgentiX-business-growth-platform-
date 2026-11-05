"use client";

import type { ReactNode } from "react";

import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/surface";
import { useSession } from "@/lib/session";

/** Tenant-scoped pages render only once the user has an active organization. */
export function RequireOrganization({ children }: { children: ReactNode }) {
  const { membership } = useSession();
  if (!membership) {
    return (
      <EmptyState
        title="No organization yet"
        action={<ButtonLink href="/settings">Create an organization</ButtonLink>}
      >
        Research projects belong to an organization. Create one to get started.
      </EmptyState>
    );
  }
  return <>{children}</>;
}
