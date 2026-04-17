# AI Features — Usage, Limits, and Costs

This document covers the three AI-generation features on the platform,
their per-user daily limits, what happens when you hit a limit, and
the design rationale behind the numbers.

If you're an end user looking for the short version: see the
**"What you can do"** table below. If you're an operator deciding
whether to raise the limits or fund a budget bump, jump to **Cost
model** and **Adjusting limits**.

---

## What you can do

| Feature | Endpoint | Daily limit per user | What it does |
|---|---|---|---|
| **Cover letter** | `POST /api/v1/cover-letter/generate` | **30 / day** | Generates a tailored cover letter for one job, using your active resume + the job description. Choose tone: professional, enthusiastic, technical, conversational. |
| **Interview prep** | `POST /api/v1/interview-prep/generate` | **10 / day** | Generates a study guide for one job: likely interview questions, talking points from your resume, company research items, and red flags to ask about. |
| **Resume customize** | `POST /api/v1/resume/{id}/customize` | **10 / day** | AI rewrites your resume to better match a specific job's keywords and role profile. Targets a configurable ATS score (60-95). Restricted to jobs in your relevant role clusters. |

All three counters reset at **midnight UTC**.

The platform shows your remaining budget inline on the AI Tools panel
of any job's detail page — look for the small "X / Y left" pill next to
each feature button.

---

## What happens when you hit a limit

The endpoint returns **HTTP 429 Too Many Requests** with:

- `detail`: human-readable message naming the feature and limit, e.g.
  `"Daily cover letter limit reached (30/day). Resets at midnight UTC."`
- `Retry-After` header: integer seconds until the next reset (capped
  at 86400). Standard HTTP semantic — well-behaved clients (curl
  --retry, browser fetch + retry libs, monitoring tools) honor it.

The frontend translates this into a toast that includes the
"Resets midnight UTC" text + a real countdown.

**Failed calls don't count.** If the AI call itself fails (no API key
configured, upstream Anthropic 5xx, safety refusal, network timeout),
the audit log still records the attempt but the rate-limit counter
ignores it. You only consume quota when the AI actually produced a
result you could use. This is the F170/F203 design — debugging an
intermittent upstream issue would otherwise burn the user's daily
budget through no fault of their own.

---

## How the count works

- All three features write to the same `ai_customization_logs` table,
  discriminated by a `feature` column (one of `customize`,
  `cover_letter`, `interview_prep`).
