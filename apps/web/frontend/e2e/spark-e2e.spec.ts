import { test, expect } from "@playwright/test";

const SPARK_IP = process.env.SPARK_IP || process.env.LAN_IP || "192.168.1.49";
const API_KEY = process.env.MODELFORGE_API_KEY || "";
/** Same origin as the SPA (nginx → `/api` → FastAPI). Prefer PLAYWRIGHT_BASE_URL over API_URL from `.env` (often :8000). */
const API_BASE =
  process.env.PLAYWRIGHT_BASE_URL ||
  process.env.API_URL ||
  `http://${SPARK_IP}:3001`;
const N8N_BASE = process.env.N8N_URL || `http://${SPARK_IP}:5679`;

const apiHeaders = API_KEY ? { "X-API-Key": API_KEY } : {};

test.describe("API endpoints", () => {
  test("system health returns ok or degraded", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/system/health`, {
      headers: apiHeaders,
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(["ok", "degraded"]).toContain(body.status);
    expect(body.postgres).toBeDefined();
    expect(body.redis).toBeDefined();
    expect(body.ollama).toBeDefined();
  });

  test("GPU status responds", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/system/gpu`, {
      headers: apiHeaders,
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(typeof body.gpu_available).toBe("boolean");
  });

  test("champion endpoint responds (200 or 404 if none)", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/models/champion`, {
      headers: apiHeaders,
    });
    expect([200, 404]).toContain(res.status());
  });

  test("lineage tree responds", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/lineage/tree`, {
      headers: apiHeaders,
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.nodes)).toBeTruthy();
  });

  test("eval scores responds", async ({ request }) => {
    const res = await request.get(`${API_BASE}/api/eval/scores`, {
      headers: apiHeaders,
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trends).toBeDefined();
  });

  test("inference via Ollama works", async ({ request }) => {
    test.skip(!API_KEY, "MODELFORGE_API_KEY required for authenticated infer");
    // Trailing slash avoids a 307 to a Location that must preserve Host:port (see infra/nginx.conf).
    const res = await request.post(`${API_BASE}/api/infer/`, {
      headers: { ...apiHeaders, "Content-Type": "application/json" },
      data: { prompt: "Say hello in exactly 3 words", max_tokens: 20 },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.response).toBeTruthy();
  });
});

test.describe("Frontend pages", () => {
  test("landing page loads", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
  });

  test("dashboard page loads with key panels", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator("text=Dashboard").first()).toBeVisible();
    await expect(page.locator("text=Evolution").first()).toBeVisible({ timeout: 15_000 });
  });

  test("lineage page loads", async ({ page }) => {
    await page.goto("/lineage");
    await expect(page.locator("body")).toBeVisible();
  });

  test("benchmarks page loads", async ({ page }) => {
    await page.goto("/benchmarks");
    await expect(page.locator("body")).toBeVisible();
  });

  test("playground page loads and has input", async ({ page }) => {
    await page.goto("/playground");
    const input = page.locator("textarea").first();
    await expect(input).toBeVisible({ timeout: 15_000 });
  });

  test("settings page loads and shows API section", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator("text=API").first()).toBeVisible({ timeout: 15_000 });
  });

  test("navigation between main pages works", async ({ page }) => {
    await page.goto("/dashboard");
    for (const name of [/Lineage Tree/i, /Benchmarks/i, /Playground/i, /Settings/i]) {
      await page.getByRole("button", { name }).first().click();
      await page.waitForTimeout(400);
    }
    await page.getByRole("button", { name: /Dashboard/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard/);
  });
});

test.describe("n8n workflows", () => {
  test("n8n healthz responds when reachable", async ({ request }) => {
    const res = await request.get(`${N8N_BASE}/healthz`);
    if (!res.ok()) {
      test.skip(true, `n8n not reachable at ${N8N_BASE}`);
    }
    expect(res.status()).toBe(200);
  });
});

test.describe("Evolution run", () => {
  test("can start an evolution run", async ({ request }) => {
    test.skip(!API_KEY, "MODELFORGE_API_KEY required");
    const res = await request.post(`${API_BASE}/api/evolve/start`, {
      headers: { ...apiHeaders, "Content-Type": "application/json" },
      data: {
        base_model: "llama3.2:3b",
        max_generations: 1,
      },
    });
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.run_id).toBeTruthy();
    expect(body.status).toMatch(/starting|running/);
  });

  test("can poll evolution status", async ({ request }) => {
    test.skip(!API_KEY, "MODELFORGE_API_KEY required");
    const res = await request.get(`${API_BASE}/api/evolve/status`, {
      headers: apiHeaders,
    });
    expect(res.status()).toBe(200);
  });
});
