# AI Intelligence — Insights Pipeline

This document covers the twice-weekly AI Intelligence feature: how it
works, what data it sees, where the insights go, and how to extend or
debug it.

## What it does

A Celery task fires **every Monday and Thursday at 04:00 UTC** and
generates two distinct kinds of insights:

### A) Per-user actionable insights ("Your insights")

For every active user (= submitted at least one review in the last 30
days AND has an active resume), Claude analyzes their recent platform
activity and produces 4-6 specific, actionable observations.

**Example outputs:**

- `"Your acceptance rate is 60% on infra vs 25% on security, narrow your filter to focus where you're winning."` (severity: tip)
- `"Add Terraform to your resume, it appears in 78% of jobs you've accepted but only 30% of your scored jobs match it."` (severity: tip)
- `"You reject 80% of jobs at companies under 50 employees, the company size filter would save you about 40 review-clicks per week."` (severity: info)

Users see these on the new **Insights** sidebar page.

### B) Product-improvement signals ("Product insights")

A single platform-wide call analyzes aggregate user behavior and
produces 3-7 product suggestions for the admin team.

**Example outputs:**

- `"Add 'company size' to JobsPage filter, 34% of rejection reasons cite size with no current filter axis."` (category: feature_request, severity: medium)
- `"The 'remote_scope' filter is applied then cleared in 80% of sessions, UX is unclear, consider renaming to 'remote location'."` (category: ux, severity: low)
- `"Cribl, Datadog, and HashiCorp keep getting accepted but none are in is_target=true, auto-promote candidates."` (category: data, severity: medium)

Admins see these on the same Insights page (admin-only section), with
**Action / Dismiss** controls per insight.

---

## The flywheel: AI improving the product

When an admin marks a product insight `actioned` (we shipped a fix
based on it) or `dismissed` (we decided not to act), the next run's
prompt receives the prior decisions as context. This lets the LLM:

- **Score impact** — comment on whether the metric mentioned in an
  actioned insight has actually moved since the action
- **Avoid noise** — not re-suggest items the admin already dismissed

This is the closed-loop "AI improving the product" the platform was
designed for. Every triage decision the admin makes makes the next run
smarter.

---

## Schedule

| Day | Time | Task |
|---|---|---|
| Monday | 04:00 UTC | `weekly_ai_insights` |
| Thursday | 04:00 UTC | `weekly_ai_insights` |

Sequenced AFTER the existing scoring + classification jobs so insights
see the freshest data:

- 03:00 UTC — `rescore_jobs` (recompute relevance scores)
- 03:15 UTC — `auto_target_companies`
- 03:30 UTC — `rescore_active_resumes`
- **04:00 UTC — `weekly_ai_insights`** ← runs after all the above

Same schedule in both `aggressive` and `normal` modes. The insight
cadence is independent of the scan cadence — we don't want product
insights computed less often when the platform is on a slower scan
schedule.

---

## Cost

At Anthropic Sonnet 4 list pricing (~$3/M input tokens, ~$15/M output
tokens):

| Component | Per-call cost | Per-run cost (50 users) |
|---|---|---|
| Per-user insights (input ~2K, output ~1K) | ~$0.020 | $1.00 |
| Product insights (input ~5K, output ~1.5K) | ~$0.040 | $0.04 |
| **Total per run** | | **~$1.04** |
| **Per week** (Mon + Thu) | | ~$2.08 |
| **Per month** | | ~$8.30 |

At larger scale (100 users): ~$2.04/run = ~$16/month.

This is a small line item compared to the per-user AI features
(customize / cover-letter / interview-prep) which are user-triggered
and uncapped relative to scheduled jobs.

---

## What goes into the prompt

### Per-user insights — `_collect_user_signals()`

For each user, last 30 days unless noted:

- `accept_by_cluster` — cross-tab of `(role_cluster, decision)` review counts
- `top_rejection_tags` — top 10 rejection-tag counts (descending)
- `active_resume_score` — count, avg, max, p90 of ResumeScore.overall_score for the active resume
- `ai_usage_last_7d` — calls per AI feature (customize / cover_letter / interview_prep)
- `applications_last_7d` / `applications_last_30d` — counts of `applied_at` rows

The full signal block is persisted to `user_insights.input_signals` so
the prompt-version A/B comparison can replay later.

### Product insights — `_collect_product_signals()`

Platform-wide, last 7 days:

- `growing_rejection_tags` — tags whose count grew week-over-week (with the noise floor of >=5 occurrences)
- `high_accept_companies_not_targeted` — companies with accept rate >=50% over the last 7d that have `is_target=false`
- `active_users_7d` — distinct reviewer count
- `ai_feature_calls_7d` — total AI calls per feature

Plus the last 20 admin-actioned insights (status + note) so the LLM
can reference prior decisions.

---

## Output shape

Both generators return JSON arrays of insight items. The renderer is
shared so the shapes overlap:

```json
{
  "title": "Short headline (no em-dashes)",
  "body": "1-4 sentences, citing specific numbers from signals.",
  "severity": "info" | "tip" | "warning"
                | "low" | "medium" | "high",
  "category": "filter" | "resume" | "skill" | "timing" | "market"
              | "ux" | "scoring" | "data" | "feature_request" | "other",
  "action_link": "/jobs?role_cluster=infra"  // optional
}
```

