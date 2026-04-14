# Changelog

All notable changes to this project are documented in this file.

## [2.4.0] - 2026-04-13

### Added
- **QA Role Cluster**: New role cluster for Quality Assurance / Testing / SDET roles
  - 30 QA keywords (selenium, cypress, playwright, pytest, sdet, test automation, etc.)
  - 20 approved QA role titles (QA Engineer, SDET, Test Automation Engineer, etc.)
  - QA testing tools added to ATS scoring engine (jest, jmeter, gatling, k6, cucumber, etc.)
  - 384 existing jobs reclassified and re-scored as QA (avg relevance: 67.7)
  - Dashboard 3-column layout: Infra, Security, QA cards
  - Jobs page filter dropdown updated with QA option
  - "Relevant" filter now includes QA alongside Infra and Security
- **LinkedIn Integration via JSearch API** (RapidAPI)
  - Multi-strategy fetcher: JSearch API (primary) → LinkedIn Data API (alternative) → HTML scraping (fallback)
  - JSearch pulls ~30 jobs per company across 3 pages with salary data, employment type, and remote flags
  - 41 LinkedIn boards configured across top companies (Cloudflare, Datadog, CrowdStrike, etc.)
  - 1,019 LinkedIn jobs indexed (417 new from initial JSearch scan)
  - Configurable via `RAPIDAPI_KEY` and `RAPIDAPI_LINKEDIN_HOST` env vars
- **Feedback File Attachments**: Screenshot URL field on feedback submissions
  - New `screenshot_url` column on feedback table (migration `i9d0e1f2g3h4`)
  - URL input field in feedback form, stored and displayed on feedback cards
- **Feedback Approval Fields**: `approved_by`, `approved_at`, `approver_role` columns (migration `h8c9d0e1f2g3`)

### Fixed
- **ATS scoring inflation**: Non-technical resumes no longer score 80+ against technical roles
  - Fixed `compute_role_alignment` multiplier (`* 200` → `* 100`)
  - Added technical depth guard: resumes with <3 tech keywords capped at 15 role alignment
  - QA roles now included in `_title_match_score` approved roles set
- **Platforms import button**: Silent failures now show dismissible error banner with details
- **Enrich Now button**: Added polling via `refetchInterval` so enrichment progress updates live
  - Local state + useEffect handles race condition between mutation success and query refresh
- **502 Bad Gateway after deploys**: Documented tunnel-nginx restart requirement after container recreation

### Changed
- Dashboard grid layout: 2-column → 3-column for role cluster cards (Infra, Security, QA)
- LinkedIn fetcher rewritten with multi-strategy fallback and JSearch as default
- Word-boundary keyword protection extended: `qa`, `sdet` added to prevent false positives
- Relevance scoring: QA jobs now score on par with Infra/Security (avg 67.7 vs 64.4/63.6)

## [2.3.0] - 2026-04-05

### Added
- **Configurable Role Clusters**: Admin UI to manage which job categories count as "relevant"
  - New `role_cluster_configs` DB table with name, keywords, approved roles, is_relevant flag
  - Admin page at `/role-clusters` with full CRUD
  - Dynamic `_get_relevant_clusters(db)` helper replaces hardcoded cluster list
  - Fallback to `["infra", "security"]` when no clusters configured
- **5 New Platform Fetchers**: Himalayas, Wellfound, Jobvite, SmartRecruiters, Recruitee
  - Total platforms: 10 (up from 5)
  - Source tiers updated: Tier 1 (Greenhouse, Lever, Ashby, Workable, BambooHR), Tier 2 (SmartRecruiters, Jobvite, Recruitee, Wellfound), Tier 3 (Himalayas)
- **Platform Discovery Scan**: Probes slugs across all platforms, auto-creates Company + Board records
  - `discover_and_add_boards` Celery task with multi-platform probing
  - Trigger from admin Monitoring panel
- **Resume scoring expanded**: Scores against ALL relevant jobs (removed previous 20-job limit)
- **AI resume customization restricted**: Only available for jobs in relevant clusters

### Changed
- Discovery task rewritten to probe Lever, Ashby, Wellfound, SmartRecruiters, Recruitee (was Greenhouse-only)
- Monitoring page enhanced with scan controls grid for all 10 platforms

## [2.2.0] - 2026-04-05

### Added
- **User Management** (admin): Register, list, update roles, toggle active, reset passwords, delete users
  - Admin page at `/users` with role overview cards, user table, inline actions
  - Safety checks: cannot remove last admin, cannot deactivate self
- **Scan Controls** (admin): Trigger full, per-platform, or per-board scans from Monitoring panel
  - Async Celery tasks with live status polling
  - `scan_platform` and `scan_single_board` tasks
- **Password Management**: Change password (all users), admin force-reset, self-service reset flow
- **Authorization Roles**: admin, reviewer, viewer with role-based route protection

### Changed
- Settings page now includes password change form
- Monitoring page now includes scan control buttons and task status indicators
- Sidebar admin section expanded: Monitoring, User Management, Role Clusters, Settings

## [2.1.0] - 2026-04-04

### Added
- **Resume ATS Scoring**: Upload PDF/DOCX, extract text, score against top relevant jobs
  - 50% keyword overlap, 30% role alignment, 20% format/completeness
- **AI Resume Customization**: Claude API rewrites resume to target a specific ATS score
- **Company Scoring**: Score companies by remote-friendliness and hiring patterns
- **Resume Score Page**: UI for uploading, viewing scores, and triggering AI customization

## [2.0.0] - 2026-04-03

### Added
- **Full-stack platform** replacing standalone Python monitor
  - FastAPI async backend with SQLAlchemy + PostgreSQL
  - Celery + Redis background workers
  - React 18 + TypeScript + TanStack Query frontend
  - Docker Compose deployment (6 services)
- **Core features**: Dashboard, Jobs (with filters/search), Review Queue, Companies, Platforms, Pipeline, Analytics
- **5 ATS fetchers**: Greenhouse, Lever, Ashby, Workable, BambooHR
- **Multi-signal relevance scoring** (0-100): title, company, geography, source, freshness
- **Role classification**: infra and security clusters with keyword matching
- **Geography classification**: global_remote, usa_only, uae_only
- **JWT auth** with Google OAuth support
- **Admin monitoring** with DB stats, activity logs, platform breakdowns

## [1.0.0] - 2026-04-01

### Added
- Initial standalone Python job monitor (`job-monitor/`)
- SQLite-based storage
- Greenhouse, Lever, Ashby, Workable scrapers
- CSV export
- Manual prompt-based scraping with Claude (prompts/, outputs/)

### Removed (in 2.0.0)
- `job-monitor/` - Replaced by `platform/backend/`
- `prompts/` - Scraping now automated
- `outputs/` - Data now in PostgreSQL
- `changelog/` - Replaced by this file
- `learnings/` - Incorporated into platform logic
- `resources/` - Data imported to DB
