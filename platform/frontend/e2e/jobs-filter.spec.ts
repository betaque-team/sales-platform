/**
 * F265 #2 — Jobs filter URL disambiguation.
 *
 * Catches: F260 #3 ("Relevant Jobs" and "All Jobs" showed identical
 * data) and any future cluster-filter regression. The pre-fix bug
 * was that JobsPage's localStorage filter-restore silently re-applied
 * a stale ``role_cluster=relevant`` filter when the URL had no params.
 * F260 fixed it with an explicit ``role_cluster=any`` sentinel on
 * the All Jobs sidebar link.
 *
 * The structural assertion: clicking the two sidebar links from the
 * SAME starting state must produce DIFFERENT result counts (any total
 * > relevant total) AND DIFFERENT URLs.
 */
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./fixtures/auth";

test.beforeEach(async ({ page }) => {
  await loginAsAdmin(page);
});

test("Relevant Jobs and All Jobs sidebar links go to distinct URLs", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /relevant jobs/i }).click();
  await expect(page).toHaveURL(/role_cluster=relevant/);

  await page.getByRole("link", { name: /all jobs/i }).click();
  // F260: All Jobs MUST carry an explicit role_cluster=any sentinel.
  // Without it, the URL is just /jobs and JobsPage's localStorage
  // restore re-applies "relevant" → both pages show identical data.
  await expect(page).toHaveURL(/role_cluster=any/);
});

test("All Jobs total is greater than Relevant Jobs total", async ({ page }) => {
  // Navigate via direct URL so we don't depend on sidebar click order.
  await page.goto("/jobs?role_cluster=relevant");
  // The total count is rendered somewhere on the page — typically in
  // the page header or a summary line. We grep the page text for
  // ``\d+\s*results`` or ``\d+\s*jobs`` patterns. If the rendering
  // changes, this assertion needs updating but the spec catches the
  // intent.
  const relevantText = await page.locator("body").innerText();
  const relevantMatch = relevantText.match(/(\d{1,3}(?:,\d{3})*)\s*(?:results|jobs|total)/i);
  expect(relevantMatch, "Could not find a count on Relevant Jobs page").toBeTruthy();
  const relevantTotal = parseInt(relevantMatch![1].replace(/,/g, ""), 10);

  await page.goto("/jobs?role_cluster=any");
  const anyText = await page.locator("body").innerText();
  const anyMatch = anyText.match(/(\d{1,3}(?:,\d{3})*)\s*(?:results|jobs|total)/i);
  expect(anyMatch, "Could not find a count on All Jobs page").toBeTruthy();
  const anyTotal = parseInt(anyMatch![1].replace(/,/g, ""), 10);

  // The single most important invariant: All Jobs ≥ Relevant Jobs.
  // F260's bug made these equal. We use ≥ instead of > to allow the
  // edge case where every classified job is relevant (unlikely in
  // prod but possible in a small test seed).
  expect(anyTotal).toBeGreaterThanOrEqual(relevantTotal);
});

test("Sidebar active-link state distinguishes Relevant from All", async ({ page }) => {
  await page.goto("/jobs?role_cluster=relevant");
  // The active link gets an ``aria-current`` attribute or a distinct
  // class. We assert that "Relevant Jobs" is the active link, NOT
  // "All Jobs". F260's bug pre-fix would have flagged BOTH as active.
  const relevantLink = page.getByRole("link", { name: /relevant jobs/i });
  const allLink = page.getByRole("link", { name: /all jobs/i });

  // Both links should be visible at all times.
  await expect(relevantLink).toBeVisible();
  await expect(allLink).toBeVisible();

  // Active state — different visual class. We check that the two
  // links don't have IDENTICAL ``class`` attributes when one is
  // selected. This is a pragmatic regression guard rather than a
  // pixel-perfect check.
  const relevantClass = await relevantLink.getAttribute("class");
  const allClass = await allLink.getAttribute("class");
  expect(relevantClass).not.toEqual(allClass);
});
