import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunDetailView } from "@/components/research/run-detail-view";
import type { ResearchRun } from "@/lib/api";

const run: ResearchRun = {
  id: "r1",
  company_id: "c1",
  company_name: "Acme",
  project_id: null,
  status: "running",
  current_step: "extract_information",
  progress: 45,
  steps: [
    { name: "validate_input", state: "done", duration_ms: 12 },
    { name: "fetch_website", state: "done", duration_ms: 1840 },
    { name: "discover_relevant_pages", state: "done", duration_ms: 90 },
    { name: "extract_information", state: "current", duration_ms: null },
    { name: "save_evidence", state: "pending", duration_ms: null },
    { name: "ai_opportunity_audit", state: "skipped", duration_ms: null },
    { name: "persist_results", state: "pending", duration_ms: null },
  ],
  attempts: 1,
  max_attempts: 3,
  next_attempt_at: null,
  error_type: null,
  error_message: null,
  ai_status: "pending",
  audit_summary: null,
  pages_fetched: 4,
  input_tokens: 0,
  output_tokens: 0,
  estimated_cost_usd: 0,
  models_used: [],
  prompt_versions: {},
  cancel_requested: false,
  created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z",
  completed_at: null,
};

describe("RunDetailView", () => {
  it("renders progress, steps and attempts", () => {
    render(<RunDetailView run={run} />);
    const bar = screen.getByRole("progressbar", { name: "Research progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "45");
    const steps = within(screen.getByRole("list", { name: "Research steps" })).getAllByRole("listitem");
    expect(steps).toHaveLength(7);
    expect(steps[1]).toHaveTextContent("Fetch website");
    expect(steps[1]).toHaveTextContent("1.8 s");
    expect(steps[3]).toHaveAttribute("data-state", "current");
    expect(screen.getByText("Attempt 1 of 3")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("shows tokens and cost as not available without AI usage", () => {
    render(<RunDetailView run={run} />);
    expect(screen.getAllByText("Not available")).toHaveLength(2);
  });

  it("formats cost with four decimals and lists models", () => {
    render(
      <RunDetailView
        run={{
          ...run,
          status: "completed",
          progress: 100,
          ai_status: "completed",
          input_tokens: 1200,
          output_tokens: 300,
          estimated_cost_usd: 0.0123,
          models_used: ["model-a"],
          prompt_versions: { audit: "v2" },
          audit_summary: "Two opportunities found.",
        }}
      />,
    );
    expect(screen.getByText("$0.0123")).toBeInTheDocument();
    expect(screen.getByText("1200 / 300")).toBeInTheDocument();
    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.getByText("audit: v2")).toBeInTheDocument();
    expect(screen.getByText("Two opportunities found.")).toBeInTheDocument();
  });

  it("shows the error and next retry for a pending run that failed an attempt", () => {
    render(
      <RunDetailView
        run={{ ...run, status: "pending", error_type: "FetchError", error_message: "Timed out", next_attempt_at: "2026-01-01T00:05:00Z", attempts: 2 }}
      />,
    );
    expect(screen.getByText(/Next retry at/)).toBeInTheDocument();
    expect(screen.getByText(/Timed out/)).toBeInTheDocument();
    expect(screen.getByText(/FetchError/)).toBeInTheDocument();
  });
});
