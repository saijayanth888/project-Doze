import { test, expect } from "@playwright/test";

test.describe("landing", () => {
  test("hero CTAs navigate to dashboard", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/ModelForge/i);
    await page.getByRole("navigation").getByRole("button", { name: "Dashboard →" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText(/EVOLUTION STATUS|Evolution Status/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("View Dashboard and anchor links", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /View Dashboard/i }).click();
    await expect(page).toHaveURL(/\/dashboard$/);

    await page.goto("/");
    await page.getByRole("link", { name: "How It Works" }).click();
    await expect(page.locator("#how-it-works")).toBeVisible();
  });
});

test.describe("app shell", () => {
  test("sidebar routes and back to home", async ({ page }) => {
    await page.goto("/dashboard");
    for (const label of ["Lineage Tree", "Benchmarks", "Playground", "Settings"]) {
      const navBtn = page.getByRole("button", { name: label, exact: true });
      await navBtn.click();
      await expect(navBtn).toBeVisible();
    }
    await page.getByRole("link", { name: /Back to home page/i }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("Start Evolution in sidebar goes to dashboard", async ({ page }) => {
    await page.goto("/benchmarks");
    await page.getByRole("button", { name: "Start Evolution" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("champion card routes", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "Run Inference" }).click();
    await expect(page).toHaveURL(/\/playground$/);
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "View Lineage" }).click();
    await expect(page).toHaveURL(/\/lineage$/);
  });

  test("View Logs scrolls to activity", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: "View Logs" }).click();
    await expect(page.locator("#activity-feed")).toBeVisible();
  });
});
