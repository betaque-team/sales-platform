# Training Data Capture Pipeline

This document covers the training-data capture system: what gets
captured, how privacy is enforced, how to export it for model
training, and how to extend it with new task types.

The goal: every meaningful labeled signal on the platform — a review
decision, an AI generation, a role classification — gets persisted
as a `(input, label)` row that a future custom model can train on.
Without this pipeline, those signals are visible only as side-effects
in unrelated tables (`reviews`, `jobs`, `ai_customization_logs`) and
can't be cleanly extracted for ML work.

---

## What gets captured

Six task types, all sharing one `training_examples` table
(discriminated by `task_type` column):

| Task type | When captured | Inputs | Label | Volume estimate |
|---|---|---|---|---|
| `resume_match` | `POST /reviews` | resume + JD + role_cluster | `accepted` / `rejected` / `skipped` | ~50/day per active user |
| `role_classify` | One-shot backfill from existing Jobs | job title + JD | `role_cluster` (infra/security/...) | ~13k initial + ~500/day |
| `cover_letter_quality` | `POST /cover-letter/generate` (success) | resume + JD + tone | initially `generated`; future UI events bump to `kept`/`regenerated`/`applied` | depends on AI feature usage |
| `interview_prep_quality` | `POST /interview-prep/generate` (success) | resume + JD | initially `generated` | depends on AI feature usage |
| `customize_quality` | `POST /resume/{id}/customize` (success) | resume + JD + target_score + customized_text | initially `generated` | depends on AI feature usage |
| `search_intent` | (not yet wired) | filter state + query | clicked job ids | future |

`resume_match` is the highest-value signal — every review event
becomes one labeled row, and the label (`accepted` / `rejected`) is
exactly what a future "is this resume a good match for this job"
model needs to learn.

---

## Privacy: what we strip and how

Every free-text field passes through `app/utils/training_scrub.py`
before persistence:

| Pattern | Replaced with |
|---|---|
| Email addresses (`foo@bar.com`) | `[EMAIL]` |
| Phone numbers (international + US formats, ≥7 digits) | `[PHONE]` |
| Personal URLs (`linkedin.com/in/...`, `github.com/<user>`, `twitter.com/<handle>`, `t.me/<handle>`) | `[PERSONAL_URL]` |
| The first name-shaped line of the resume (resume header) | `[NAME]` |

The scrub is **conservative** — false positives are better than false
negatives. A "[NAME]" placeholder leaking into "Hello, [NAME] is the
project lead" is harmless; a real email leaking into a training
corpus is not.

User identity is preserved as a **hashed identifier**:

- `user_id_hash` = `SHA-256(JWT_SECRET + user_id)[:32]`
- Stable per environment — same user produces the same hash across
  runs, enabling per-user train/eval splits.
- Never reversible without the JWT secret.
- Two different deploy environments produce different hashes for
  the same user, preventing cross-env data leakage.

The actual `user_id` is **not** stored. If you need to debug "who
produced this row?", you must compute the hash with the env secret
and look it up.

---

## Schema

```sql
CREATE TABLE training_examples (
    id              UUID PRIMARY KEY,
    task_type       VARCHAR(40) NOT NULL,         -- resume_match | role_classify | ...
    label_class     VARCHAR(64),                  -- accepted | rejected | infra | ...
    inputs          JSONB NOT NULL DEFAULT '{}'::jsonb,
    labels          JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json   JSONB NOT NULL DEFAULT '{}'::jsonb,
    user_id_hash    VARCHAR(64),                  -- nullable (some tasks have no user)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_training_examples_task_created ON training_examples (task_type, created_at DESC);
CREATE INDEX ix_training_examples_task_label   ON training_examples (task_type, label_class);
CREATE INDEX ix_training_examples_user_hash    ON training_examples (user_id_hash);
```

`inputs` and `labels` shape varies by task type. Examples:

### resume_match

```json
{
  "inputs": {
    "resume_text": "[NAME]\n[EMAIL]\n[PHONE]\n\nSenior DevOps Engineer | 5+ years...",
    "job_title": "Senior Security Operations Engineer",
    "job_description": "About Cribl: We're building..."
  },
  "labels": { "decision": "accepted" },
  "label_class": "accepted",
  "metadata_json": { "role_cluster": "security", "job_id": "65ab171c-..." },
  "user_id_hash": "a3f5...",
  "created_at": "2026-04-17T05:42:00Z"
}
```

### role_classify

```json
{
  "inputs": {
    "job_title": "Senior Backend Engineer, Platform",
    "job_description": "We're hiring a..."
  },
  "labels": {
    "role_cluster": "infra",
    "matched_role": "Backend Engineer"
  },
  "label_class": "infra",
  "metadata_json": { "job_id": "...", "platform": "greenhouse", "first_seen_at": "..." },
  "user_id_hash": null,
  "created_at": "..."
}
```

### cover_letter_quality / interview_prep_quality / customize_quality

```json
{
  "inputs": {
    "resume_text": "[NAME]\n...",
    "job_title": "...",
    "job_description": "...",
    "tone": "professional"        // cover_letter only
  },
  "labels": {
    "cover_letter_text": "When sophisticated threats demand...",
    "outcome": "generated"
  },
  "label_class": "generated",
  "metadata_json": { "model_version": "claude-sonnet-4-20250514", "job_id": "..." },
  "user_id_hash": "a3f5...",
  "created_at": "..."
}
```

