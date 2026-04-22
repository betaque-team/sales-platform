"""Claude Routine Apply — orchestration endpoints.

This router is the control-plane for the MCP-Chrome routine that
automates job applications. The routine (a Claude-driven browser
session) polls these endpoints to know:

  * Which jobs to target next                  (top-to-apply)
  * Whether the operator has killed the run    (kill-switch)
  * How to record a run's progress             (runs CRUD)
  * How to de-fingerprint generated text       (humanize helper)

Everything here is *operator-scoped* — a query returns only data
owned by the caller. There are no admin-override endpoints; the
routine runs as the user, and the user sees only their own runs.

Pre-flight gating
-----------------
``POST /routine/runs`` is the single choke-point that decides
whether a run is allowed to start. It verifies:

  1. Kill-switch is OFF.
  2. Required answer-book coverage is 100% complete.
  3. Global daily cap (10 apps / 24h rolling) not hit.

The routine is expected to re-check these between applications too,
because a long run can race against a user toggling the kill-switch.
``GET /routine/top-to-apply`` returns the current state of all three
in its response envelope so a single poll is enough.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.answer_book import AnswerBookEntry
from app.models.application import Application
from app.models.application_submission import ApplicationSubmission
from app.models.company import Company
from app.models.humanization_corpus import HumanizationCorpus
from app.models.job import Job
from app.models.role_config import RoleClusterConfig
from app.models.routine_kill_switch import RoutineKillSwitch
from app.models.routine_run import RoutineRun, ROUTINE_STATUSES
from app.models.user import User
from app.schemas.routine import (
    CreateRoutineRunRequest,
    CreateRoutineRunResponse,
    HumanizeRequest,
    HumanizeResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    RoutineRunDetail,
    RoutineRunOut,
    SubmissionDetail,
    TopToApplyJob,
    TopToApplyResponse,
    UpdateRoutineRunRequest,
)
from app.services.answer_book_seed import REQUIRED_ENTRIES
from app.services.humanizer import humanize as humanize_text
from app.utils.audit import log_action

router = APIRouter(prefix="/routine", tags=["routine"])


# ═══════════════════════════════════════════════════════════════════
# Tunables — kept at module scope so tests can monkeypatch and the
# operator can see the constants without grep-diving. Values agreed
# during v6 planning.
# ═══════════════════════════════════════════════════════════════════

# Global cap on submitted applications per rolling 24h. The routine
# refuses to submit above this; top-to-apply reports the remaining.
DAILY_CAP = 10

# Per-company cooldown: once a user applies to a job at a company,
# we suppress every other job from the same company from top-to-apply
# for this many days. Prevents shotgun-blasting a single employer.
COMPANY_COOLDOWN_DAYS = 30

# Platforms excluded outright from the routine. LinkedIn has its own
# Easy Apply pipeline and anti-bot measures that make MCP-Chrome
# automation a detection nightmare; ship without it for v6.
EXCLUDED_PLATFORMS: frozenset[str] = frozenset({"linkedin"})

# Geography buckets the routine supports. "" (unclassified) is
# excluded because the salary-minimum lookup needs a bucket to pick.
ROUTINE_GEOGRAPHY_BUCKETS: tuple[str, ...] = ("global_remote", "usa_only", "uae_only")

# Minimum humanization_corpus rows required before style-match
# kicks in. Mirrored from the humanizer module so the router and
# the helper stay in sync.
STYLE_MATCH_MIN_CORPUS_SIZE = 10


# ═══════════════════════════════════════════════════════════════════
# Helpers — shared between top-to-apply and create-run
# ═══════════════════════════════════════════════════════════════════


async def _get_relevant_clusters(db: AsyncSession) -> list[str]:
    """Duplicate of the helper in companies.py / jobs.py.

    Intentionally copy-pasted rather than imported to keep this router
    decoupled from other v1 modules — if companies.py moves or the
    helper signature changes, the routine still works.
    """
    result = await db.execute(
        select(RoleClusterConfig.name).where(
            RoleClusterConfig.is_relevant == True,  # noqa: E712
            RoleClusterConfig.is_active == True,  # noqa: E712
        )
    )
    clusters = result.scalars().all()
    return list(clusters) if clusters else ["infra", "security"]


async def _count_recent_submissions(db: AsyncSession, user_id: UUID, hours: int = 24) -> int:
    """Count applications the user submitted in the last ``hours`` window.

    Source of truth is ``Application.applied_at`` because that's when
    the submit actually happened — ``created_at`` can be days older
    for rows that sat in the "prepared" state. Dry-run submissions
    don't flip ``status="applied"`` so they're naturally excluded.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(func.count(Application.id)).where(
            Application.user_id == user_id,
            Application.status == "applied",
            Application.applied_at >= cutoff,
        )
    )
    return int(result.scalar() or 0)


