import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { ACME_OWNER, GLOBEX_OWNER, signIn } from "./helpers";

/**
 * Sprint 2 acceptance: requires the stack to run with docker-compose.e2e.yml (offline fixture websites +
 * deterministic LLM test double), so results are reproducible without internet access or API keys.
 */
const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE_CSV = path.resolve(
  here,
  "../../api/src/aigentix/modules/lead_intelligence/fixtures/companies_sample.csv",
);

let companyPath = "";

async function orgHeader(page: Page): Promise<Record<string, string>> {
  const me = await (await page.request.get("/api/v1/me")).json();
  return { "X-Organization-Id": me.memberships[0].organization.id as string };
}

async function waitForRuns(request: APIRequestContext, headers: Record<string, string>, query: string) {
  await expect
    .poll(
      async () => {
        const runs = await (await request.get(`/api/v1/research-runs?${query}`, { headers })).json();
        return runs.items.length > 0 && runs.items.every((r: { status: string }) => !["pending", "running"].includes(r.status));
      },
      { timeout: 60_000, intervals: [500, 1000] },
    )
    .toBe(true);
}

test.describe.serial("Sprint 2 — Lead Intelligence", () => {
  test("add a company, research it, inspect evidence and review an opportunity", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Lead Intelligence" }).click();
    await expect(page).toHaveURL(/\/lead-intelligence$/);
    await expect(page.getByText("Total companies")).toBeVisible();

    await page.getByRole("navigation", { name: "Lead Intelligence sections" }).getByRole("link", { name: "Companies" }).click();
    await page.getByRole("link", { name: "Add companies" }).first().click();
    await expect(page.getByRole("heading", { name: "Add companies" })).toBeVisible();

    // Validation feedback, then a real submission.
    await page.getByLabel("Company website").fill("http://localhost:3000");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page.getByLabel("Company website")).toHaveAttribute("aria-invalid", "true");
    await expect(page).toHaveURL(/\/companies\/new/); // nothing was created
    await page.getByLabel("Company website").fill("https://www.northwind-logistics.example/");
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page).toHaveURL(/\/companies\/[0-9a-f-]{36}/);
    companyPath = new URL(page.url()).pathname;

    // Start research and monitor progress on the run page.
    await page.getByRole("button", { name: /Start research|Research again/ }).click();
    await page.getByRole("link", { name: "View research run" }).first().click();
    await expect(page).toHaveURL(/\/research-runs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("progressbar", { name: "Research progress" })).toBeVisible();
    await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("list", { name: "Research steps" })).toBeVisible();

    // Results on the company page.
    await page.getByRole("link", { name: "View company results" }).click();
    await expect(page.getByRole("heading", { name: "Company profile", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Northwind Logistics" }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
    await expect(page.getByText("E1", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(/offline test double \(fixture-rules-v1\)/)).toBeVisible();
    const sourceLink = page.locator('a[href*="northwind-logistics.example/"][target="_blank"]').first();
    await expect(sourceLink).toHaveAttribute("rel", /noopener/);

    // Review the first opportunity.
    await expect(page.getByRole("heading", { name: "AI opportunities", exact: true })).toBeVisible();
    const card = page.locator("article", { has: page.getByRole("button", { name: "Approve for investigation" }) }).first();
    await expect(card.getByText("Hypothesis")).toBeVisible();
    await card.getByRole("button", { name: "Mark for review" }).click();
    await expect(card.getByRole("status")).toContainText(/under.review/i);
    await card.getByRole("button", { name: "Approve for investigation" }).click();
    await expect(card.getByRole("status")).toContainText(/approved/i);
    await card.getByLabel("Reviewer note").fill("Validated in the E2E suite");
    await card.getByRole("button", { name: "Save note" }).click();
    await expect(card.getByRole("status")).toContainText("Note saved.");

    // It shows up in the review queue.
    await page.goto("/opportunities");
    await page.getByRole("tab", { name: "Approved" }).click();
    await expect(page.getByText("Validated in the E2E suite").first()).toBeVisible();
  });

  test("bulk import from CSV into a project and research the whole campaign", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    const headers = await orgHeader(page);
    const project = await (
      await page.request.post("/api/v1/projects", { data: { name: `Campaign ${Date.now()}` }, headers })
    ).json();

    await page.goto(`/companies/new?project=${project.id}`);
    await page.getByRole("tab", { name: "CSV import" }).click();
    await page.getByLabel("CSV file").setInputFiles(SAMPLE_CSV);
    await page.getByRole("button", { name: "Preview import" }).click();
    const preview = page.getByRole("table", { name: "Import preview rows" });
    await expect(preview).toBeVisible();
    await expect(preview.getByText("duplicate", { exact: false }).first()).toBeVisible();
    await expect(preview.getByText(/invalid/i).first()).toBeVisible();
    await page.getByRole("button", { name: "Import companies" }).click();
    await expect(page.getByText("Import complete")).toBeVisible();

    await page.goto(`/projects/${project.id}`);
    await expect(page.getByRole("heading", { name: "Companies in this project", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Research all companies" }).click();
    await expect(page.getByRole("status").filter({ hasText: /started|skipped|already/i }).first()).toBeVisible();

    await waitForRuns(page.request, headers, `project_id=${project.id}`);
    const runs = await (await page.request.get(`/api/v1/research-runs?project_id=${project.id}`, { headers })).json();
    expect(runs.items.length).toBeGreaterThanOrEqual(3);
    for (const run of runs.items) expect(["completed", "partial"]).toContain(run.status);

    await page.goto("/lead-intelligence");
    await expect(page.getByText("Companies researched")).toBeVisible();
  });

  test("another organization cannot see the researched company", async ({ page }) => {
    expect(companyPath).not.toBe("");
    await signIn(page, GLOBEX_OWNER);
    await page.goto("/companies");
    await expect(page.getByRole("heading", { name: "Companies", exact: true })).toBeVisible();
    await expect(page.getByText("northwind-logistics.example")).toHaveCount(0);
    await page.goto(companyPath);
    await expect(page.getByText(/not found/i).first()).toBeVisible();
    const headers = await orgHeader(page);
    const response = await page.request.get(`/api/v1${companyPath}/evidence`, { headers });
    expect(response.status()).toBe(404);
  });
});
