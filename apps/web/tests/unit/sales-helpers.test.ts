import { describe, expect, it } from "vitest";

import { existingOpportunityId } from "@/components/sales/convert-panel";
import {
  allowedNextStages,
  formatMoney,
  formatPerCurrency,
  formatRate,
  OPEN_STAGES,
  parseLines,
  pipelineNote,
  proposalActions,
  sectionStatusLabel,
  sectionText,
  taskQuery,
  taskTabLabel,
  TASK_VIEWS,
  toStatements,
} from "@/lib/sales";

describe("allowedNextStages", () => {
  it("mirrors the backend transition table", () => {
    expect(allowedNextStages("qualified")).toEqual(["researching", "contact_planned"]);
    expect(allowedNextStages("researching")).toEqual(["qualified", "contact_planned"]);
    expect(allowedNextStages("contact_planned")).toEqual(["researching", "in_conversation"]);
    expect(allowedNextStages("in_conversation")).toEqual(["contact_planned", "proposal_sent"]);
    expect(allowedNextStages("proposal_sent")).toEqual(["in_conversation"]);
  });

  it("never offers won/lost as a move and nothing for closed deals", () => {
    for (const s of OPEN_STAGES) {
      expect(allowedNextStages(s)).not.toContain("won");
      expect(allowedNextStages(s)).not.toContain("lost");
    }
    expect(allowedNextStages("won")).toEqual([]);
    expect(allowedNextStages("lost")).toEqual([]);
  });
});

describe("metrics formatting", () => {
  it("shows null rates as an em dash, never 0%", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(undefined)).toBe("—");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(0.375)).toBe("37.5%");
    expect(formatRate(1)).toBe("100%");
  });

  it("formats values per currency without summing across currencies", () => {
    expect(formatPerCurrency({ USD: "100.00", EUR: "12000.00" })).toEqual(["EUR 12,000", "USD 100"]);
    expect(formatPerCurrency({})).toEqual([]);
  });

  it("shows a missing deal value as No value", () => {
    expect(formatMoney(null, "EUR")).toBe("No value");
    expect(formatMoney("5000.00", "EUR")).toBe("EUR 5,000");
  });

  it("explains deals without value", () => {
    expect(pipelineNote({ open_without_value: 0 })).toBeNull();
    expect(pipelineNote({ open_without_value: 1 })).toBe("1 deal without value not included");
    expect(pipelineNote({ open_without_value: 3 })).toBe("3 deals without value not included");
  });
});

describe("follow-up tabs", () => {
  it("labels the dashboard tabs", () => {
    expect(TASK_VIEWS.map((t) => t.label)).toEqual(["Overdue", "Today", "Upcoming", "Completed", "Assigned to me"]);
    expect(taskTabLabel("mine")).toBe("Assigned to me");
  });

  it("maps tabs to API queries", () => {
    expect(taskQuery("overdue")).toEqual({ view: "overdue", mine: false });
    expect(taskQuery("completed")).toEqual({ view: "completed", mine: false });
    expect(taskQuery("mine")).toEqual({ view: "open", mine: true });
  });
});

describe("proposals", () => {
  it("labels section statuses", () => {
    expect(sectionStatusLabel("draft")).toBe("Draft");
    expect(sectionStatusLabel("needs_input")).toBe("Needs input");
  });

  it("only offers human status moves", () => {
    expect(proposalActions("draft")).toEqual(["ready"]);
    expect(proposalActions("ready")).toEqual(["draft", "sent"]);
    expect(proposalActions("sent")).toEqual(["accepted", "declined"]);
    expect(proposalActions("generating")).toEqual([]);
    expect(proposalActions("failed")).toEqual([]);
    expect(proposalActions("accepted")).toEqual([]);
  });
});

describe("brief content", () => {
  it("reads AI statements with evidence and basis, and human edits as plain text", () => {
    const ai = toStatements([{ text: "Uses a contact form", evidence: ["E1", 2], basis: "observed" }, { text: "  " }, "Plain edit"]);
    expect(ai).toEqual([
      { text: "Uses a contact form", evidence: ["E1"], basis: "observed" },
      { text: "Plain edit", evidence: [], basis: null },
    ]);
    expect(sectionText({ observed_situation: ai }, "observed_situation", "list")).toBe("Uses a contact form\nPlain edit");
    expect(sectionText({ company_summary: { text: "A summary", evidence: [], basis: "hypothesis" } }, "company_summary", "text")).toBe("A summary");
    expect(sectionText(null, "company_summary", "text")).toBe("");
  });

  it("splits list edits into non-empty lines", () => {
    expect(parseLines(" a \n\n b\n")).toEqual(["a", "b"]);
  });
});

describe("conversion conflicts", () => {
  it("extracts the existing opportunity id from a 409 error", () => {
    expect(existingOpportunityId({ error: { message: "exists", details: { existing_opportunity_id: "abc" } } })).toBe("abc");
    expect(existingOpportunityId({ error: { message: "nope" } })).toBeNull();
    expect(existingOpportunityId(undefined)).toBeNull();
  });
});
