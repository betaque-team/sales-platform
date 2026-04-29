/**
 * F265 — shared login helpers for the E2E suite.
 *
 * The platform uses a JWT cookie named ``session`` (per
 * backend/app/api/deps.py:19). Tests log in once and reuse the cookie
 * across navigations. The login flow is intentionally exercised end-
 * to-end here (rather than mock-injecting a cookie) because the
 * login page itself is a critical regression surface — F207 was a
 * mid-session 401 redirect bug.
 *
 * Default test credentials assume the prod-seed admin user exists:
 *   admin@jobplatform.io / admin123
 * If your local dev DB has a different password, set:
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD env vars.
 */
import { Page, expect } from "@playwright/test";

export const E2E_ADMIN_EMAIL =
  process.env.E2E_ADMIN_EMAIL || "admin@jobplatform.io";
export const E2E_ADMIN_PASSWORD =
  process.env.E2E_ADMIN_PASSWORD || "admin123";

/**
 * Log in via the actual ``/login`` form, then wait for the dashboard
 * route to render. Reusable across specs.
 *
 * Returns once the sidebar is visible — that's our signal that auth +
 * the first authenticated query (``/auth/me``) both succeeded.
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(E2E_ADMIN_EMAIL);
  await page.getByLabel(/password/i).fill(E2E_ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  // Wait for sidebar — the auth-protected layout renders it on every
  // page. Without this wait, navigating immediately after login can
  // race the auth-context bootstrap and 401-redirect us back.
  await expect(
    page.getByRole("link", { name: /dashboard/i })
  ).toBeVisible({ timeout: 15_000 });
}
