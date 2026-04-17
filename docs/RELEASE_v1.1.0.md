# 🚀 Sales Platform v1.1.0 — AI Capability Release

**Released:** 2026-04-17
**Live at:** https://salesplatform.reventlabs.com

Hey team,

We just shipped a meaningful upgrade to the platform — five rounds of
AI features anchored on getting our Anthropic API key plumbed through
the deploy pipeline correctly. Cover letter generation, interview
prep, resume customization, and a brand-new Insights page are all
live now.

This release also adds the foundation for **AI-driven product
improvement** (insights generated twice a week analyze platform
behavior and suggest fixes) and **training-data capture** (every
review and AI generation gets logged in a clean format we can use to
train custom models in the future).

---

## What's new for everyone

### 🪄 AI Cover Letters (live now)

Open any job's detail page → **AI Tools** panel → **Cover Letter** →
pick a tone (Professional / Enthusiastic / Technical / Conversational)
→ click Generate.

You get a personalized 250-350 word cover letter that:

- **Only references claims actually in your resume** — the AI is
  explicitly forbidden from making up experience to match the JD
- Uses the job description to choose which of your real achievements
  to lead with
- Reads like a human wrote it — no em-dashes (—), no "leverage", no
  "passionate self-starter", no AI-tell phrases
- Comes with 2-3 key selling points + customization notes

**Limit: 30 generations per day per user.** Resets at midnight UTC.
You'll see "X/30 left" inline next to the button.

📖 Full details: [`docs/AI_USAGE.md`](./AI_USAGE.md)

### 🎤 AI Interview Prep (live now)

Same panel → **Interview Prep** → click. Get a per-job study guide:

- Likely interview questions categorized (technical, behavioral, etc.)
  with suggested answers grounded in your resume
- Talking points to bring up proactively
- Company research items to brush up on before the call
- Red flags to ask about (compensation gaps, vague title language, etc.)

**Limit: 10 generations per day per user.**

### 📝 AI Resume Customize (existing, now part of the family)

`/resume-score` page → click any job → **AI Customize**. Same as
before but now the usage badge tells you "X/10 left today" inline.

**Limit: 10 generations per day per user.**

### 💡 Insights Page (NEW — live now)

New sidebar entry: **Insights**. Twice a week (Mon + Thu at 04:00 UTC)
the platform analyzes your last 30 days of activity and produces 4-6
personalized observations like:

- "Your acceptance rate is 60% on infra vs 25% on security, narrow
  your filter to focus where you're winning."
- "Add Terraform to your resume — it appears in 78% of jobs you've
  accepted but only 30% of your scored jobs match it."
- "You reject 80% of jobs at companies under 50 employees. Consider
  using the company-size filter."

If you've reviewed at least one job in the last 30 days and have an
active resume, you'll see insights starting Monday morning UTC. New
accounts see a friendly "Insights will appear after the next run"
message.

📖 Full details: [`docs/AI_INSIGHTS.md`](./AI_INSIGHTS.md)

---

## What's new for admins

### 🛡 Product Insights Queue

The same Insights page has an admin-only section showing
**platform-improvement suggestions** the AI generates each Mon + Thu:

- "Add 'company size' to JobsPage filter, 34% of rejection reasons
  cite size with no current filter axis."
- "Cribl, Datadog, and HashiCorp keep getting accepted but none are
  in is_target=true — auto-promote candidates."
- "The 'remote_scope' filter is applied then cleared in 80% of
  sessions, UX is unclear."

