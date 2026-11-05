import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectForm } from "@/components/forms/project-form";

const post = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { POST: (...a: unknown[]) => post(...a) } }));

describe("ProjectForm", () => {
  beforeEach(() => post.mockReset());

  it("requires a name and a valid URL", async () => {
    render(<ProjectForm onCreated={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Company website"), "javascript:alert(1)");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByText("Project name is required")).toBeInTheDocument();
    expect(screen.getByText("Enter a full URL starting with https://")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("creates a project with trimmed values", async () => {
    const created = { id: "p1", name: "Acme" };
    post.mockResolvedValue({ data: created });
    const onCreated = vi.fn();
    render(<ProjectForm onCreated={onCreated} />);
    await userEvent.type(screen.getByLabelText("Project name"), "  Acme  ");
    await userEvent.type(screen.getByLabelText("Company website"), "https://acme.example");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(post).toHaveBeenCalledWith("/api/v1/projects", {
      body: { name: "Acme", description: "", target_url: "https://acme.example" },
    });
    expect(onCreated).toHaveBeenCalledWith(created);
  });

  it("surfaces API errors", async () => {
    post.mockResolvedValue({ error: { error: { message: "You are not a member of this organization" } } });
    render(<ProjectForm onCreated={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Project name"), "Acme");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You are not a member of this organization");
  });
});