`action_link` is optional and only used by per-user insights — it
deep-links to a relevant page (the JobsPage with a pre-applied filter,
the resume editor, etc.) so the user can act on the insight in one
click.

---

## Reading insights

### As a user

Click **Insights** in the sidebar. See your latest 4-6 insights for
the week. If you've never been part of a run (new account, no recent
reviews), the page shows a friendly empty state explaining the
schedule.

### As an admin

Same page, plus a **"Product insights"** section below. Default view
shows pending items (no admin decision yet). Triage with:

- **Actioned** — "we shipped a fix based on this"
- **Dismiss** — "we decided not to act"  
- **(Add note)** — optional context fed into the next run

Use the **"Run now"** button to force a fresh generation outside the
schedule (useful right after shipping a fix, to see if the suggested
improvement registered).

---

## Anti-AI-tell guardrails

The same em-dash scrubber + AI-tell phrase ban from F235 (cover
letter) applies here. Both prompts explicitly forbid:

- Em-dashes (— / –)
- Filler phrases ("consider improving", "leverage", "robust", etc.)

And both pipe output through `_strip_em_dashes()` as belt-and-
suspenders. Insights should read as if a senior career coach wrote
them, not as if a model generated them.

---

## Schemas

### `user_insights` table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `user_id` | UUID FK | indexed `(user_id, generated_at DESC)` |
| `generation_id` | UUID | groups all per-user rows from one beat run |
| `insights` | JSONB | array of insight dicts |
| `input_signals` | JSONB | snapshot of what the LLM saw (debugging, A/B) |
| `model_version` | VARCHAR(64) | e.g. `claude-sonnet-4-20250514` |
| `prompt_version` | VARCHAR(32) | e.g. `user_insights.1.0` |
| `input_tokens` / `output_tokens` | INTEGER | from Anthropic usage |
| `generated_at` | TIMESTAMPTZ | `NOW()` default |

### `product_insights` table

Same shape as above plus:

| Column | Type | Notes |
|---|---|---|
| `title` | VARCHAR(200) | not in JSONB — needs to sort/filter |
| `body` | TEXT | |
| `category` | VARCHAR(50) | `ux` / `scoring` / `data` / `feature_request` / `other` |
| `severity` | VARCHAR(20) | `low` / `medium` / `high` |
| `actioned_at` | TIMESTAMPTZ NULL | NULL = pending |
| `actioned_by` | UUID FK NULL | which admin triaged |
| `actioned_status` | VARCHAR(20) NULL | `actioned` / `dismissed` / `duplicate` |
| `actioned_note` | TEXT NULL | optional context for next run |

Partial index `ix_product_insights_pending WHERE actioned_at IS NULL`
keeps the default admin view fast.

---

## API

### `GET /api/v1/insights/me?history=N`

Returns the current user's latest insight bundle, optionally with up
to N (0-10) prior bundles for "compare to last week" UX.

```json
{
  "latest": {
    "generation_id": "...",
    "generated_at": "2026-04-17T04:00:12Z",
    "insights": [...],
    "model_version": "claude-sonnet-4-20250514",
    "prompt_version": "user_insights.1.0"
  },
  "history": []
}
```

### `GET /api/v1/insights/product?status=pending&page=1&page_size=50`

Admin-only. Filter by `pending` (default), `actioned`, `dismissed`,
or `all`. Sort: severity DESC, then generated_at DESC.

### `POST /api/v1/insights/{id}/action`

Admin-only. Body: `{"status": "actioned"|"dismissed"|"duplicate", "note": "..."}`.
Records the decision + admin id; the note is fed into the next run's
prompt as context.

### `POST /api/v1/insights/run`

Admin-only. Manually fires the Celery task. Useful for smoke-testing
a prompt change or refreshing right after shipping a fix mentioned in
a prior run. Audit-logged as `insights.manual_run`.

---

## Tuning the prompt

Both prompts are in `platform/backend/app/workers/tasks/_ai_insights.py`.
Bump the corresponding `*_PROMPT_VERSION` constant when you edit
either prompt — the version gets persisted on every row so future
analysis can compare output quality across prompt revisions.

Two natural next iterations:

1. **Add `action_link` to product insights.** Currently only per-user
   insights ship with action links; product insights are descriptive.
   A version 2 prompt could ask Claude to suggest the route (e.g.
   `/jobs?status=new`) for each insight so the admin can jump
   directly into the affected workflow.

2. **Per-cluster product insights.** Right now we generate one
   platform-wide product-insight set. A future revision could split by
   role cluster ("here's what's broken specifically for infra users")
   so admins can prioritize fixes.

---

## Failure modes

| Symptom | Likely cause |
|---|---|
| `/insights/me` returns `{"latest": null}` | User joined after last run, OR no reviews in last 30 days, OR no active resume |
| `/insights/product` returns 0 items | First run hasn't happened yet, OR all insights have been actioned/dismissed (try `?status=all`) |
| Beat schedule shows next run as expected but no new rows after | Check celery-beat container logs; check Redis broker is up; check `ANTHROPIC_API_KEY` is configured (`/api/health` ai_configured=true) |
| Insights contain em-dashes despite the prompt forbidding them | Bug in `_strip_em_dashes()` — file an issue with a sample. The post-process should always catch them as belt-and-suspenders |
| `WARNING: per-user insights failed for X` in Celery logs | Per-user errors don't take down the whole run by design. Check the user's signal block — usually a NULL field in input_signals that the LLM choked on |
