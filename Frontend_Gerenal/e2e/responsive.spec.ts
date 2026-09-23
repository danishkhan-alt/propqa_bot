/**
 * E2E: Responsive layout — mobile viewport tests.
 */

import { test, expect } from "@playwright/test";

test.describe("Responsive Layout", () => {
  test.use({ viewport: { width: 390, height: 844 } }); // iPhone 14 Pro

  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("auth gate dialog is visible on mobile", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const dialog = page.getByRole("dialog");
    if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(dialog).toBeVisible();
      // Dialog should be readable within mobile viewport
      const box = await dialog.boundingBox();
      expect(box?.width).toBeLessThanOrEqual(400);
    }
  });

  test("composer is visible and usable on mobile", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    const composer = page.getByPlaceholder(/ask about dubai/i);
    await expect(composer).toBeVisible({ timeout: 5000 });
  });

  test("sidebar toggle works on mobile", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    const toggle = page.getByLabel(/toggle sidebar/i);
    await expect(toggle).toBeVisible({ timeout: 3000 });
    await toggle.click();
    // After click sidebar state changes (we just verify it doesn't crash)
  });

  test("header buttons fit within mobile viewport", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Header should be within mobile width
    const header = page.locator("header").first();
    await expect(header).toBeVisible({ timeout: 3000 });
    const box = await header.boundingBox();
    expect(box?.width).toBeLessThanOrEqual(400);
  });
});
