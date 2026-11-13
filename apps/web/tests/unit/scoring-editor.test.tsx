import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScoringProfileEditor } from "@/components/scoring/scoring-editor";
import type { Profile } from "@/lib/api";

const patch = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { PATCH: (...a: unknown[]) => patch(...a) } }));

const profile: Profile = {
  id: "p1",
  name: "Default",
  description: "",
  version: 1,
  is_default: true,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
  config: { weights: { opportunity: 35, fit: 25, triggers: 20, intent: 20 } },
};

describe("ScoringProfileEditor", () => {
  beforeEach(() => patch.mockReset());

  it("shows the live weight total and blocks saving unless it is 100", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ data: { ...profile, version: 2 } });
    render(<ScoringProfileEditor profile={profile} canEdit onSaved={() => {}} />);
    expect(screen.getByTestId("weights-sum")).toHaveTextContent("Total: 100 / 100");
    const intent = screen.getByLabelText("Intent weight");
    await user.clear(intent);
    await user.type(intent, "30");
    expect(screen.getByTestId("weights-sum")).toHaveTextContent("Total: 110 / 100");
    expect(screen.getByTestId("weights-sum")).toHaveTextContent("must add up to 100");
    expect(screen.getByRole("button", { name: "Save scoring profile" })).toBeDisabled();

    const opp = screen.getByLabelText("Opportunity weight");
    await user.clear(opp);
    await user.type(opp, "25");
    expect(screen.getByRole("button", { name: "Save scoring profile" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Save scoring profile" }));
    expect(patch).toHaveBeenCalledTimes(1);
    const body = patch.mock.calls[0]![1].body.config;
    expect(body.weights).toEqual({ opportunity: 25, fit: 25, triggers: 20, intent: 30 });
    expect(await screen.findByText(/Existing scores update when you re-score/)).toBeInTheDocument();
  });

  it("is read-only for non-owners", () => {
    render(<ScoringProfileEditor profile={profile} canEdit={false} onSaved={() => {}} />);
    expect(screen.getByLabelText("Intent weight")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save scoring profile" })).toBeNull();
  });

  it("shows API validation errors", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ error: { error: { message: "freshness bands must be increasing" } } });
    render(<ScoringProfileEditor profile={profile} canEdit onSaved={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Save scoring profile" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("freshness bands must be increasing");
  });
});
