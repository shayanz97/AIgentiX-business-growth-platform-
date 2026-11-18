"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/surface";
import { api, errorMessage } from "@/lib/api";
import { downloadText } from "@/lib/sales";

export function ExportCsvButton({ entity, filename }: { entity: "opportunities" | "activities" | "tasks"; filename: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const { data: csv, error: apiError } = await api.GET("/api/v1/sales/export", { params: { query: { entity } }, parseAs: "text" });
      if (typeof csv !== "string") setError(errorMessage(apiError, "Could not export."));
      else downloadText(csv, filename, "text/csv;charset=utf-8");
    } catch {
      setError("Cannot reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="secondary" onClick={() => void run()} disabled={busy}>
        {busy ? "Exporting…" : "Export CSV"}
      </Button>
      {error ? <Alert>{error}</Alert> : null}
    </>
  );
}
