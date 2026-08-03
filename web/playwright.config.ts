import { defineConfig } from "@playwright/test";

/**
 * E2E tests run against the live FastAPI server, which serves the built
 * bundle at /app/ and the REST API at /api (same origin, so no CORS/auth
 * juggling — loopback requests skip the token per the trusted-CIDR rule).
 *
 * Rebuild the bundle (`npm run build`) before running so /app/ reflects
 * your changes. Override the target with AIMUSIC_BASE if needed.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.AIMUSIC_BASE || "http://127.0.0.1:7860",
    viewport: { width: 390, height: 844 }, // iPhone-ish; the app is a phone webview
    // The app registers a service worker that reloads the page on
    // controllerchange (PWA auto-update). In tests that reload resets the SPA
    // mid-flow; block the SW so navigation state is deterministic.
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