You can **Action** (= we shipped a fix), **Dismiss** (= won't act),
or **mark Duplicate** with optional notes. The notes feed into the
next AI run as context, so it can score whether the actioned fixes
moved the metric and stop re-suggesting dismissed items. **It's a
real flywheel — your triage decisions actively improve the next run.**

There's also a **"Run now"** button if you've just shipped a fix and
want to see if the AI notices the metric move.

### 📊 Training Data Capture (NEW — admin only)

Open `/monitoring` → scroll to **"Training data capture"** tile.

Every review event, every AI generation, and every job classification
now lands in a `training_examples` table as a clean `(input, label)`
row. You can:

- See per-task counts + class balance at a glance
- **Export as JSONL** per task type (50K rows per call, audit-logged)
- **Backfill `role_classify`** from existing 13K jobs in one click

This is the foundation for training custom models down the road —
resume-job match scoring, role classification, cover-letter quality.
**Privacy: emails / phones / personal URLs / resume-header names are
all scrubbed before persistence; user IDs are SHA-256 hashed.** You
can ship the JSONL to a model trainer without a privacy review.

📖 Full details: [`docs/TRAINING_DATA.md`](./TRAINING_DATA.md)

### 🔐 The deploy pipeline is now bulletproof for the AI key

The `ANTHROPIC_API_KEY` GitHub Secret now actually reaches the running
container — and the deploy verify step asserts it post-deploy and
fails the run loudly if the key is set but the backend doesn't see it.
No more "I set the Secret but features are still dead" silent
half-rollouts.

📖 Full details: [`docs/DEPLOY_SETUP.md`](./DEPLOY_SETUP.md) (F234
section in Day-2 maintenance)

---

## Quick reference

| Feature | Where | Daily limit | Reset |
|---|---|---|---|
| AI Cover Letter | Job detail → AI Tools | **30/day** | midnight UTC |
| AI Interview Prep | Job detail → AI Tools | **10/day** | midnight UTC |
| AI Resume Customize | Resume Score → job row | **10/day** | midnight UTC |
| Insights | Sidebar → Insights | auto-generated | Mon + Thu 04:00 UTC |
| Training Data Export | Monitoring (admin) | unlimited | n/a |

---

## Docs index

- 📖 [`docs/AI_USAGE.md`](./AI_USAGE.md) — All three AI generation
  features: limits, reset cadence, what happens at the cap, cost
  breakdown, env-var overrides, the `/api/v1/ai/usage` API.

- 📖 [`docs/AI_INSIGHTS.md`](./AI_INSIGHTS.md) — How the twice-weekly
  insight generator works, what data it sees, the schema, how to tune
  the prompts, the action-flywheel design, failure-mode debugging.

- 📖 [`docs/TRAINING_DATA.md`](./TRAINING_DATA.md) — Training-data
  pipeline: what gets captured, the privacy scrub model, the JSONL
  export API with curl + jq examples, how to add a new task type, the
  path to training the first custom model.

- 📖 [`docs/DEPLOY_SETUP.md`](./DEPLOY_SETUP.md) — VM operations
  including the F234 `ANTHROPIC_API_KEY` plumbing requirement.

---

## Costs

For transparency:

- **User-facing AI features** (cover letter / interview prep /
  customize): ceiling at 50 daily-active users hitting every cap is
  ~$2.50/user/day = ~$3,750/month worst case. Realistic usage at
  ~30% of caps consumed: ~$1,125/month.
- **Insights cron**: ~$8.30/month at 50 users (negligible).

If usage trends require lifting any of the per-user limits, the
config is environment-variable-overridable on the VM — no code
change needed.

---

## How to give feedback

If anything's broken / surprising / annoying:

1. The **Feedback** sidebar entry — file an in-app ticket. Admin
   triage queue is on the Feedback page.
2. For AI quality issues specifically (e.g. "cover letter mentioned
   experience I don't have", "interview prep missed obvious questions
   for this role"): include the job URL + which feature so we can
   reproduce. The `training_examples` table captures the exact prompt
   inputs so we can replay locally.

---

## What's next (preview)

- **Round 70+**: post-action label bumps for AI-quality task types
  (currently every cover letter is logged with label `generated`; UI
  events will bump to `kept` / `regenerated` / `applied` so the
  training data becomes proper quality signal).
- **Search-intent capture** so the model can learn "what filter
  combinations precede an apply".
- **First model training experiment** off the captured `resume_match`
  corpus once we have ~10K rows with reasonable class balance.

—

Questions? Drop them in #sales-platform or reply to this thread.

— Engineering
