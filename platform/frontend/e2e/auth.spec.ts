/**
 * F265 #1 — Auth flow + 401 redirect.
 *
 * Catches: F207-class regressions where a mid-session 401 (cookie
 * expired, server-side invalidation) used to surface as "Job not
 * found" because TanStack Query collapsed the 401 into a generic
 * error. Post-fix the api.ts helper detects 401 and hard-redirects
 * to /login?next=<previous_path> for clean re-auth.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/auth";

test("admin can log in and reach the dashboard", async ({ page }) => {
  await loginAsAdmin(page);
  // Dashboard is the default landing route for authenticated users.
  await expect(page).toHaveURL(/\/$|\/dashboard/);
  // Sidebar exists for auth'd users only.
  await expect(page.getByRole("link", { name: /dashboard/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /relevant jobs/i })).toBeVisible();
});

test("expired session redirects to /login with next= param", async ({ page, context }) => {
  await loginAsAdmin(page);
  // Visit a protected page first so we have a known ``next`` target.
  await page.goto("/jobs?role_cluster=relevant");
  await expect(page).toHaveURL(/\/jobs/);

  // Simulate session expiry by clearing the auth cookie.
  await context.clearCookies();

  // Trigger any authenticated query — TanStack Query refetches on
  // window focus, so a manual navigation does the trick.
  await page.goto("/jobs?role_cluster=relevant");

  // F207: api.ts redirects to /login?next=<encoded_path>. Verify both
  // the destination AND the next param so a regression to "redirect
  // but lose context" is caught.
  await expect(page).toHaveURL(/\/login\?next=/);
  const url = page.url();
  expect(decodeURIComponent(url)).toContain("/jobs?role_cluster=relevant");
});