async def _required_coverage_complete(db: AsyncSession, user_id: UUID) -> bool:
    """Return True iff every required answer-book entry is filled.

    Pre-flight gate for both top-to-apply (advisory flag) and
    create-run (hard rejection). Keyed on ``is_locked=True`` +
    non-empty answer; cheaper than re-validating the full seed list
    on every call because the lock flag is the server-side truth.
    """
    required_keys = [qkey for (_cat, qkey, _q) in REQUIRED_ENTRIES]
    if not required_keys:
        return True

    # Count filled rows among the required set. A row is "filled"
    # when the answer trims to non-empty — same rule as
    # RequiredCoverageResponse.
    result = await db.execute(
        select(func.count(AnswerBookEntry.id)).where(
            AnswerBookEntry.user_id == user_id,
            AnswerBookEntry.is_locked == True,  # noqa: E712
            AnswerBookEntry.source == "manual_required",
            AnswerBookEntry.question_key.in_(required_keys),
            func.length(func.trim(AnswerBookEntry.answer)) > 0,
        )
    )
    filled = int(result.scalar() or 0)
    return filled == len(required_keys)


async def _kill_switch_disabled(db: AsyncSession, user_id: UUID) -> bool:
    """Return True when the user has actively disabled the routine."""
    row = (await db.execute(
        select(RoutineKillSwitch).where(RoutineKillSwitch.user_id == user_id)
    )).scalar_one_or_none()
    return bool(row and row.disabled)


# ═══════════════════════════════════════════════════════════════════
# GET /routine/top-to-apply
# ═══════════════════════════════════════════════════════════════════