- The rate-limit query is `SELECT COUNT(*) FROM ai_customization_logs
  WHERE user_id = $1 AND feature = $2 AND success = TRUE AND created_at
  >= midnight_utc_today`. There's a composite index on `(user_id,
  feature, created_at)` so the lookup stays O(1)-cardinality even at
  100k+ rows.
- The `success` filter is the F170 fix — see **What happens when you
  hit a limit** above.

---

## Cost model

At Anthropic Sonnet 4 list pricing (~$3 / M input tokens, ~$15 / M
output tokens) — list prices, no negotiated discounts assumed:

| Feature | Tokens (in / out) | Cost per call |
|---|---|---|
| Resume customize | ~7K / 2K | ~$0.05 |
| Cover letter | ~6K / 2K | ~$0.05 |
| Interview prep | ~6K / 2K | ~$0.05 |

**Worst-case daily spend per user** (if a single user hits every cap):
- 10 customize × $0.05 = $0.50
- 30 cover letter × $0.05 = $1.50
- 10 interview prep × $0.05 = $0.50
- **Total: $2.50/user/day**

**Realistic platform spend** at 50 active users with average usage
(~30% of caps consumed per day): ~$37.50/day = ~$1,125/month.

---

## Why these numbers

The 30/10/10 ratio matches typical reviewer workflow shape:

- **Cover letter (30)** is the highest-volume feature because reviewers
  draft cover letters as part of every application. A reviewer who
  applies to 20 jobs in a day consumes most of the cap legitimately;
  the 30 ceiling absorbs that plus regenerations with different tones.
- **Interview prep (10)** is lower because it only fires once per job
  the user is actually about to interview at — a reviewer doesn't
  prepare for 30 interviews a day. Anything above 10 is almost
  certainly an automation bug or experimentation, not real use.
- **Resume customize (10)** stays at the existing F170 number — a
  reviewer customizes their resume once per "job they're seriously
  considering", which matches the interview-prep cadence.

If a user consistently hits these limits in normal workflow, that's
signal to raise them (admin contact below).

---

## Adjusting limits

Three knobs in `platform/backend/app/config.py`:

```python
ai_daily_limit_per_user: int = 10           # customize
ai_cover_letter_daily_limit_per_user: int = 30
ai_interview_prep_daily_limit_per_user: int = 10
```

Each maps to an env var (uppercased): `AI_DAILY_LIMIT_PER_USER`,
`AI_COVER_LETTER_DAILY_LIMIT_PER_USER`,
`AI_INTERVIEW_PREP_DAILY_LIMIT_PER_USER`. Set them on the VM's
`/opt/sales-platform/.env` and restart the backend container —
the values are read at process startup via `Settings()`.

Per-role caps (e.g. higher limit for admins) are not implemented yet.
The current behavior is "every user gets the same cap regardless of
role". If you need that, file an issue describing the policy you want
and we'll add a role-keyed lookup.

---

## API reference

### `GET /api/v1/ai/usage`

Returns the current user's per-feature usage snapshot. Authenticated.

```json
{
  "has_api_key": true,
  "reset_at_utc": "2026-04-17T00:00:00Z",
  "features": {
    "customize":      {"used": 3, "limit": 10, "remaining": 7},
    "cover_letter":   {"used": 1, "limit": 30, "remaining": 29},
    "interview_prep": {"used": 0, "limit": 10, "remaining": 10}
  }
}
```

`reset_at_utc` is the START of today's window; the next reset is at
+24h. The frontend renders a relative countdown ("Resets in 4h 23m")
by computing `(reset_at_utc + 24h) - now`.

### Backwards-compatible alias: `GET /api/v1/resume/ai-usage`

Returns the same `customize` block in its legacy flat shape plus the
new `features` map for new callers:

```json
{
  "used_today": 3,
  "daily_limit": 10,
  "remaining": 7,
  "has_api_key": true,
  "reset_at_utc": "2026-04-17T00:00:00Z",
  "features": { ... same as /ai/usage ... }
}
```

This will stay around indefinitely — no deprecation timeline. New
frontend code should prefer `/ai/usage` so it picks up new features
automatically without a per-feature endpoint update.

### Per-call usage block

All three generation endpoints return a `usage` block in their
response so the frontend can update its "X / Y left" badge without a
second round-trip:

```json
{ "...other fields...", "usage": {"used": 4, "limit": 30, "remaining": 26} }
```

The shape matches one entry of `/ai/usage::features`.

---

## When the AI is unavailable

If `ANTHROPIC_API_KEY` is not configured on the VM (see
[DEPLOY_SETUP.md](./DEPLOY_SETUP.md) for the F234 plumbing):

- `GET /api/health` reports `ai_configured: false`
- `POST /cover-letter/generate` returns **HTTP 503**
- `POST /interview-prep/generate` returns **HTTP 503**
- `POST /resume/{id}/customize` returns **HTTP 200** with
  `{"error": true, "improvement_notes": "AI customization requires
  an Anthropic API key."}` (this asymmetry is intentional per F203
  — the existing ResumeScorePage UI renders inline-error from this
  shape; flipping it to 503 would break the UX)

In all three cases, **no quota is consumed** — failed calls are
audited but don't count against the daily limit.

---

## Audit + observability

Every call writes to `ai_customization_logs` with:

- `user_id`, `feature`, `created_at`
- `input_tokens`, `output_tokens` (when available)
- `success: bool` (false rows persist for debugging but don't burn
  quota)
- `resume_id`, `job_id` (nullable; populated when known)

Admins can query this directly for usage breakdowns, cost attribution,
or abuse investigation. A future round may surface aggregates on the
admin Monitoring page.
