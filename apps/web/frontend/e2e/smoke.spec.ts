import { test, expect } from "@playwright/test";

test("landing page loads", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/ModelForge/i);
  await expect(page.locator("#root")).toBeVisible();
});

test("n8n health (full stack)", async ({ request }) => {
  const base = (process.env.N8N_URL || "http://127.0.0.1:5679").replace(/\/$/, "");
  const inCi = !!process.env.CI;
  let res;
  try {
    res = await request.get(`${base}/healthz`, { timeout: 15_000 });
  } catch {
    test.skip(
      inCi,
      `n8n not reachable at ${base} (GitHub Actions does not start n8n by default)`,
    );
    throw new Error(
      `n8n not reachable at ${base}. Start the stack (e.g. docker compose up n8n) or set N8N_URL.`,
    );
  }
  expect(res.ok()).toBeTruthy();
});
