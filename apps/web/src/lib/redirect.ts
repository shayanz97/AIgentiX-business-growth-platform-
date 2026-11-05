/**
 * Resolve a post-login `next` parameter to a same-origin path. Anything that would leave the origin
 * (absolute URLs, `//host`, `/\host`, control characters, ...) falls back to the dashboard.
 */
export function safeNextPath(value: string | null, origin: string, fallback = "/dashboard"): string {
  if (!value || !value.startsWith("/") || /[\\\u0000-\u001f\u007f]/.test(value)) return fallback;
  try {
    const url = new URL(value, origin);
    return url.origin === origin ? `${url.pathname}${url.search}${url.hash}` : fallback;
  } catch {
    return fallback;
  }
}
