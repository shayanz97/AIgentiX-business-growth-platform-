"use client";

import { useEffect, useState } from "react";

type Result<T> = { data: T | null; error: string | null; loading: boolean };

/** Minimal loader for client pages: runs `load` once on mount and exposes loading/error state. */
export function useApi<T>(load: () => Promise<{ data?: T; error?: unknown }>, deps: unknown[] = []): Result<T> {
  const [state, setState] = useState<Result<T>>({ data: null, error: null, loading: true });
  useEffect(() => {
    let cancelled = false;
    load()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (data !== undefined) setState({ data, error: null, loading: false });
        else setState({ data: null, error: (error as { error?: { message?: string } })?.error?.message ?? "Request failed", loading: false });
      })
      .catch(() => !cancelled && setState({ data: null, error: "Cannot reach the server", loading: false }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass explicit deps
  }, deps);
  return state;
}
