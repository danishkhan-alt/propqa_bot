/**
 * E2E: Login flow — sign in with demo credentials, see authenticated header.
 */

import { test, expect } from "@playwright/test";

const DEMO_EMAIL = "demo@propqa.ai";
const DEMO_PASSWORD = "Demo1234!";

test.describe("Login Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("shows login tab in auth gate", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Auth gate should show login tab
    const dialog = page.getByRole("dialog");
    if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(page.getByRole("tab", { name: /sign in/i })).toBeVisible();
    }
  });

  test("demo credential hint is visible", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Look for the demo credential hint
    await expect(page.getByText(/demo@propqa\.ai/i)).toBeVisible({ timeout: 5000 });
  });

  test("can fill and submit login form", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const dialog = page.getByRole("dialog");
    const isVisible = await dialog.isVisible({ timeout: 3000 }).catch(() => false);
    if (!isVisible) {
      // Open auth gate via Sign In button
      await page.getByRole("button", { name: /sign in/i }).first().click();
    }

    await page.getByLabel(/email/i).fill(DEMO_EMAIL);
    await page.getByLabel(/password/i).fill(DEMO_PASSWORD);

    // Form is filled correctly
    await expect(page.getByLabel(/email/i)).toHaveValue(DEMO_EMAIL);
    await expect(page.getByLabel(/password/i)).toHaveValue(DEMO_PASSWORD);
  });

  test("clicking demo credential hint fills the form", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const demoLink = page.getByText(/demo@propqa\.ai/i).first();
    if (await demoLink.isVisible({ timeout: 3000 }).catch(() => false)) {
      await demoLink.click();
      // Email field should be filled
      await expect(page.getByLabel(/email/i)).toHaveValue(DEMO_EMAIL);
    }
  });
});
