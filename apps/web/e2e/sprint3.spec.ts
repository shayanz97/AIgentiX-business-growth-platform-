import { expect, test, type Page } from "@playwright/test";

import { ACME_OWNER, signIn } from "./helpers";

/**
 * Sprint 3 acceptance: enrich -> ranked list -> detail -> review -> profile change -> re-score -> export.
 * Requires the stack to run with docker-compose.e2e.yml (fixture websites, fixture tender source, deterministic
 * LLM double and a fixed SCORING_REFERENCE_DATE), so results are reproducible without internet access.
 */
const DOMAIN = "kundenservice-anfrage.example";
const GENEROUS = 90_000;

async function orgHeader(page: Page): Promise<Record<string, string>> {
  const me = await (await page.request.get("/api/v1/me")).json();
  return { "X-Organization-Id": me.memberships[0].organization.id as string };
}

test.describe.serial("Sprint 3 — Growth intelligence & lead scoring", () => {
  let companyId = "";

  test("enrich a company and find it in the ranked leads with explicit intent", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    const headers = await orgHeader(page);

    await page.goto("/companies/new");
    await page.getByLabel("Company website").fill(`https://${DOMAIN}/`);
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page).toHaveURL(/\/companies\/[0-9a-f-]{36}/);
    companyId = new URL(page.url()).pathname.split("/").pop() ?? "";

    // Research first (Sprint 2 pipeline), then enrichment.
    await page.getByRole("button", { name: /Start research|Research again/ }).click();
    await expect
      .poll(
        async () => {
          const company = await (await page.request.get(`/api/v1/companies/${companyId}`, { headers })).json();
          return company.research_status;
        },
        { timeout: GENEROUS, intervals: [1000, 2000] },
      )
      .toMatch(/completed|partial/);

    await page.reload();
    const panel = page.locator("section", { has: page.getByRole("heading", { name: "Enrichment & score" }) });
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: "Enrich (re-crawl)" }).click();
    await expect(panel.getByRole("link", { name: "View enrichment run" }).first()).toBeVisible();

    await expect
      .poll(
        async () => {
          const signals = await (await page.request.get(`/api/v1/companies/${companyId}/signals`, { headers })).json();
          return signals.enrichment_run?.status ?? "none";
        },
        { timeout: GENEROUS, intervals: [1000, 2000] },
      )
      .toMatch(/completed|partial/);

    await page.goto("/leads");
    await expect(page.getByRole("heading", { name: "Ranked leads", exact: true })).toBeVisible();
    const row = page.getByTestId("lead-row").filter({ hasText: DOMAIN });
    await expect(row).toBeVisible({ timeout: 30_000 });
    await expect(row.getByText("Intent: Explicit")).toBeVisible();
    await expect(row.getByText(/coverage \d+%/)).toBeVisible();
  });

  test("inspect the breakdown and timeline, then review the lead", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto("/leads");
    await page.getByTestId("lead-row").filter({ hasText: DOMAIN }).getByRole("link").first().click();
    await expect(page).toHaveURL(new RegExp(`/leads/${companyId}$`));

    await expect(page.getByRole("heading", { name: "Score breakdown", exact: true })).toBeVisible();
    for (const key of ["opportunity", "fit", "triggers", "intent"]) await expect(page.getByTestId(`component-${key}`)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Trigger timeline", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Buying intent", exact: true })).toBeVisible();

    await page.getByLabel("Review status").selectOption("qualified_for_review");
    await page.getByLabel("Note (optional)").fill("Checked in the E2E suite");
    await page.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("Review saved.")).toBeVisible();
    await expect(page.getByRole("list", { name: "Review history" })).toContainText("Qualified for review");
  });

  test("change the scoring weights, re-score and export", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto("/scoring");
    const scoring = page.getByRole("region", { name: "Scoring profiles" });
    await scoring.getByRole("button", { name: "Edit" }).first().click();
    await scoring.getByLabel("Opportunity weight").fill("25");
    await scoring.getByLabel("Intent weight").fill("30");
    await expect(scoring.getByTestId("weights-sum")).toContainText("Total: 100 / 100");
    await scoring.getByRole("button", { name: "Save scoring profile" }).click();
    await expect(scoring.getByText(/Saved as a new version/)).toBeVisible();

    await page.goto(`/leads/${companyId}`);
    await page.getByRole("button", { name: "Re-score" }).click();
    await expect(page.getByText(/Re-scored 1 company/)).toBeVisible();
    // Initial snapshot (enrichment) + the re-score with the new profile version; re-scoring reloads the history.
    await expect(page.getByTestId("history-entry")).toHaveCount(2, { timeout: 30_000 });
    await page.reload();
    await expect(page.getByTestId("history-entry")).toHaveCount(2, { timeout: 30_000 });

    await page.goto("/leads");
    await expect(page.getByTestId("lead-row").filter({ hasText: DOMAIN })).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const csv = Buffer.concat(chunks).toString("utf8");
    expect(csv).toContain(DOMAIN);
  });
});
