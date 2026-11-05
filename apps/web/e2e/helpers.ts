import { expect, type Page } from "@playwright/test";

export const PASSWORD = process.env.E2E_PASSWORD ?? "";
export const ACME_OWNER = "owner@acme.example";
export const GLOBEX_OWNER = "owner@globex.example";

export async function signIn(page: Page, email: string) {
  if (!PASSWORD) throw new Error("Set E2E_PASSWORD to the password used for `seed-dev`");
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}
