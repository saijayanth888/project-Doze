import { defineConfig, devices } from "@playwright/test";

// `localhost` avoids 127.0.0.1 vs IPv6-only listen quirks. CI uses a free preview port
// so a dev server on :3000 does not block the health check.
const ciPreviewPort = process.env.PLAYWRIGHT_PREVIEW_PORT || "4173";
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ||
  (process.env.CI ? `http://localhost:${ciPreviewPort}` : "http://localhost:3000");

/** When set (e.g. Docker UI on :3001), do not spawn Vite — test against the running server. */
const externalBase = !!process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "line" : "html",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: externalBase
    ? undefined
    : {
        // CI builds first, then serves dist (avoids flaky esbuild subprocess in some runners).
        command: process.env.CI
          ? `npx vite preview --port ${ciPreviewPort} --strictPort`
          : "npm run dev",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
