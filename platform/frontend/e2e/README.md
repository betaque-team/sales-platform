# E2E tests — local-only Playwright harness (F265)

These tests run **on your local machine, not in CI**. The deliberate
choice (per the F265 ship decision) is that GitHub Actions free
minutes are precious and E2E runs would burn them fast — so we put
the friction on the developer's laptop instead.

The trade-off: nothing fails on push. The compensating control is
the pre-merge checklist below — run these tests before pushing
changes that touch any of the surfaces they cover.

## What's covered

| Spec | Catches |
|---|---|
| `auth.spec.ts` | F207 — mid-session 401 should redirect to `/login?next=...`, not silent-fail with "not found" |
| `jobs-filter.spec.ts` | F260 #3 — Sidebar "Relevant Jobs" vs "All Jobs" must produce distinct URLs and totals |
| `feedback-attachment.spec.ts` | F260 #1 — oversized/wrong-MIME attachment failures must surface in the amber error banner, not silently swallow |
| `profile-vault-delete.spec.ts` | F260 #4 — "Delete permanently" button visible to admin; typed-email gate enforced |
| `team-pipeline.spec.ts` | F261 — Admin scope toggle on `/applications`; Pipeline card "Apps" drill-down panel |
| `geography-badge.spec.ts` | F260 #2 + F263 — Every job row has a geography badge (real bucket or muted "unclassified" fallback); table has scrollbar-gutter:stable |

## Prereq — running services on localhost

Tests target `http://localhost:3000` (frontend) and assume the
backend is at `http://localhost:8000`. Boot the stack first:

```bash
cd platform
docker compose up -d
docker compose exec backend alembic upgrade head
# (one-time) seed an admin + a profile + some jobs to cover all 6 specs
docker compose exec backend python -m app.seed_admin
docker compose exec backend python -m app.seed_remote_companies
# kick a scan so the jobs table has rows
docker compose exec backend python -c "
from app.workers.tasks.scan_task import scan_all_platforms
scan_all_platforms.delay()
"
```

Wait ~1 min for the scan to populate enough jobs for `geography-
badge.spec.ts` to have material to assert on.

## First-time install

```bash
cd platform/frontend
npm install                    # picks up @playwright/test devDep
npm run e2e:install            # downloads Chromium + Firefox binaries
```

## Running the tests

```bash
cd platform/frontend
npm run e2e                    # headless, both browsers
npm run e2e -- --project chromium    # chromium only (faster)
npm run e2e:ui                 # Playwright UI mode — best for debugging
```

A failing test drops a `playwright-report/` directory with traces +
screenshots. Open it with:

```bash
npx playwright show-report
```

## Credentials

By default the tests log in as `admin@jobplatform.io` /
`admin123` (the seed admin). Override via env:

```bash
E2E_ADMIN_EMAIL=other@example.com \
E2E_ADMIN_PASSWORD=hunter2 \
  npm run e2e
```

## Pre-merge checklist (the workflow)

If your PR touches any of these files, **run the relevant spec
locally before pushing**:

| Files touched | Run |
|---|---|
| `Sidebar.tsx`, `JobsPage.tsx`, `auth.tsx`, anything in `lib/api.ts` related to auth | `npm run e2e -- auth.spec.ts jobs-filter.spec.ts` |
| `FeedbackPage.tsx` or `feedback.py` backend | `npm run e2e -- feedback-attachment.spec.ts` |
| `ProfileDetailPage.tsx` or `profiles.py` backend | `npm run e2e -- profile-vault-delete.spec.ts` |
| `ApplicationsPage.tsx`, `PipelinePage.tsx`, `applications.py` (`/team` route), `pipeline.py` (`/{id}/applications` route) | `npm run e2e -- team-pipeline.spec.ts` |
| `_role_matching.py`, geography classifier, JobsPage row-rendering | `npm run e2e -- geography-badge.spec.ts` |

A full run takes ~2 min. Per-spec runs are 10-30 sec.

## Known limitations

- Tests assume a populated DB. If the local DB is empty, several
  specs will skip (they print a clear "no rows seeded" message).
- The two browser projects (Chromium + Firefox) double the run
  time. Use `--project chromium` while iterating.
- These are **structural / behavioural** tests, not visual regression.
  A CSS rewrite that changes badge colours but preserves text + ARIA
  will pass — that's deliberate. We rely on the user reviewing the
  diff for visual changes.
- No Cypress/Playwright installation inside the docker-compose stack
  — tests run from the host against the served frontend on `localhost
  :3000`, not from inside a container.

## Adding a new spec

When a new feature ships, add an E2E test in the same PR. The
pattern is: import `loginAsAdmin` from `fixtures/auth.ts`, scope
your assertions to a single user-visible flow, prefer ARIA roles
(`getByRole`) over CSS selectors. See existing specs for examples.
