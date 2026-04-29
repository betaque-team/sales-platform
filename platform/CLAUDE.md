# CLAUDE.md - Job Platform

## Project Overview
Full-stack job aggregation and sales intelligence platform. Scrapes job boards (Greenhouse, Lever, Ashby, Workable, BambooHR), classifies roles, scores relevance, and provides ATS resume scoring with AI-powered customization.

## Architecture
- **Backend**: FastAPI (async) + SQLAlchemy (async for API, sync for Celery) + PostgreSQL
- **Workers**: Celery + Redis for background scanning tasks
- **Frontend**: React 18 + TypeScript + TanStack Query + Tailwind CSS + Recharts
- **Deployment**: Docker Compose (6 services: postgres, redis, backend, celery-worker, celery-beat, frontend)

## Directory Structure
```
platform/
  backend/
    app/
      api/v1/          # FastAPI routers (jobs, reviews, companies, platforms, resume, monitoring, analytics)
      models/           # SQLAlchemy models (Job, Company, Resume, Review, etc.)
      schemas/          # Pydantic schemas
      fetchers/         # ATS board fetchers (greenhouse, lever, ashby, workable, bamboohr)
      workers/tasks/    # Celery tasks + scoring/matching engines
      config.py         # Settings from env vars
      database.py       # DB engine + session factory
      main.py           # FastAPI app entrypoint
    alembic/            # Database migrations
  frontend/
    src/
      pages/            # React page components
      components/       # Reusable UI components
      lib/              # API client, types, auth
  docker-compose.yml
  .env
```

## Key Concepts

### Role Clusters
Jobs are classified into two scored clusters:
- **infra**: DevOps, Cloud, Infrastructure, SRE, Platform Engineering, Kubernetes, etc.
- **security**: Security, DevSecOps, SOC, Compliance, GRC, Penetration Testing, etc.
Jobs outside these clusters are saved but unscored (relevance_score = 0).

### Geography Classification
- `global_remote`: Worldwide/anywhere remote
- `usa_only`: US-restricted remote
- `uae_only`: UAE-restricted remote
- Empty: Unclassified or region-locked

### Relevance Scoring (0-100)
Weighted: 40% title match, 20% company fit, 20% geography clarity, 10% source priority, 10% freshness

### ATS Resume Scoring
Users upload resumes (PDF/DOCX), text is extracted, scored against top jobs:
- 50% keyword overlap
- 30% role alignment
- 20% format/completeness
AI customization uses Claude API to rewrite resume for target score.

## Running
```bash
cd platform
docker compose build
docker compose up -d
# Create tables if needed:
docker compose exec backend alembic upgrade head
# Seed remote companies:
docker compose exec backend python -m app.seed_remote_companies
```

## Environment Variables (.env)
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `JWT_SECRET` - JWT signing secret
- `ANTHROPIC_API_KEY` - For AI resume customization (optional)
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` - OAuth (optional)

## API Conventions
- Pagination: `{ items, total, page, page_size, total_pages }`
- Auth: JWT in cookie, `get_current_user` dependency
- Admin-only: `require_role("admin")` dependency
- File uploads: multipart/form-data (resume upload)

## Frontend Conventions
- All API calls through `lib/api.ts` using `request<T>()` helper
- State management via TanStack Query (`useQuery` / `useMutation`)
- Types in `lib/types.ts`
- Routing in `App.tsx`, navigation in `components/Sidebar.tsx`

## Current State
- ~13,000 jobs from 786 ATS boards across 4 platforms
- ~1,667 relevant scored jobs (842 infra + 825 security)
- Dashboard with Relevant Jobs, All Jobs, Infra, Security, Global Remote sections
- Admin monitoring panel with DB stats, activity, breakdowns
- Resume ATS scoring with AI customization
- Company scoring for filtering

## E2E Tests (F265)
Playwright suite at `platform/frontend/e2e/`. **Local-only — NOT in
CI** to preserve GitHub Actions free minutes. Run before pushing
changes to user-facing flows:
```bash
cd platform/frontend
npm run e2e -- --project chromium       # 6 specs, ~2 min
```
Covers regression surfaces from F260, F261, F263, F207. See
`platform/frontend/e2e/README.md` for the full pre-merge checklist
(which spec to run for which file change).
