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
| reviewer | test-reviewer@reventlabs.com | Password `TestReview123` | ❌ 401 Invalid email or password |
| viewer | test-viewer@reventlabs.com | Password `TestView123` | ❌ 401 Invalid email or password |

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
| 1 | 🔴 | Auth | `test-reviewer` & `test-viewer` credentials from password doc both return 401 — roles cannot be tested end-to-end | ⏳ needs super_admin to reset passwords via `/users/{id}/reset-password` — code path works, no code change required |
| 2 | 🔴 | Data integrity | Company count inconsistent: Dashboard says **5,827**, Companies page & Monitoring say **6,638** | ✅ fixed: Dashboard now uses `COUNT(Company.id)` to match Monitoring (`analytics.py`) |
| 3 | 🟠 | Jobs/UX | Clicking a checkbox on a job row navigates to the job detail (missing `stopPropagation`) — bulk-select effectively unusable | ✅ fixed: removed double-toggle, added explicit `stopPropagation` on input + cell (`JobsPage.tsx`) |
| 4 | 🟠 | Search | Search by company name returns 0 results for real companies (e.g. `Bitwarden` → 0, but Bitwarden jobs appear on dashboard). Confirms an existing user ticket | ✅ fixed: `jobs.py` search now matches `Job.title`, `Company.name`, and `Job.location_raw` |
| 5 | 🟠 | Admin UX | `/users` page returns empty state for non-super_admin. API returns 403 but UI shows "0 admins, 0 reviewers, 0 viewers" with no permission notice | ✅ fixed: `UserManagementPage.tsx` renders a proper permission-denied card on 403 |
| 6 | 🟡 | Analytics | Job Trends chart axis labels render `NaN/NaN` (multiple times) | ✅ fixed: `dataKey` was `date`/`new_jobs` but backend returns `day`/`total`; added aliases + guarded `tickFormatter` |
| 7 | 🟡 | Platforms | `himalayas` fetcher reports **180 errors** on last scan; 4 platforms (`bamboohr`, `jobvite`, `recruitee`, `wellfound`) report 0 jobs but are marked active | ⬜ open — needs fetcher-by-fetcher investigation (API changes likely) |
| 8 | 🟡 | Sidebar | `Settings` link lives inside `adminNavigation` (Sidebar.tsx:47-51) — reviewers/viewers can't reach their own Settings via the nav | ✅ fixed: moved `Settings` into the shared `navigation` list in `Sidebar.tsx` |
| 9 | 🔵 | Dashboard | "1864 jobs" badge on Security section wraps onto 2 lines at 1728px viewport | ✅ fixed: `Badge` now uses `whitespace-nowrap` + `shrink-0` so it never wraps |
| 10 | 🔵 | Pipeline | A card titled literally "1name" appears in `Researching` stage — looks like seeded/test data leaking to prod | ⬜ open — data cleanup task, not code. Run `DELETE FROM potential_clients WHERE company_name ILIKE '1name'` against prod (with admin approval) |
| 11 | 🔵 | Feedback | Many duplicate "Resume Score / Relevance" tickets (8 identical entries from same user 4/14) — no dedup | ✅ fixed: `feedback.py` now returns 409 if the same user posts an identical open title within 7 days |
| 12 | 🔵 | Copy | Dashboard AI Insight says "6 ATS sources" when 10 are listed on Platforms | ✅ fixed: analytics fallback now uses `COUNT(DISTINCT platform)` instead of `len(top_sources)` |

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

**End of report.**
