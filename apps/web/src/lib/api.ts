import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "@contracts/schema";

export type Schemas = components["schemas"];
export type Project = Schemas["ProjectRead"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type Membership = Schemas["MembershipRead"];
export type Me = Schemas["MeResponse"];
export type ModuleInfo = Schemas["ModuleRead"];
export type Member = Schemas["MemberRead"];
export type WorkflowRun = Schemas["WorkflowRunRead"];

export const ORG_HEADER = "X-Organization-Id";
const ORG_STORAGE_KEY = "aigx.activeOrganization";

/** The active organization is a client preference only; the API verifies membership on every request. */
export const activeOrganization = {
  get(): string | null {
    try {
      return window.localStorage.getItem(ORG_STORAGE_KEY);
    } catch {
      return null;
    }
  },
  set(id: string | null): void {
    try {
      if (id) window.localStorage.setItem(ORG_STORAGE_KEY, id);
      else window.localStorage.removeItem(ORG_STORAGE_KEY);
    } catch {
      /* storage unavailable: selection lasts for this page only */
    }
  },
};

const orgHeader: Middleware = {
  onRequest({ request }) {
    const org = activeOrganization.get();
    if (org && !request.headers.has(ORG_HEADER)) request.headers.set(ORG_HEADER, org);
    return request;
  },
};

/** Typed client generated from the backend OpenAPI contract. Same-origin; Next.js proxies /api/v1. */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(orgHeader);

type ErrorPayload = { error?: { message?: string; details?: unknown } } | undefined;

export function errorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
  const message = (error as ErrorPayload)?.error?.message;
  return typeof message === "string" && message.length > 0 ? message : fallback;
}
