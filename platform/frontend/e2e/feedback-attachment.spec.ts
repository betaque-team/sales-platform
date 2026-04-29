/**
 * F265 #3 — Feedback attachment failure surfaces in UI.
 *
 * Catches: F260 #1 (feedback attachments silently fail). Pre-fix the
 * create flow caught upload errors with a bare ``catch {}`` and
 * dropped them, so users saw the ticket appear with no attachment +
 * no explanation. Post-fix an amber error banner lists per-file
 * failure reasons and pendingFiles is preserved for retry.
 *
 * The structural assertion: when an upload should fail (file > 10MB,
 * wrong MIME, etc.), the user sees an amber banner mentioning the
 * file name, NOT a silent success state.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/auth";

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
  await page.goto("/feedback");
});

test("ticket submits cleanly with no attachments", async ({ page }) => {
  // Baseline happy path — ensure we haven't broken the no-attachment
  // case while fixing the with-attachment case.
  const stamp = Date.now();
  await page.getByLabel(/title/i).fill(`E2E test no-attach ${stamp}`);
  await page
    .getByLabel(/description/i)
    .fill("E2E baseline — no attachment, should submit cleanly.");
  await page.getByRole("combobox", { name: /category/i }).selectOption("question");
  await page.getByRole("button", { name: /submit/i }).click();

  // Success: form clears (title field empty) AND no amber error
  // banner appears.
  await expect(page.getByLabel(/title/i)).toHaveValue("", { timeout: 10_000 });
  await expect(page.getByText(/attachment.* failed/i)).not.toBeVisible();
});

test("oversized attachment surfaces an amber error (does NOT silent-succeed)", async ({ page }, testInfo) => {
  // Build an 11 MB blob and post it as an attachment. The backend
  // 10 MB cap should reject it.
  const oversized = Buffer.alloc(11 * 1024 * 1024, 0x42);

  const stamp = Date.now();
  await page.getByLabel(/title/i).fill(`E2E test oversized ${stamp}`);
  await page
    .getByLabel(/description/i)
    .fill("E2E — uploading >10MB to verify the amber error banner appears.");
  await page.getByRole("combobox", { name: /category/i }).selectOption("bug");

  // Find the file input via Playwright's setInputFiles helper.
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles({
    name: "oversized.png",
    mimeType: "image/png",
    buffer: oversized,
  });

  await page.getByRole("button", { name: /submit/i }).click();

  // F260: amber banner must appear with the file name + a "failed"
  // marker. Pre-fix this was silently swallowed and the form just
  // cleared, leaving no signal to the user.
  await expect(
    page.getByText(/attachment.* failed/i)
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/oversized\.png/i)).toBeVisible();

  // Form should NOT be cleared — pendingFiles + description stay so
  // the user can fix and retry without re-typing.
  await expect(page.getByLabel(/description/i)).not.toHaveValue("");
});
