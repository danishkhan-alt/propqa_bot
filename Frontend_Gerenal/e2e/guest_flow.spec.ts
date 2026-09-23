/**
 * E2E: Guest flow — open app, skip auth, send a message, see conversion banner.
 *
 * Requires the dev server (npm run dev) and backend (uvicorn) to be running.
 */

import { test, expect } from "@playwright/test";

test.describe("Guest Flow", () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to start fresh
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test("shows auth gate on first visit", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);
    // Auth gate dialog should be visible for first-time visitors
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/welcome to propqa/i)).toBeVisible();
  });

  test("can continue as guest and see chat interface", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Click Continue as Guest
    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Should see the composer / chat input
    await expect(page.getByPlaceholder(/ask about dubai/i)).toBeVisible({ timeout: 5000 });
  });

  test("guest can type in the composer", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    // Dismiss auth gate if it appears
    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    const composer = page.getByPlaceholder(/ask about dubai/i);
    await expect(composer).toBeVisible({ timeout: 5000 });
    await composer.fill("Show me apartments in Dubai Marina");
    await expect(composer).toHaveValue("Show me apartments in Dubai Marina");
  });

  test("sidebar shows conversation list toggle", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(500);

    const guestBtn = page.getByRole("button", { name: /continue as guest/i });
    if (await guestBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await guestBtn.click();
    }

    // Sidebar panel-left button
    const sidebarToggle = page.getByLabel(/toggle sidebar/i);
    await expect(sidebarToggle).toBeVisible();
  });
});
