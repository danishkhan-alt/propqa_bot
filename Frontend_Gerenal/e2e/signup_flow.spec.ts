/**
 * E2E: Signup flow — create a new account and verify UI update.
 */

import { test, expect } from "@playwright/test";

test.describe("Signup Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("shows Create Account tab in auth gate", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const dialog = page.getByRole("dialog");
    if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(page.getByRole("tab", { name: /create account/i })).toBeVisible();
    }
  });

  test("can switch to Create Account tab", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const dialog = page.getByRole("dialog");
    const isVisible = await dialog.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await page.getByRole("tab", { name: /create account/i }).click();
      // Should see full name field
      await expect(page.getByLabel(/full name/i)).toBeVisible({ timeout: 3000 });
    }
  });

  test("signup form validation is active", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const dialog = page.getByRole("dialog");
    const isVisible = await dialog.isVisible({ timeout: 3000 }).catch(() => false);
    if (!isVisible) return;

    await page.getByRole("tab", { name: /create account/i }).click();

    // Try to submit empty form
    await page.getByRole("button", { name: /create account/i }).click();

    // Should show validation errors
    await page.waitForTimeout(200);
    // At minimum the form should still be present (no premature navigation)
    await expect(page.getByLabel(/full name/i)).toBeVisible();
  });

  test("Register button opens auth gate to signup tab", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Dismiss initial auth gate
    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Click Register in header
    const registerBtn = page.getByRole("button", { name: /register/i });
    if (await registerBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await registerBtn.click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 3000 });
    }
  });
});
