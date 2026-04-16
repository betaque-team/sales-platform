// Regression finding 207.c (follow-up to F207/F207.a/F207.b): even after
// the JobDetailPage error-state rewrite + api.ts 401 interceptor shipped
// in `index-BZ6AVjCK.js`, users who had the app open in a tab BEFORE the
// deploy kept running the old bundle — which still had the "Job not
// found" bug. Their browser won't fetch a new JS file until they
// manually reload, because our static-asset Cache-Control is
// `immutable, max-age=31536000` (correct — the filename is content-
// hashed, so "immutable" is literally true) and the tab already
// has the old module in memory.
//
// This module closes the loop: at boot we record the bundle hash we
// booted with, then we check for a newer hash on two triggers:
//
//   (1) tab returns to the foreground after being hidden for >10
//       minutes — classic "laptop lid closed overnight" flow. User's
//       cookie is probably also expired, and they're about to click
//       something that would silently hit the old code; reload first
//       so the new bundle's 401 interceptor fires properly.
//
//   (2) periodic 30-minute poll — catches always-visible dashboards
//       (e.g., a monitoring screen left up in the ops room) so they
//       pick up fixes without manual intervention.
//
// If the origin's index.html references a different /assets/index-*.js
// hash than the one we booted with, a deploy has shipped and we
// `window.location.reload()`. Going through the full page load fetches
// the new index.html (Cache-Control: no-store per nginx.conf from
// Round 27.1), which then pulls the new hashed bundle.
//
// Safety: we only reload on visibility-change (user is present, no
// in-flight action) or on poll tick while the tab is visible but the
// user hasn't interacted for a while. We NEVER reload while the tab
// is hidden (would abort any background request the user expects to
// complete) and we skip entirely if we couldn't detect our own boot
// hash (SSR / unusual build — fail safe rather than flap-reload).

const BUNDLE_PATTERN = /\/assets\/index-([A-Za-z0-9_-]+)\.js/;
const MIN_HIDDEN_MS = 10 * 60 * 1000; // 10 minutes
const POLL_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes

let bootHash: string | null = null;
let lastHiddenAt = 0;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let reloading = false;

function detectBootHash(): string | null {
  if (typeof document === "undefined") return null;
  // Vite emits `<script type="module" crossorigin src="/assets/index-<hash>.js">`
  // into the HTML. At runtime these are in `document.scripts`. We also
  // check modulepreload links as a secondary source in case Vite changes
  // its emission strategy in a future version.
  const scripts = Array.from(document.querySelectorAll("script[src]"));
  for (const s of scripts) {
    const src = (s as HTMLScriptElement).src || "";
    const m = src.match(BUNDLE_PATTERN);
    if (m) return m[1];
  }
  const links = Array.from(
    document.querySelectorAll('link[rel="modulepreload"][href]')
  );
  for (const l of links) {
    const href = (l as HTMLLinkElement).href || "";
    const m = href.match(BUNDLE_PATTERN);
    if (m) return m[1];
  }
  return null;
}

async function fetchLiveHash(): Promise<string | null> {
  try {
    // cache:"no-store" on the fetch PLUS explicit headers — belt and
    // suspenders for well-behaved intermediate proxies. The origin
    // already sends `Cache-Control: no-store` on "/" (nginx.conf after
    // Round 27.1), but a corporate proxy might not honor response
    // directives and we want the live copy here unconditionally.
    const res = await fetch("/", {
      cache: "no-store",
      headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
      credentials: "same-origin",
    });
    if (!res.ok) return null;
    const text = await res.text();
    const m = text.match(BUNDLE_PATTERN);
    return m ? m[1] : null;
  } catch {
    // Offline, DNS hiccup, or CORS — don't flap the user's session
    // on transient network issues. Wait for the next trigger.
    return null;
  }
}

async function maybeReload(trigger: "visibilitychange" | "poll"): Promise<void> {
  if (reloading) return;
  if (!bootHash) return;
  const liveHash = await fetchLiveHash();
  if (!liveHash || liveHash === bootHash) return;
  reloading = true;
  // eslint-disable-next-line no-console
  console.info(
    `[staleBundle] bundle changed ${bootHash} → ${liveHash} (${trigger}); reloading`
  );
  // location.reload() fetches a fresh index.html (which nginx serves
  // with Cache-Control: no-store per Round 27.1), which in turn pulls
  // the new hashed bundle. We don't try to swap modules in place —
  // React's module graph isn't designed for that and we'd end up with
  // a tree mixing pre- and post-fix components.
  window.location.reload();
}

export function initStaleBundleCheck(): void {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  bootHash = detectBootHash();
  if (!bootHash) {
    // Dev mode (Vite serves source files, no hashed bundle) or unusual
    // build output — nothing we can meaningfully compare against, so
    // opt out rather than risk flap-reloading.
    return;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      lastHiddenAt = Date.now();
      return;
    }
    // Tab just returned to foreground. If it was hidden long enough
    // to plausibly have missed a deploy, check for update.
    if (lastHiddenAt && Date.now() - lastHiddenAt >= MIN_HIDDEN_MS) {
      void maybeReload("visibilitychange");
    }
    lastHiddenAt = 0;
  });

  if (pollTimer === null) {
    pollTimer = setInterval(() => {
      // Don't hit the origin every 30 min when the user isn't looking
      // — visibility handler will catch their return. Also avoid
      // reloading a hidden tab (would terminate an in-flight request
      // the user expected to complete on their return).
      if (!document.hidden) void maybeReload("poll");
    }, POLL_INTERVAL_MS);
  }
}
