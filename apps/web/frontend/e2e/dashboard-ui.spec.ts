/**
 * Dashboard interaction smoke tests against a running Spark/LAN UI.
 *
 * Run from repo root (loads .env):
 *   set -a && . ./.env && set +a && cd apps/web/frontend && \
 *   PLAYWRIGHT_BASE_URL=http://192.168.1.49:3001 \
 *   MODELFORGE_API_KEY="$MODELFORGE_API_KEY" \
 *   npx playwright test e2e/dashboard-ui.spec.ts --reporter=list
 *
 * If clicks "do nothing", ensure MODELFORGE_API_KEY matches the API
 * (or VITE_MODELFORGE_API_KEY was baked into the frontend image).
 *
 * The "Start Evolution" modal must be in a build that uses a body portal
 * (see EvolutionStatus + createPortal). Rebuild the Spark frontend if the
 * modal test fails against `http://IP:3001` with "intercepts pointer events".
 */

import { test, expect } from "@playwright/test";

const API_KEY = process.env.MODELFORGE_API_KEY || "";

test.describe.configure({ timeout: 45_000 });

test.beforeEach(async ({ page }) => {
  if (API_KEY) {
    await page.addInitScript((k: string) => {
      try {
        localStorage.setItem("modelforge_api_key", k);
      } catch {
        /* ignore */
      }
    }, API_KEY);
  }
});

test.describe("Dashboard UI interactions", () => {
  test("dashboard loads without blank screen", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
    await expect(page.locator("body")).toBeVisible();
    await expect(page.getByText(/Evolution Status/i).first()).toBeVisible({
      timeout: 20_000,
    });
    expect(errors, `JS errors: ${errors.join("; ")}`).toHaveLength(0);
  });

  test("Start Evolution opens modal and Cancel closes it", async ({
    page,
  }) => {
    // Avoid networkidle — dashboard polls /api and may never go “idle”.
    await page.goto("/dashboard", { waitUntil: "domcontentloaded" });

    // Prefer test id (new builds); fallback for Spark UI not rebuilt yet.
    const evolutionCard = page
      .getByTestId("evolution-status-panel")
      .or(page.locator(".mf-card-hover").filter({ hasText: /Evolution Status/i }).first());
    await expect(evolutionCard).toBeVisible({ timeout: 20_000 });
    const openBtn = evolutionCard.getByRole("button", {
      name: /^Start Evolution$/i,
    });
    await openBtn.click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    await expect(dialog.getByRole("button", { name: /^Cancel$/i })).toBeVisible();

    await dialog.getByRole("button", { name: /^Cancel$/i }).click();
    await expect(dialog).toBeHidden({ timeout: 10_000 });
  });

  test("sidebar navigates to Settings and back", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: /^Settings$/i }).first().click();
    await expect(page).toHaveURL(/\/settings/, { timeout: 15_000 });
    await expect(page.getByText(/API Configuration/i).first()).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole("button", { name: /^Dashboard$/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
  });

  test("View Logs scrolls to activity feed section", async ({ page }) => {
    await page.goto("/dashboard");
    const logsBtn = page.getByRole("button", { name: /View Logs/i }).first();
    await expect(logsBtn).toBeVisible({ timeout: 15_000 });
    await logsBtn.click();
    const feed = page.locator("#activity-feed");
    await expect(feed).toBeVisible({ timeout: 10_000 });
  });
});
