const formatter = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(4)}`;
}

export function formatDate(iso: string): string {
  return `${formatter.format(new Date(iso))} UTC`;
}
