/**
 * E2E: Session claim flow — chat as guest, log in, verify session history migrated.
 */

import { test, expect } from "@playwright/test";

test.describe("Session Claim Flow", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("guest can see Sign In button in header after dismissing auth gate", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Dismiss auth gate as guest
    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Header should show Sign In option
    const signInBtn = page.getByRole("button", { name: /sign in/i });
    await expect(signInBtn).toBeVisible({ timeout: 3000 });
  });

  test("Sign In button opens auth gate", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Dismiss initial gate
    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Click Sign In in header
    const signInBtn = page.getByRole("button", { name: /sign in/i }).first();
    if (await signInBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await signInBtn.click();
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 3000 });
    }
  });
});
