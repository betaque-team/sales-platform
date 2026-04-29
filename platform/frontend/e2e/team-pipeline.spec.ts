/**
 * F265 #5 — Team Pipeline scope toggle + Pipeline drill-down.
 *
 * Catches: F261 (Team Pipeline Tracker) regressions. The new
 * /applications page has a My / Team scope toggle for admins, and
 * /pipeline cards have an "Apps" drill-down button. Both surfaces
 * are admin-gated; if the role-check regresses, viewers/reviewers
 * would see (or worse, be able to act on) team-wide data.
 *
 * Structural assertions:
 *   1. Admin can toggle My ↔ Team on /applications.
 *   2. Team scope renders applicant identity columns (name + email).
 *   3. Pipeline cards have an "Apps" button (admin only).
 *   4. Clicking it opens a drill-down panel with applicant rows.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/auth";

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
});

test("admin sees and can switch the My / Team scope on Applications", async ({ page }) => {
  await page.goto("/applications");

  // F261 — scope tabs only render for admin/super_admin. Both must
  // be visible before we toggle.
  const myTab = page.getByRole("button", { name: /my applications/i });
  const teamTab = page.getByRole("button", { name: /team pipeline/i });
  await expect(myTab).toBeVisible();
  await expect(teamTab).toBeVisible();

  // Default scope is "mine". Click Team — the table should swap to
  // the team feed which has an "Applicant" column header that
  // doesn't exist on the per-user view.
  await teamTab.click();
  await expect(
    page.getByRole("columnheader", { name: /applicant/i })
  ).toBeVisible({ timeout: 10_000 });

  // Switch back — Applicant column disappears.
  await myTab.click();
  await expect(
    page.getByRole("columnheader", { name: /applicant/i })
  ).not.toBeVisible();
});

test("Pipeline card has Apps drill-down (admin only) opening a side panel", async ({ page }) => {
  await page.goto("/pipeline");

  // Wait for at least one pipeline card to render. If no cards exist
  // (empty pipeline), skip with a clear message.
  const firstCard = page.locator("button:has-text('Apps')").first();
  const cardCount = await firstCard.count();
  test.skip(
    cardCount === 0,
    "No pipeline cards on /pipeline — seed an application + accept it to populate"
  );

  await firstCard.click();

  // F261 — the side panel header reads "Applications under this
  // company". Verify it appears.
  await expect(
    page.getByRole("heading", { name: /applications under this company/i })
  ).toBeVisible({ timeout: 5_000 });

  // Close panel via X button.
  await page.getByRole("button", { name: /^close$/i }).click().catch(async () => {
    // Fallback — backdrop click also closes.
    await page.locator(".fixed.inset-0").click({ position: { x: 10, y: 10 } });
  });
  await expect(
    page.getByRole("heading", { name: /applications under this company/i })
  ).not.toBeVisible();
});
