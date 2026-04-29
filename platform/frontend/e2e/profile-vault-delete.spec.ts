/**
 * F265 #4 — Profile vault hard-delete with typed-email confirmation.
 *
 * Catches: F260 #4 (Delete permanently button missing) and the gate
 * regression where typing a wrong email accidentally enables the
 * destructive action.
 *
 * The structural assertion: ``Delete permanently`` button is visible
 * to admin → opens a typed-email panel → button stays disabled until
 * the email is typed exactly → click triggers a DELETE request that
 * carries ``hard=true&confirm=<email>``.
 *
 * NOTE: This test does NOT actually delete a profile (would be
 * destructive against the local dev DB). It verifies the UI gate
 * behaviour up to but not including the click. A separate integration
 * test exercises the backend endpoint with a throwaway profile.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/auth";

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
});

test("admin sees Delete permanently button on profile detail page", async ({ page }) => {
  // Profiles list — pick the first row.
  await page.goto("/profiles");
  // If no profiles seeded, skip with a clear message rather than
  // silently passing. Local devs without seed data should know.
  const firstProfileLink = page.locator("a[href^='/profiles/']").first();
  const profileCount = await firstProfileLink.count();
  test.skip(
    profileCount === 0,
    "No profiles seeded — create one in the local dev DB to run this test"
  );
  await firstProfileLink.click();
  await expect(page).toHaveURL(/\/profiles\/[a-f0-9-]+/);

  // F260 #4: the Delete permanently button MUST be visible to admin.
  await expect(
    page.getByRole("button", { name: /delete permanently/i })
  ).toBeVisible();
});

test("typed-email gate blocks destructive action until exact match", async ({ page }) => {
  await page.goto("/profiles");
  const firstProfileLink = page.locator("a[href^='/profiles/']").first();
  const profileCount = await firstProfileLink.count();
  test.skip(profileCount === 0, "No profiles seeded — see prior test");
  await firstProfileLink.click();

  // Capture the displayed profile email — it's the source of truth
  // for what we have to type in the confirmation panel.
  const profileEmail = await page
    .locator('p:near(h1)')
    .first()
    .innerText()
    .catch(() => "");
  // If we can't find an email on the page, this is a rendering bug
  // separate from F265 — bail with a clear message.
  expect(profileEmail, "Could not read profile email from header").toMatch(/@/);

  await page.getByRole("button", { name: /delete permanently/i }).click();

  // Panel opens. Confirm button starts disabled.
  const confirmBtn = page.getByRole("button", { name: /confirm permanent delete/i });
  await expect(confirmBtn).toBeVisible();
  await expect(confirmBtn).toBeDisabled();

  // Type a wrong email — button stays disabled.
  const emailInput = page.locator('input[type="text"][placeholder*="@"]').last();
  await emailInput.fill("wrong-email@nope.invalid");
  await expect(confirmBtn).toBeDisabled();

  // Type the exact email (case-insensitive per the backend) — button
  // becomes enabled. This is the F260 #4 invariant.
  await emailInput.fill(profileEmail.trim());
  await expect(confirmBtn).toBeEnabled();

  // Cancel out — we don't actually delete in this test (destructive).
  await page.getByRole("button", { name: /^cancel$/i }).click();
  await expect(confirmBtn).not.toBeVisible();
});
