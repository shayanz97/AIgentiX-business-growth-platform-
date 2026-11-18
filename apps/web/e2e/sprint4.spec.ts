import { expect, test, type Page } from "@playwright/test";

import { ACME_OWNER, GLOBEX_OWNER, signIn } from "./helpers";

/**
 * Sprint 4 acceptance: lead -> convert -> pipeline -> activity -> brief -> proposal -> follow-up -> won -> export,
 * plus a tenant-isolation check. Requires the stack to run with docker-compose.e2e.yml (fixture websites,
 * LLM_PROVIDER=fixture, RESEARCH_TENDER_SOURCE=fixtures, SCORING_REFERENCE_DATE=2026-11-12) on a fresh database.
 */
const DOMAIN = "kundenservice-anfrage.example";
const GENEROUS = 90_000;
const TASK_TITLE = "Call back about the inquiry";

async function orgHeader(page: Page): Promise<Record<string, string>> {
  const me = await (await page.request.get("/api/v1/me")).json();
  return { "X-Organization-Id": me.memberships[0].organization.id as string };
}

function localInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

test.describe.serial("Sprint 4 — Sales pipeline, briefs, proposals and follow-ups", () => {
  let companyId = "";
  let dealId = "";
  let dealTitle = "";

  test("research and enrich a company, qualify it and convert it to an opportunity", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    const headers = await orgHeader(page);

    await page.goto("/companies/new");
    await page.getByLabel("Company website").fill(`https://${DOMAIN}/`);
    await page.getByRole("button", { name: "Add company" }).click();
    await expect(page).toHaveURL(/\/companies\/[0-9a-f-]{36}/);
    companyId = new URL(page.url()).pathname.split("/").pop() ?? "";

    await page.getByRole("button", { name: /Start research|Research again/ }).click();
    await expect
      .poll(async () => (await (await page.request.get(`/api/v1/companies/${companyId}`, { headers })).json()).research_status, {
        timeout: GENEROUS,
        intervals: [1000, 2000],
      })
      .toMatch(/completed|partial/);

    await page.reload();
    const panel = page.locator("section", { has: page.getByRole("heading", { name: "Enrichment & score" }) });
    await panel.getByRole("button", { name: "Enrich (re-crawl)" }).click();
    await expect
      .poll(async () => (await (await page.request.get(`/api/v1/companies/${companyId}/signals`, { headers })).json()).enrichment_run?.status ?? "none", {
        timeout: GENEROUS,
        intervals: [1000, 2000],
      })
      .toMatch(/completed|partial/);

    await page.goto(`/leads/${companyId}`);
    await expect(page.getByRole("heading", { name: "Score breakdown", exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Convert to sales opportunity" })).toHaveCount(0);

    await page.getByLabel("Review status").selectOption("qualified_for_review");
    await page.getByRole("button", { name: "Save review" }).click();
    await expect(page.getByText("Review saved.")).toBeVisible();

    await page.getByRole("button", { name: "Convert to sales opportunity" }).click();
    await page.getByRole("form", { name: "Convert to sales opportunity" }).getByRole("button", { name: "Convert", exact: true }).click();
    await expect(page).toHaveURL(/\/sales\/opportunities\/[0-9a-f-]{36}$/);
    dealId = new URL(page.url()).pathname.split("/").pop() ?? "";
    dealTitle = ((await page.getByRole("heading", { level: 1 }).textContent()) ?? "").trim();
    expect(dealTitle).not.toBe("");
    await expect(page.getByTestId("deal-header")).toContainText("Qualified");
    await expect(page.getByText(/not a purchase probability/)).toBeVisible();
  });

  test("the pipeline shows the card in Qualified and moves it to Contact planned", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto("/sales/pipeline");
    const qualified = page.getByRole("region", { name: "Qualified column" });
    const card = qualified.getByTestId("deal-card").filter({ hasText: dealTitle });
    await expect(card).toBeVisible();
    await card.getByLabel(/^Move .* to…/).selectOption("contact_planned");
    const planned = page.getByRole("region", { name: "Contact planned column" });
    await expect(planned.getByTestId("deal-card").filter({ hasText: dealTitle })).toBeVisible();
  });

  test("record a call and move the deal to In conversation", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);

    // The gate is enforced by the API: no recorded contact, no conversation stage.
    await page.getByLabel(/^Move .* to…/).selectOption("in_conversation");
    await expect(page.getByRole("alert").filter({ hasText: /contact|call|meeting|e-mail/i }).first()).toBeVisible();

    const form = page.getByRole("form", { name: "Record activity" });
    await form.getByLabel("Type").selectOption("call");
    await form.getByLabel("Description").fill("Intro call with the head of customer service");
    await form.getByRole("button", { name: "Record activity" }).click();
    await expect(page.getByRole("list", { name: "Activity timeline" })).toContainText("Intro call with the head of customer service");

    await page.getByLabel(/^Move .* to…/).selectOption("in_conversation");
    await expect(page.getByTestId("deal-header")).toContainText("In conversation");
  });

  test("generate and approve a sales brief", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);
    await page.getByRole("button", { name: "Generate brief" }).click();
    const brief = page.getByTestId("brief");
    await expect(brief.getByTestId("brief-model")).toContainText("fixture-sales-v1", { timeout: GENEROUS });
    await expect(brief).toContainText("Draft");
    await expect(brief).toContainText(/Observed|Hypothesis/);
    await brief.getByRole("button", { name: "Approve brief" }).click();
    await expect(brief).toContainText("Approved");
  });

  test("generate a proposal, edit a section, mark it as sent and move the deal to Proposal sent", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);
    await page.getByRole("button", { name: "Generate proposal" }).click();
    const row = page.getByTestId("proposal-row").first();
    await expect(row.getByTestId("proposal-editor")).toBeVisible({ timeout: GENEROUS });
    await expect(row.getByTestId("proposal-revision")).toHaveText("Revision 1");

    await row.getByTestId("section-executive_summary").getByRole("textbox").fill("Edited summary written by a person.");
    await row.getByLabel("Revision note (optional)").fill("E2E edit");
    await row.getByRole("button", { name: "Save revision" }).click();
    await expect(row.getByTestId("proposal-revision")).toHaveText("Revision 2");

    await row.getByRole("button", { name: "Mark as ready" }).click();
    await expect(row.getByTestId("proposal-editor")).toContainText("Ready");
    await row.getByRole("button", { name: /Mark as sent/ }).click();
    await row.getByLabel("I sent this outside AIgentiX").check();
    await row.getByRole("button", { name: "Confirm: mark as sent" }).click();
    await expect(row.getByTestId("proposal-editor")).toContainText("Sent", { timeout: 15_000 });

    await page.getByLabel(/^Move .* to…/).selectOption("proposal_sent");
    await expect(page.getByTestId("deal-header")).toContainText("Proposal sent");
  });

  test("an overdue follow-up shows on the dashboard until it is completed", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);
    const form = page.getByRole("form", { name: "Create follow-up task" });
    await form.getByLabel("Task").fill(TASK_TITLE);
    await form.getByLabel("Due").fill(localInput(new Date(Date.now() - 2 * 24 * 3600 * 1000)));
    await form.getByRole("button", { name: "Create task", exact: true }).click();
    await expect(page.getByRole("list", { name: "Opportunity tasks" })).toContainText(TASK_TITLE);

    await page.goto("/sales/tasks");
    await page.getByRole("tab", { name: /Overdue/ }).click();
    const task = page.getByTestId("task-row").filter({ hasText: TASK_TITLE });
    await expect(task).toBeVisible();
    await task.getByRole("button", { name: `Complete ${TASK_TITLE}` }).click();
    await expect(page.getByTestId("task-row").filter({ hasText: TASK_TITLE })).toHaveCount(0);
  });

  test("close the deal as won, see it on the overview and export it", async ({ page }) => {
    await signIn(page, ACME_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);
    await page.getByRole("button", { name: /^Close / }).click();
    const form = page.getByRole("form", { name: "Close opportunity" });
    await form.getByLabel("Outcome").selectOption("won");
    await form.getByLabel(/Won value/).fill("5000");
    await form.getByRole("button", { name: "Confirm close" }).click();
    await expect(page.getByTestId("deal-header")).toContainText("Won");
    await expect(page.getByTestId("deal-header")).toContainText("5,000");

    await page.goto("/sales");
    await expect(page.locator("dt", { hasText: /^Won$/ }).locator("xpath=following-sibling::dd")).toHaveText("1");
    await expect(page.getByText("No external CRM connected.")).toBeVisible();

    await page.goto("/sales/pipeline");
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    expect(Buffer.concat(chunks).toString("utf8")).toContain(dealTitle);
  });

  test("another organization cannot open the opportunity", async ({ page }) => {
    await signIn(page, GLOBEX_OWNER);
    await page.goto(`/sales/opportunities/${dealId}`);
    await expect(page.getByRole("heading", { name: "Opportunity not found" })).toBeVisible();
    await page.goto("/sales/pipeline");
    await expect(page.getByTestId("deal-card").filter({ hasText: dealTitle })).toHaveCount(0);
  });
});
