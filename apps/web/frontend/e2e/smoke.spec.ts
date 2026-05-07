import { test, expect } from "@playwright/test";

test("landing page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/ModelForge/i);
  await expect(page.locator("#root")).toBeVisible();
});

// n8n was removed in favour of the in-process AutomationEngine
// (services/automation_engine). Its health-check test was deleted.
