import { test, expect } from "@playwright/test";

test("landing page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/ModelForge/i);
  await expect(page.locator("#root")).toBeVisible();
});

test("n8n health (optional, full stack)", async ({ request }) => {
  test.skip(
    process.env.N8N_E2E !== "1",
    "Set N8N_E2E=1 and N8N_URL if n8n is running (e.g. after make db-only).",
  );
  const base = (process.env.N8N_URL || "http://127.0.0.1:5679").replace(/\/$/, "");
  const res = await request.get(`${base}/healthz`);
  expect(res.ok()).toBeTruthy();
});
