import { test, expect } from "@playwright/test";

test("landing page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/ModelForge/i);
  await expect(page.locator("#root")).toBeVisible();
});

test("n8n health (full stack)", async ({ request }) => {
  const base = (process.env.N8N_URL || "http://127.0.0.1:5679").replace(/\/$/, "");
  const res = await request.get(`${base}/healthz`);
  expect(res.ok()).toBeTruthy();
});
