/**
 * Playwright config — F265 local-only E2E harness.
 *
 * NOT wired into CI (deliberate — would burn GitHub Actions minutes).
 * Engineers run these on their laptop before pushing changes that
 * touch user-facing flows. See ``e2e/README.md`` for the prereq +
 * run instructions.
 *
 * Tests target a locally-running docker-compose stack:
 *   - Backend at http://localhost:8000
 *   - Frontend at http://localhost:3000
 *   - Postgres + Redis on the docker network
 *
 * The harness DOES NOT auto-start docker-compose because we want the
 * developer to have the service stack already up (and to see logs in
 * a separate terminal). If services aren't reachable, ``baseURL`` will
 * fail-fast on the first navigation rather than waste minutes booting.
 *
 * Browsers: Chromium + Firefox. We skip WebKit because most of our
 * users are on Chrome/Firefox; running 3 browsers triples test time
 * with little marginal coverage given our app uses no Safari-only APIs.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // F265 — we want failures to surface quickly so the developer can
  // fix-and-rerun without waiting on retries. CI usage would benefit
  // from retries; local-only doesn't.
  retries: 0,
  // Sequential execution — the seed fixture mutates DB state and we
  // don't want races. If we add isolation later (per-test schema,
  // transactional seed), this can go back to parallel.
  workers: 1,
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    // Default frontend URL. Override via PLAYWRIGHT_BASE_URL if you
    // run vite dev on a different port.
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000",
    // Trace + screenshot on failure for post-mortem debugging.
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Most assertions need a moment for TanStack Query refetches.
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
});
