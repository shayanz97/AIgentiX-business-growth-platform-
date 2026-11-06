import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/components/forms/login-form";

const post = vi.fn();
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: { POST: (...a: unknown[]) => post(...a) } }));

describe("LoginForm", () => {
  beforeEach(() => post.mockReset());

  it("validates input before calling the API", async () => {
    render(<LoginForm onSuccess={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid e-mail address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
  });

  it("signs in and calls onSuccess", async () => {
    post.mockResolvedValue({ data: { id: "1" }, response: new Response(null, { status: 200 }) });
    const onSuccess = vi.fn();
    render(<LoginForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "ada@acme.example");
    await userEvent.type(screen.getByLabelText("Password"), "a-strong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(post).toHaveBeenCalledWith("/api/v1/auth/login", {
      body: { email: "ada@acme.example", password: "a-strong-password" },
    });
    expect(onSuccess).toHaveBeenCalledOnce();
  });

  it("shows a generic error for rejected credentials", async () => {
    post.mockResolvedValue({ error: { error: { message: "x" } }, response: new Response(null, { status: 401 }) });
    const onSuccess = vi.fn();
    render(<LoginForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText("E-mail"), "ada@acme.example");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid e-mail or password.");
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
