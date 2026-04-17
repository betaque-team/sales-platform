# Releases

Chronological log of production releases to `salesplatform.reventlabs.com`.
Newest at the top. Each entry is one merge to `main` that triggered a deploy
via [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml).

**How this file is maintained.** The deploy workflow appends a stub entry
automatically on every successful merge-to-main run (see the `append-release`
step in `deploy.yml`). The stub contains: short SHA, tag, UTC timestamp, and
the commit subject. A human can then edit the stub to add the "why it
matters" line — keep it user-facing, one sentence, no implementation details.

**Format per entry:**

```
## YYYY-MM-DD · <short-sha> · <tag>
<one-line commit subject>

<optional one-sentence user-facing summary>
```

The one-line commit subject is the machine-written bit; the user-facing
summary is the human edit. Entries with only the subject (no summary) are
still-to-be-annotated — fine to leave as-is for minor fixes.

For per-feature deep-dives, the `docs/releases/` subdirectory holds the
long-form writeups (one `.md` per notable round). This file is the index.

---

<!-- RELEASES_LOG_START -->

## 2026-04-17 · 9a3bdd1 · sha-9a3bdd1
Merge Round 1 QoL: Opus 4.7 cover letter + answer-book auto + LinkedIn cred + releases

## 2026-04-17 · bf06008 · auto
Merge fix/skill-gaps-order-by-freshness: pin sample to newest 500 jobs

Skill-gaps page stopped silently reporting stale market demand — samples
now reflect the 500 most recently ingested jobs instead of the oldest.

## 2026-04-17 · 9b25f2f · auto
Merge fix/ci-pytest-ignore-live-integration: unblock backend test job

Backend CI test job goes green; added 10 real smoke tests as regression
guards on the SecretStr + log-scrubber leak defenses.

## 2026-04-17 · dc71fc0 · auto
Merge: ANTHROPIC_API_KEY leak defense (SecretStr + log scrubber + hook)

Three-layer protection so the Anthropic key can never reach logs,
commit messages, or stringified settings dumps.

## 2026-04-17 · 8d3d097 · auto
Merge fix/f228-applications-submission-source-filter

`GET /applications` now honours `?submission_source=…`; new "Source"
dropdown on the Applications page.

## 2026-04-17 · aecb3ca · auto
Merge deploy.yml: pipe ANTHROPIC_API_KEY to ci-deploy.sh via stdin

Rotating the Anthropic key is now a GH Secret update + re-run —
no SSH-and-edit on the VM.

## 2026-04-17 · c45ec13 · auto
Merge fix/ci-migration-ai-log-fk: unblock CI + deploy

Alembic upgrade no longer fails on a fresh DB (FK to the un-migrated
ai_customization_logs table dropped, UUID type aligned with repo
convention).

## 2026-04-17 · 89966cc · auto
Merge feat/manual-link-review-priority-applied

Three sales-workflow features shipped together:

* **Submit job link** — paste an ATS URL, server fetches + scores the
  posting through the same pipeline the scanners use.
* **Review queue prioritization** — today / yesterday / older date
  buckets + team-wide best resume fit ordering.
* **Applied action** — marks a job submitted with an immutable snapshot
  of the resume text and score used at submit time.

<!-- Earlier releases are tracked in docs/releases/ as per-round writeups -->
<!-- RELEASES_LOG_END -->
