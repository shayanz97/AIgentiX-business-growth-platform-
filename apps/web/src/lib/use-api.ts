"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type Result<T> = { data: T | null; error: string | null; loading: boolean };

/**
 * Minimal loader for client pages: runs `load` on mount and when `deps` change, and exposes loading/error state.
 * `reload()` refetches silently (no loading flash) and keeps the previous data if the refetch fails.
 */
export function useApi<T>(load: () => Promise<{ data?: T; error?: unknown }>, deps: unknown[] = []): Result<T> & { reload: () => void } {
  const [state, setState] = useState<Result<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    load()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (data !== undefined) setState({ data, error: null, loading: false });
        else
          setState((prev) => ({
            data: prev.data,
            error: (error as { error?: { message?: string } })?.error?.message ?? "Request failed",
            loading: false,
          }));
      })
      .catch(() => !cancelled && setState((prev) => ({ data: prev.data, error: "Cannot reach the server", loading: false })));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- callers pass explicit deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

/** Calls `callback` every `intervalMs` while `active`; the timer is cleared on deactivation and unmount. */
export function usePolling(callback: () => void, active: boolean, intervalMs = 2000): void {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  });
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => saved.current(), intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs]);
}
