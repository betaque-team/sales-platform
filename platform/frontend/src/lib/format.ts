/**
 * Shared number / display formatters.
 *
 * Regression findings 36 + 49: raw-integer counts (47,776 → "47776")
 * were surfacing across Dashboard, Companies, Analytics, Intelligence,
 * Pipeline, and the scan-by-platform grid while Platforms and Monitoring
 * already called `.toLocaleString()`. That left the same number rendered
 * two different ways on adjacent pages ("47776" vs "47,776"), which made
 * it look like the pages were disagreeing on data.
 *
 * Centralizing via `formatCount` gives us one source of truth so future
 * counts stay grouped-by-thousand by default, and null/undefined
 * defensively renders as "0" (we never want a blank slot — see finding
 * 47 for the platforms-card version of that same mistake).
 */

/** Format a number with locale-appropriate thousand separators. */
export function formatCount(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "0";
  return n.toLocaleString();
}
