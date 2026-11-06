import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OpportunityCard } from "@/components/research/opportunity-card";
import type { Opportunity } from "@/lib/api";

const patch = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { PATCH: (...a: unknown[]) => patch(...a) } }));

const opportunity: Opportunity = {
  id: "o1",
  company_id: "c1",
  company_name: "Acme",
  research_run_id: "r1",
  title: "Automate quote requests",
  observed_context: "The site has a quote request form.",
  problem_hypothesis: "Staff may re-key quotes by hand.",
  proposed_ai_solution: "Extract fields from quote emails.",
  estimated_business_impact: "Faster replies.",
  implementation_complexity: "low",
  confidence: "medium",
  assumptions: ["Quotes arrive by e-mail"],
  validation_questions: ["How many quotes per week?"],
  next_step: "Interview the sales lead.",
  quality_flags: ["unsupported_claim"],
  status: "proposed",
  reviewer_note: null,
  reviewed_by_user_id: null,
  reviewed_at: null,
  evidence: [
    {
      id: "e1",
      label: "E1",
      evidence_type: "contact_form",
      observed_fact: "Quote form present",
      supporting_excerpt: "<b>Request a quote</b>",
      source_url: "https://acme.example/contact",
      basis: "observed",
      confidence: "high",
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("OpportunityCard", () => {
  beforeEach(() => patch.mockReset());

  it("renders model text as plain text with warnings and a safe source link", () => {
    render(<OpportunityCard opportunity={opportunity} showCompany />);
    expect(screen.getByText("Contains a claim not supported by the cited evidence — confidence lowered")).toBeInTheDocument();
    expect(screen.getByText("<b>Request a quote</b>")).toBeInTheDocument();
    expect(screen.getByText("Hypothesis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://acme.example/contact" })).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(screen.getByRole("link", { name: "Acme" })).toHaveAttribute("href", "/companies/c1");
  });

  it("changes status through PATCH and shows the updated badge", async () => {
    patch.mockResolvedValue({ data: { ...opportunity, status: "approved" } });
    const onUpdated = vi.fn();
    render(<OpportunityCard opportunity={opportunity} onUpdated={onUpdated} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve for investigation" }));
    expect(patch).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}", {
      params: { path: { opportunity_id: "o1" } },
      body: { status: "approved" },
    });
    expect(await screen.findByText("Status changed to approved.")).toBeInTheDocument();
    expect(onUpdated).toHaveBeenCalledWith(expect.objectContaining({ status: "approved" }));
    expect(screen.getByRole("button", { name: "Approve for investigation" })).toBeDisabled();
  });

  it("displays the API message for an invalid transition", async () => {
    patch.mockResolvedValue({ error: { error: { message: "Cannot move from rejected to approved" } } });
    render(<OpportunityCard opportunity={{ ...opportunity, status: "rejected" }} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve for investigation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot move from rejected to approved");
  });

  it("saves a reviewer note", async () => {
    patch.mockResolvedValue({ data: { ...opportunity, reviewer_note: "Looks promising" } });
    render(<OpportunityCard opportunity={opportunity} />);
    await userEvent.type(screen.getByLabelText("Reviewer note"), "Looks promising");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(patch).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}", {
      params: { path: { opportunity_id: "o1" } },
      body: { reviewer_note: "Looks promising" },
    });
    expect(await screen.findByText("Note saved.")).toBeInTheDocument();
  });
});