@router.get("/top-to-apply", response_model=TopToApplyResponse)
async def top_to_apply(
    limit: int = Query(10, ge=1, le=25),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pick the next N jobs for the routine to target.

    Filters applied (in order):
      * ``Job.platform NOT IN excluded`` (LinkedIn excluded)
      * ``Job.role_cluster IN relevant_clusters`` (infra/security by default)
      * ``Job.geography_bucket IN routine buckets`` (global/usa/uae)
      * ``Job.status NOT IN ('expired', 'archived')``
      * No existing ``Application`` for (user, job)
      * No application to the same ``company_id`` in the last 30 days
      * Ordered by ``relevance_score`` DESC

    Response envelope also carries three pre-flight flags —
    ``kill_switch_active``, ``answer_book_ready``, ``daily_cap_remaining``
    — so the routine can decide "should I even start?" from a single
    poll. The jobs array is returned even when the flags fail; the
    routine is responsible for not calling confirm-submitted in those
    cases.
    """
    relevant_clusters = await _get_relevant_clusters(db)

    # Jobs already in Application (any status) are skipped — the user
    # has already engaged, and we don't want the routine to re-apply
    # to a withdrawn/rejected job. Scope by user_id on purpose.
    applied_jobs_sub = select(Application.job_id).where(
        Application.user_id == user.id
    ).subquery()

    # Companies the user has applied to within the cooldown window.
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(days=COMPANY_COOLDOWN_DAYS)
    cooldown_companies_sub = (
        select(Job.company_id)
        .join(Application, Application.job_id == Job.id)
        .where(
            Application.user_id == user.id,
            Application.applied_at >= cooldown_cutoff,
            Job.company_id.is_not(None),
        )
    ).subquery()

    query = (
        select(Job, Company.name.label("company_name"))
        .join(Company, Company.id == Job.company_id, isouter=True)
        .where(
            Job.platform.notin_(EXCLUDED_PLATFORMS),
            Job.role_cluster.in_(relevant_clusters),
            Job.geography_bucket.in_(ROUTINE_GEOGRAPHY_BUCKETS),
            Job.status.notin_(("expired", "archived")),
            Job.id.notin_(select(applied_jobs_sub.c.job_id)),
            and_(
                Job.company_id.is_not(None),
                Job.company_id.notin_(select(cooldown_companies_sub.c.company_id)),
            ),
        )
        .order_by(Job.relevance_score.desc(), Job.first_seen_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(query)).all()

    # Flags for the response envelope.
    kill_active = await _kill_switch_disabled(db, user.id)
    coverage_ready = await _required_coverage_complete(db, user.id)
    used_today = await _count_recent_submissions(db, user.id, hours=24)
    remaining = max(0, DAILY_CAP - used_today)

    return TopToApplyResponse(
        kill_switch_active=kill_active,
        daily_cap_remaining=remaining,
        answer_book_ready=coverage_ready,
        jobs=[
            TopToApplyJob(
                job_id=job.id,
                title=job.title,
                company_id=job.company_id,
                company_name=company_name or "",
                platform=job.platform,
                relevance_score=float(job.relevance_score or 0.0),
                geography_bucket=job.geography_bucket or None,
                role_cluster=job.role_cluster or None,
            )
            for job, company_name in rows
        ],
    )


# ═══════════════════════════════════════════════════════════════════
# Kill-switch — GET / POST
# ═══════════════════════════════════════════════════════════════════


@router.get("/kill-switch", response_model=KillSwitchResponse)
async def get_kill_switch(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current kill-switch state for the caller.

    Absence of a row == ``disabled=False`` (the default). We don't
    auto-create rows on read to keep the table small — only flips
    to ``disabled=True`` write.
    """
    row = (await db.execute(
        select(RoutineKillSwitch).where(RoutineKillSwitch.user_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        return KillSwitchResponse(disabled=False, disabled_at=None, reason=None)
    return KillSwitchResponse(
        disabled=row.disabled,
        disabled_at=row.disabled_at,
        reason=row.reason,
    )


@router.post("/kill-switch", response_model=KillSwitchResponse)
async def set_kill_switch(
    body: KillSwitchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the kill-switch.

    Writes an audit row on every flip (enabled→disabled and back) so
    an operator can reconstruct "why did the routine stop" from the
    audit log alone. ``reason`` is captured in both the DB row (so
    it survives a toggle-back) and the audit metadata.
    """
    row = (await db.execute(
        select(RoutineKillSwitch).where(RoutineKillSwitch.user_id == user.id)
    )).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = RoutineKillSwitch(
            user_id=user.id,
            disabled=body.disabled,
            disabled_at=now if body.disabled else None,
            reason=body.reason,
        )
        db.add(row)
    else:
        row.disabled = body.disabled
        row.disabled_at = now if body.disabled else None
        row.reason = body.reason

    await db.commit()
    await db.refresh(row)

    await log_action(
        db, user,
        action=("routine.kill_switch_on" if body.disabled else "routine.kill_switch_off"),
        resource="routine_kill_switch",
        request=request,
        metadata={"reason": body.reason},
    )

    return KillSwitchResponse(
        disabled=row.disabled,
        disabled_at=row.disabled_at,
        reason=row.reason,
    )


# ═══════════════════════════════════════════════════════════════════
# Routine runs — CRUD
# ═══════════════════════════════════════════════════════════════════


def _run_to_out(run: RoutineRun) -> RoutineRunOut:
    return RoutineRunOut(
        id=run.id,
        user_id=run.user_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        mode=run.mode,  # type: ignore[arg-type]
        applications_attempted=run.applications_attempted,
        applications_submitted=run.applications_submitted,
        applications_skipped=run.applications_skipped or [],
        detection_incidents=run.detection_incidents or [],
        status=run.status,  # type: ignore[arg-type]
        kill_switch_triggered=run.kill_switch_triggered,
    )


@router.post("/runs", response_model=CreateRoutineRunResponse)
async def create_run(
    body: CreateRoutineRunRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new routine run.

    Hard-rejects with 400 when any pre-flight fails. The routine is
    expected to fix the underlying problem (fill the answer book,
    flip the kill-switch off, wait out the daily cap) and retry —
    it should NOT create a partial run row just to record that the
    attempt was blocked (the audit log carries that).
    """
    if await _kill_switch_disabled(db, user.id):
        raise HTTPException(
            status_code=400,
            detail="Routine is currently disabled by the kill-switch. "
                   "Toggle it off via POST /routine/kill-switch before starting a run.",
        )

    if not await _required_coverage_complete(db, user.id):
        raise HTTPException(
            status_code=400,
            detail="Answer book required-coverage is incomplete. "
                   "Fill all required entries via /answer-book/required-setup.",
        )

    # Daily cap is only a hard block for `live` runs. Dry-runs and
    # single-trial runs don't increment the applied count, so letting
    # them start is safe even when the cap is used.
    if body.mode == "live":
        used_today = await _count_recent_submissions(db, user.id, hours=24)
        if used_today >= DAILY_CAP:
            raise HTTPException(
                status_code=400,
                detail=f"Daily application cap ({DAILY_CAP}/day) already used. "
                       f"Try again in 24h or run in dry_run / single_trial mode.",
            )

    run = RoutineRun(
        id=uuid.uuid4(),
        user_id=user.id,
        mode=body.mode,
        status="running",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    await log_action(
        db, user,
        action="routine.run_created",
        resource="routine_run",
        request=request,
        metadata={
            "run_id": str(run.id),
            "mode": body.mode,
            "target_job_count": len(body.target_job_ids) if body.target_job_ids else 0,
        },
    )

    return CreateRoutineRunResponse(run_id=run.id)


@router.patch("/runs/{run_id}", response_model=RoutineRunOut)
async def update_run(
    run_id: UUID,
    body: UpdateRoutineRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Incremental update of a run's counters / status.

    The routine PATCHes this between applications with partial bodies
    — e.g. ``{"applications_attempted": 3}`` after a skip, or
    ``{"status": "complete", "ended_at": <now>}`` at the end.

    Non-terminal → terminal status transitions auto-stamp ``ended_at``
    if the caller forgets to send it.
    """
    run = (await db.execute(
        select(RoutineRun).where(
            RoutineRun.id == run_id,
            RoutineRun.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Routine run not found")

    # Reject writes on a terminal run — once it's complete/aborted,
    # the counters are frozen. Silent accept would hide routine bugs.
    if run.status in ("complete", "aborted") and body.status is None:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in terminal status '{run.status}' and cannot be updated.",
        )

    patch = body.model_dump(exclude_unset=True)

    if "applications_attempted" in patch and patch["applications_attempted"] is not None:
        run.applications_attempted = patch["applications_attempted"]
    if "applications_submitted" in patch and patch["applications_submitted"] is not None:
        run.applications_submitted = patch["applications_submitted"]
    if "applications_skipped" in patch and patch["applications_skipped"] is not None:
        run.applications_skipped = patch["applications_skipped"]
    if "detection_incidents" in patch and patch["detection_incidents"] is not None:
        run.detection_incidents = patch["detection_incidents"]
    if "kill_switch_triggered" in patch and patch["kill_switch_triggered"] is not None:
        run.kill_switch_triggered = patch["kill_switch_triggered"]
    if "status" in patch and patch["status"] is not None:
        if patch["status"] not in ROUTINE_STATUSES:
            # Belt-and-suspenders — the Literal should already have
            # rejected this at parse time.
            raise HTTPException(status_code=400, detail="Invalid status value")
        run.status = patch["status"]
        if patch["status"] in ("complete", "aborted") and run.ended_at is None:
            run.ended_at = datetime.now(timezone.utc)
    if "ended_at" in patch and patch["ended_at"] is not None:
        run.ended_at = patch["ended_at"]

    db.add(run)
    await db.commit()
    await db.refresh(run)

    return _run_to_out(run)


@router.get("/runs/{run_id}", response_model=RoutineRunDetail)
async def get_run(
    run_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run detail + every submission recorded during the run.

    Submissions are hydrated from ``application_submissions`` via
    ``routine_run_id`` (SET NULL on run-delete, but we don't delete
    runs so the link is stable). Ordered by submission creation time
    so the UI can render "first app submitted at T=0, last at T=18m".
    """
    run = (await db.execute(
        select(RoutineRun).where(
            RoutineRun.id == run_id,
            RoutineRun.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Routine run not found")

    submissions = (await db.execute(
        select(ApplicationSubmission)
        .where(ApplicationSubmission.routine_run_id == run_id)
        .order_by(ApplicationSubmission.created_at.asc())
    )).scalars().all()

    submission_details = [
        SubmissionDetail(
            id=s.id,
            application_id=s.application_id,
            routine_run_id=s.routine_run_id,
            submitted_at=s.submitted_at,
            job_url=s.job_url,
            ats_platform=s.ats_platform,
            form_fingerprint_hash=s.form_fingerprint_hash,
            payload_json=s.payload_json or {},
            answers_json=s.answers_json or [],
            resume_version_hash=s.resume_version_hash,
            cover_letter_text=s.cover_letter_text,
            screenshot_keys=s.screenshot_keys or [],
            confirmation_text=s.confirmation_text,
            detected_issues=s.detected_issues or [],
            profile_snapshot=s.profile_snapshot or {},
            created_at=s.created_at,
        )
        for s in submissions
    ]

    base = _run_to_out(run)
    return RoutineRunDetail(
        **base.model_dump(),
        submissions=submission_details,
    )


@router.get("/runs", response_model=list[RoutineRunOut])
async def list_runs(
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most-recent runs first. Simple list — pagination would be
    overkill given the expected volume (a heavy user maybe has 1
    run/day, so 100 rows is ~3 months of history)."""
    rows = (await db.execute(
        select(RoutineRun)
        .where(RoutineRun.user_id == user.id)
        .order_by(RoutineRun.started_at.desc())
        .limit(limit)
    )).scalars().all()
    return [_run_to_out(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════
# Humanize helper
# ═══════════════════════════════════════════════════════════════════


@router.post("/humanize", response_model=HumanizeResponse)
async def humanize(
    body: HumanizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run text through the humanizer pipeline.

    The routine calls this on every LLM-generated cover letter and
    every generated answer right before it types the text into the
    form. We load the caller's ``humanization_corpus`` rows and pass
    them as few-shot examples so the style-match pass has user-voice
    data to work from.

    Corpus loading rules (kept here, not in the humanizer module, so
    the module stays DB-free and unit-testable):

      * Only rows with ``edit_distance > 10`` — small edits are
        noise; we want examples where the user meaningfully rewrote.
      * Most recent 100 rows (``accepted_at`` DESC) — the user's
        voice drifts; stale corpus can over-fit to old phrasing.
      * Scoped to ``promoted_to_answer_book = False`` — promoted
        rows are already in the answer book; reusing them as
        style-match examples risks the model regenerating an
        answer we could have just read from the book.

    When the corpus is below the style-match threshold, the pass
    no-ops (see ``humanizer.style_match_pass``) — that's fine; the
    other 7 passes still run.
    """
    corpus_rows = (await db.execute(
        select(HumanizationCorpus)
        .where(
            HumanizationCorpus.user_id == user.id,
            HumanizationCorpus.edit_distance > 10,
            HumanizationCorpus.promoted_to_answer_book == False,  # noqa: E712
        )
        .order_by(HumanizationCorpus.accepted_at.desc())
        .limit(100)
    )).scalars().all()

    examples: list[tuple[str, str]] = [
        (r.draft_text, r.final_text) for r in corpus_rows
    ]

    result = humanize_text(body.text, corpus_examples=examples or None)

    return HumanizeResponse(
        text=result.text,
        passes_applied=result.passes_applied,
        burstiness_sigma=result.burstiness_sigma,
        banned_phrase_hits=result.banned_phrase_hits,
        style_match_examples_used=result.style_match_examples_used,
    )
