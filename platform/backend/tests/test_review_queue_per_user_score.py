"""F248 — review queue must rank by the current reviewer's resume,
NOT the team-wide max across every resume.

User-reported bug (2026-04-26):
  Sarthak's review queue (DevOps/SRE/Cloud resume) was showing
  Data Engineering / Automation Engineering roles at the top with
  very high "best resume fit" scores. Pre-fix the secondary sort
  used ``MAX(ResumeScore.overall_score)`` aggregated across EVERY
  resume on the platform — so a teammate's data-engineer resume
  scoring 90 against a data-engineering job surfaced that job to
  Sarthak's queue, ahead of his own DevOps fits.

Post-fix the subquery filters ``ResumeScore.resume_id ==
user.active_resume_id`` so only the reviewer's own resume drives
the ordering.

This test pins the source-level guard. End-to-end coverage of the
ranking would need a live DB fixture with two users + two resumes
+ two cluster-disjoint jobs (one each scored), which is bigger
than the current test harness supports. Source inspection catches
the regression-class — anyone re-introducing ``func.max(...)`` or
group_by on ResumeScore in this handler will fail CI.
"""
from __future__ import annotations

import os


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault(
    "DATABASE_URL_SYNC",
    "postgresql://placeholder:placeholder@localhost:5432/placeholder",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "pytest-review-queue")


def test_review_queue_subquery_filters_by_active_resume():
    """The ResumeScore subquery in /jobs/review-queue MUST filter on
    ``ResumeScore.resume_id == user.active_resume_id`` and MUST NOT
    aggregate across every resume.

    Two independent guards:
      (1) the source contains the per-user filter expression — exact
          shape may evolve, but the constants ``resume_id ==
          user.active_resume_id`` are the regression sentinel.
      (2) the source does NOT contain ``func.max(ResumeScore`` in
          the handler — that was the team-wide broken form. A
          ``GROUP BY`` on ResumeScore in this handler is also a
          smell that points at the same regression class.
    """
    import inspect

    from app.api.v1 import jobs as jobs_module

    src = inspect.getsource(jobs_module.review_queue)

    # (1) Per-user filter present.
    assert "user.active_resume_id" in src, (
        "review_queue no longer filters the resume-score subquery on "
        "user.active_resume_id. Without that filter, the subquery "
        "spans every resume on the platform and the secondary sort "
        "ranks by team-wide max — surfacing wrong-role jobs to the "
        "wrong reviewer (F248 regression)."
    )
    assert "ResumeScore.resume_id" in src, (
        "review_queue references neither ResumeScore.resume_id nor an "
        "equivalent per-resume filter. Per-user scoping must be "
        "expressed at the resume level (one reviewer can have many "
        "resumes; only the active one drives the queue ranking)."
    )

    # (2) Team-wide aggregations forbidden in this handler.
    assert "func.max(ResumeScore" not in src, (
        "review_queue uses ``func.max(ResumeScore...)`` — that's the "
        "F248 pre-fix shape. Aggregating across every resume defeats "
        "the per-reviewer ordering. Use a per-resume filter instead."
    )
    assert "group_by(ResumeScore" not in src, (
        "review_queue groups on ResumeScore — that pattern almost "
        "always indicates a team-wide aggregation (F248 regression "
        "class). If grouping is genuinely needed, add a comment "
        "explaining why and mark this assertion explicitly."
    )


def test_review_queue_response_includes_your_resume_score_key():
    """The handler must populate ``your_resume_score`` in each item
    (the canonical post-F248 field) AND ``max_resume_score`` for
    backward-compat with cached/older clients.
    """
    import inspect

    from app.api.v1 import jobs as jobs_module

    src = inspect.getsource(jobs_module.review_queue)

    assert '"your_resume_score"' in src, (
        "response items missing ``your_resume_score`` key — the "
        "frontend reads this to render the 'Your resume fit' bar. "
        "Pre-F248 only ``max_resume_score`` existed."
    )
    assert '"max_resume_score"' in src, (
        "response items missing ``max_resume_score`` backward-compat "
        "key. Older frontend bundles still read this name; dropping it "
        "would blank the resume-fit bar for any tab opened before the "
        "F248 deploy until the user hard-refreshes."
    )
