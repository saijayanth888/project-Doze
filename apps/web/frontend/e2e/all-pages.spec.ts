import { test, expect, type ConsoleMessage } from "@playwright/test";

/**
 * Walk every sidebar entry, assert no console errors, no white screen,
 * and the root mounted. This is the safety net that catches pages
 * silently breaking after a refactor.
 *
 * The list below MUST stay in sync with apps/web/frontend/src/components/layout/Sidebar.jsx.
 */
const PAGES: Array<{ path: string; name: string }> = [
  { path: "/dashboard",  name: "Dashboard"  },
  { path: "/adapters",   name: "Adapters"   },
  { path: "/lineage",    name: "Lineage"    },
  { path: "/datasets",   name: "Datasets"   },
  { path: "/benchmarks", name: "Benchmarks" },
  { path: "/playground", name: "Playground" },
  { path: "/forge",      name: "ForgeAgent" },
  { path: "/ept",        name: "EPT"        },
  { path: "/campaign",   name: "Campaign"   },
  { path: "/automation", name: "Automation" },
  { path: "/history",    name: "History"    },
  { path: "/settings",   name: "Settings"   },
];

// Errors we tolerate — they're third-party / harmless or already known.
const IGNORED_PATTERNS: RegExp[] = [
  /Failed to load resource: the server responded with a status of 404/i, // 404 from optional endpoints
  /WebSocket.*close/i,                                                   // ws reconnect noise
  /ResizeObserver loop/i,                                                // recharts internals

  // Test-harness artefact: Playwright's extraHTTPHeaders applies X-API-Key to
  // ALL requests, including cross-origin Google Fonts fetches that don't
  // allow it in their CORS policy. Real users never trigger this — fonts
  // load via <link> and our apiFetch only attaches the key to /api/*.
  // The failed-CORS preflight surfaces TWO console messages: a long CORS
  // explainer (with the gstatic URL) and a generic "ERR_FAILED" for the
  // resource. Match both shapes.
  /fonts\.gstatic\.com.*Access-Control-Allow-Headers/i,
  /fonts\.gstatic\.com.*ERR_FAILED/i,
  /Failed to load resource.*fonts\.gstatic\.com/i,
  /Failed to load resource: net::ERR_FAILED/i,
];

function isIgnored(text: string): boolean {
  return IGNORED_PATTERNS.some((re) => re.test(text));
}

test.describe("All pages — smoke + console hygiene", () => {
  for (const { path, name } of PAGES) {
    test(`${name} (${path}) renders without console errors`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (msg: ConsoleMessage) => {
        if (msg.type() === "error" && !isIgnored(msg.text())) {
          errors.push(msg.text());
        }
      });
      page.on("pageerror", (err) => {
        if (!isIgnored(String(err))) errors.push(`pageerror: ${err.message}`);
      });

      await page.goto(path, { waitUntil: "domcontentloaded" });

      // Either a redirect to /dashboard for routes that need bootstrapping
      // or the route itself.
      await expect(page).toHaveURL(new RegExp(`(${path}|/dashboard)`), { timeout: 15_000 });

      // The React root must mount.
      await expect(page.locator("#root")).toBeVisible({ timeout: 15_000 });

      // Give async data fetches a tick to fail loudly.
      await page.waitForTimeout(800);

      expect(errors, `${name} produced console errors:\n${errors.join("\n")}`).toEqual([]);
    });
  }
});

test.describe("All pages — no fatal text", () => {
  for (const { path, name } of PAGES) {
    test(`${name} body has no "undefined"/"NaN"/"[object Object]"`, async ({ page }) => {
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1000);
      const text = await page.evaluate(() => document.body.innerText);
      // Soft check: these tokens are red flags but might appear in code blocks.
      // We exclude obvious benign occurrences (e.g. word "undefined" inside a
      // tooltip explainer). Anything that *renders* as a stray "undefined GB"
      // counts as a bug.
      const stray = [
        /\bundefined\s?GB\b/i,
        /\bNaN\s*%\b/i,
        /\[object Object\]/,
      ];
      for (const re of stray) {
        expect(text, `${name} has stray ${re.source}`).not.toMatch(re);
      }
    });
  }
});