`outcome` starts as `generated`. A future UI signal ("user kept the
letter and applied with it" vs "user regenerated") bumps it to a
quality label, turning these from input/output pairs into proper
quality labels.

---

## API

### `GET /api/v1/training-data/stats`

Admin only. Returns row counts per task_type + class balance:

```json
{
  "by_task_type": {
    "resume_match":           { "total": 1234, "by_class": {"accepted": 543, "rejected": 612, "skipped": 79} },
    "role_classify":          { "total": 13421, "by_class": {"infra": 5210, "security": 3401, "unclassified": 4810} },
    "cover_letter_quality":   { "total": 188,  "by_class": {"generated": 188} },
    "interview_prep_quality": { "total": 91,   "by_class": {"generated": 91} },
    "customize_quality":      { "total": 156,  "by_class": {"generated": 156} },
    "search_intent":          { "total": 0,    "by_class": {} }
  },
  "total_rows": 15090,
  "earliest": "2026-04-17T05:01:23Z",
  "latest":   "2026-04-17T08:42:51Z"
}
```

Surfaced on the admin Monitoring page under "Training data capture".

### `GET /api/v1/training-data/export`

Admin only. Streams JSONL (one example per line). Audit-logged.

```
?task_type=resume_match  (required, Literal-validated)
&since=2026-04-10T00:00:00Z  (optional, ISO datetime)
&limit=50000  (optional, capped at EXPORT_MAX_ROWS=50000)
```

Response: `Content-Type: application/x-ndjson`, `Content-Disposition:
attachment; filename="training_<task>_<timestamp>.jsonl"`,
`X-Row-Count` header.

Example:

```bash
curl -b cookies.txt \
  "https://salesplatform.reventlabs.com/api/v1/training-data/export?task_type=resume_match&limit=10000" \
  > resume_match.jsonl

# Verify count:
wc -l resume_match.jsonl

# Quick analysis with jq:
jq -r '.label_class' resume_match.jsonl | sort | uniq -c
```

50K row cap per call. To export more, paginate using `?since=` with
the most recent `created_at` you saw in the previous batch.

### `POST /api/v1/training-data/backfill-role-classify`

Admin only. Walks `Jobs` table and emits one `role_classify`
training_example per job. Idempotent — skips Jobs already represented
in the table (matched on `metadata_json->>'job_id'`).

```
?max_jobs=10000  (optional cap for smoke testing)
```

Response:

```json
{ "scanned": 13421, "written": 13421, "skipped_already_present": 0 }
```

Run this once after deploy to seed the `role_classify` task type with
the existing job corpus. Re-running is safe; the second run reports
`skipped_already_present == scanned` and writes nothing.

A button at the bottom of the Monitoring page training-data tile
triggers this.

---

## Admin UI

`/monitoring` (admin-only) has a "Training data capture" section at
the bottom showing:

- Row counts per task type
- Class balance (top 4 classes per task with percentages)
- "JSONL" download button per task (calls the streaming export)
- "Backfill role_classify from existing Jobs" button

The download buttons use plain `<a href>` so the browser's existing
session cookie streams the file directly — no JS-memory bouncing
through `Blob.createObjectURL`.

---

## Failure mode: capture is side-effect-only

Every capture helper wraps its `db.add` + `db.commit` in a
try/except that **logs and swallows**. The user-facing write that
triggered the capture (review, AI generation) is never blocked by a
training-capture failure.

This means: if the `training_examples` table is locked / disk full /
schema-drifted, the user keeps reviewing and the platform keeps
working. You'll see `WARNING: training_capture: failed to persist
<task> example: ...` in the backend logs, but no 5xx to the user.

---

## Adding a new task type

1. Add a constant to `app/models/training_example.py`:

   ```python
   TASK_NEW_THING = "new_thing"
   TASK_TYPE_VALUES = (..., TASK_NEW_THING)
   ```

2. Add a capture helper to `app/utils/training_capture.py` matching
   the existing pattern (PII scrub on text fields, hash user id,
   wrap in `_commit_safely`).

3. Call the helper at the relevant write site, wrapped in a
   side-effect try/except.

4. Update the `Literal` in `training_data.py::export_training_data`
   to include the new task type.

5. Update the Monitoring tile's `taskLabels` map in
   `MonitoringPage.tsx` for the human-readable name.

6. Update this doc.

No migration needed — the table absorbs new task types via the
`task_type` String column.

---

## Cost / storage

At current rate (~50 reviews/day + ~10 AI calls/day across the
active-user base), the table grows by roughly 60 rows/day = ~22k
rows/year. Each row is ~8KB on average (resume + JD + label JSON),
so ~175MB/year of storage. Negligible.

If volume grows 10× (more reviewers + more AI usage), still only
~1.75GB/year — well under operating budget. No retention policy
needed at this scale; we'll add one if storage becomes an issue.

---

## Future work

- **Wire `search_intent` capture.** Currently the `search_intent`
  task type exists as a constant but nothing writes to it. Hook
  would go on `GET /jobs` (capture filter state + result page) and
  on every `POST /reviews` / `POST /applications` against a job that
  came from the search results (capture click-through). Requires a
  session-id mechanism to link search → click → action.

- **Bump `cover_letter_quality` labels post-action.** When the user
  clicks "Regenerate" on a cover letter, that's a signal the first
  one wasn't good — update the corresponding training_example's
  `label_class` from `generated` to `regenerated`. Same for
  `interview_prep_quality` (label `applied_after` if the user later
  submits an Application against the same job).

- **Train the first model.** Once we have 10K+ `resume_match` rows
  with reasonable class balance, pull them and try a baseline
  embedding-based classifier. Compare to the existing relevance-score
  heuristic. If the model wins, route a small % of new jobs through
  it as a shadow, then promote to primary.
