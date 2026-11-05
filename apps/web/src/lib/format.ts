const formatter = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });

export function formatDate(iso: string): string {
  return `${formatter.format(new Date(iso))} UTC`;
}
