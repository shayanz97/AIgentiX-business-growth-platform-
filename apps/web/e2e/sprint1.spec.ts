import { expect, test } from "@playwright/test";

import { ACME_OWNER, GLOBEX_OWNER, signIn } from "./helpers";

const projectName = `E2E project ${Date.now()}`;
let projectPath = "";
let acmeOrgId = "";

test.describe.serial("Sprint 1 acceptance", () => {
  test("protected routes redirect to login", async ({ page }) => {
    await page.goto("/projects");
    await expect(page).toHaveURL(/\/login\?next=%2Fprojects/);
  });

  test("invalid credentials are rejected", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("E-mail").fill(ACME_OWNER);
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByText("Invalid e-mail or password.")).toBeVisible();
  });

  test("owner signs in, navigates, creates a project, views it and signs out", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await expect(page.getByLabel("Active organization")).toHaveValue(/.+/);
    await expect(page.getByLabel("Active organization").locator("option:checked")).toHaveText("Acme Robotics");

    // Navigation: planned modules are visible but disabled.
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByText("Sales")).toHaveAttribute("aria-disabled", "true");
    await nav.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.getByText("member@acme.example")).toBeVisible();
    await nav.getByRole("link", { name: "Lead Intelligence" }).click();
    await page.getByRole("navigation", { name: "Lead Intelligence sections" }).getByRole("link", { name: "Projects" }).click();
    await expect(page.getByRole("heading", { name: "Research projects", exact: true })).toBeVisible();

    // Create a project.
    await page.getByRole("link", { name: "New project" }).click();
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page.getByText("Project name is required")).toBeVisible();
    await page.getByLabel("Project name").fill(projectName);
    await page.getByLabel("Company website").fill("https://acme.example");
    await page.getByLabel("Notes").fill("Created by the Playwright E2E suite");
    await page.getByRole("button", { name: "Create project" }).click();

    // Detail page.
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    await expect(page.getByText("https://acme.example/")).toBeVisible();
    projectPath = new URL(page.url()).pathname;
    acmeOrgId = (await (await page.request.get("/api/v1/me")).json()).memberships[0].organization.id;
    expect(projectPath).toMatch(/^\/projects\/[0-9a-f-]{36}$/);

    // List page shows it.
    await page.getByRole("link", { name: "All projects" }).click();
    await expect(page.getByRole("list", { name: "Research projects" }).getByText(projectName)).toBeVisible();

    // Persisted: visible after a full reload (fresh fetch from the API/database).
    await page.reload();
    await expect(page.getByText(projectName)).toBeVisible();

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("another tenant cannot see or open the project", async ({ page }) => {
    expect(projectPath).not.toBe("");
    await signIn(page, GLOBEX_OWNER);
    await expect(page.getByLabel("Active organization").locator("option:checked")).toHaveText("Globex Analytics");
    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "Research projects", exact: true })).toBeVisible();
    await expect(page.getByText(projectName)).toHaveCount(0);

    await page.goto(projectPath);
    await expect(page.getByRole("heading", { name: "Project not found" })).toBeVisible();

    // Spoofing Acme's organization id with Globex's session is rejected by the API.
    const spoofed = await page.request.get(`/api/v1${projectPath}`, { headers: { "X-Organization-Id": acmeOrgId } });
    expect(spoofed.status()).toBe(403);
    const spoofedList = await page.request.get("/api/v1/projects", { headers: { "X-Organization-Id": acmeOrgId } });
    expect(spoofedList.status()).toBe(403);
    const me = await (await page.request.get("/api/v1/me")).json();
    const globexId = me.memberships[0].organization.id as string;
    const own = await page.request.get(`/api/v1${projectPath}`, { headers: { "X-Organization-Id": globexId } });
    expect(own.status()).toBe(404);
  });

  test("member of the same organization sees the project", async ({ page }) => {
    await signIn(page, "member@acme.example");
    await page.goto("/projects");
    await expect(page.getByText(projectName)).toBeVisible();
  });
});
