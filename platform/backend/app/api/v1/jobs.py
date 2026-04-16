"""Job listing API endpoints."""

from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy import select, func, or_, literal, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.job import Job, JobDescription
from app.models.company import Company
from app.models.user import User
from app.models.resume import ResumeScore
from app.models.role_config import RoleClusterConfig
from app.api.deps import get_current_user, require_role
from app.schemas.job import (
    JobOut, JobDescriptionOut, JobStatusUpdate, BulkActionRequest,
    JobStatusFilter, GeographyBucketFilter, PlatformFilter,
)
from app.utils.audit import log_action
from app.utils.sanitize import sanitize_html
from app.utils.sql import escape_like


async def _get_relevant_clusters(db: AsyncSession) -> list[str]:
    """Get the list of role cluster names that are marked as relevant."""
    result = await db.execute(
        select(RoleClusterConfig.name).where(
            RoleClusterConfig.is_relevant == True,
            RoleClusterConfig.is_active == True,
        )
    )
    clusters = result.scalars().all()
    # Fallback to hardcoded if no config exists yet
    return list(clusters) if clusters else ["infra", "security"]


async def _get_all_cluster_names(db: AsyncSession) -> list[str]:
    """Return every configured cluster name (active or not) for F218 filter
    validation.

    Mirrors the helper in export.py (F187). Clusters are admin-configurable
    via `RoleClusterConfig`, so we can't hard-code a `Literal` — we load
    the catalog at request time and reject unknown names with a 400 before
    they reach the SQL filter. The "relevant" pseudo-value is a UI alias
    for "all clusters marked relevant" and must be allow-listed explicitly
    (see F106 and the branching in `list_jobs` below).
    """
    result = await db.execute(select(RoleClusterConfig.name))
    return list(result.scalars().all())

router = APIRouter(prefix="/jobs", tags=["jobs"])


# Regression finding 198: `sort_by` was typed `str` and resolved via
# `getattr(Job, sort_by, None)` with a fallback to `first_seen_at`. But
# `getattr` happily returns relationships (`Job.reviews` → InstrumentedList
# proxy), JSON columns (`Job.raw_json` → "could not identify an equality
# operator" on ORDER BY), and private attrs (`_sa_instance_state` →
# CompileError). All three bubbled back as HTTP 500 "Internal Server
# Error" with a stack trace the frontend couldn't distinguish from a
# real crash.
#
# Fix: Literal-typed param so FastAPI 422s the bad sort at parse time,
# and a hand-maintained map to actual columns (no `getattr`) so we
# never accidentally orderable-ize something that isn't. `company_name`
# and `resume_score` stay keys because they drive the special JOIN
# branches below, but they don't appear in the column map — the if-chain
# consumes them before the map lookup.
_JOB_SORT_COLUMNS = {
    "first_seen_at":   Job.first_seen_at,
    "last_seen_at":    Job.last_seen_at,
    "relevance_score": Job.relevance_score,
    "posted_at":       Job.posted_at,
    "title":           Job.title,
    "status":          Job.status,
    # `platform` was advertised in the JobsPage sort dropdown but never
    # made it into the column map — picking "Platform A-Z" 422'd via
    # the F198 Literal guard (latent bug since F198 shipped). Adding
    # the column here + the matching Literal entry below + the
    # `_ALLOWED_SORT_KEYS` member makes the dropdown option work and
    # also unlocks `platform` as a multi-sort tiebreaker (e.g. group
    # infra jobs by platform with relevance as secondary).
    "platform":        Job.platform,
}

JobSortBy = Literal[
    "first_seen_at",
    "last_seen_at",
    "relevance_score",
    "posted_at",
    "title",
    "company_name",
    "resume_score",
    "status",
    "platform",
]
JobSortDir = Literal["asc", "desc"]

# Single source of truth for allowed sort keys — used by the multi-sort
# parser below. `JobSortBy` Literal stays for API-surface documentation
# and for the legacy single-sort path; the parser validates against this
# set directly because a runtime `sort_by` like
# `relevance_score:desc,first_seen_at:desc` is a single `str` arg and
# the per-segment keys aren't individually Literal-typeable at the
# signature.
_ALLOWED_SORT_KEYS = frozenset({
    "first_seen_at", "last_seen_at", "relevance_score",
    "posted_at", "title", "company_name", "resume_score", "status",
    "platform",
})


def _parse_sort_spec(sort_by: str, fallback_dir: str) -> list[tuple[str, str]]:
    """Parse a sort spec into a list of ``(key, dir)`` tuples.

    Accepts two forms:

    - **Legacy single-sort** — `sort_by="relevance_score"` (+ the separate
      `sort_dir` query param). Returns ``[(key, fallback_dir)]``.
    - **Multi-sort** — `sort_by="relevance_score:desc,first_seen_at:desc"`.
      The per-segment direction overrides `fallback_dir`. Segments
      without a `:` inherit `fallback_dir`.

    Raises ``HTTPException(422)`` on any unknown key or direction so
    callers get the same parse-time rejection as the Literal-typed
    single-sort path (F198). Deduplicates keys in-place — the first
    occurrence wins — so a shift-click chain that accidentally repeats
    a key still produces valid SQL.
    """
    segments = [s.strip() for s in sort_by.split(",") if s.strip()]
    if not segments:
        return [("first_seen_at", fallback_dir)]
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for seg in segments:
        if ":" in seg:
            key, _, direction = seg.partition(":")
            key = key.strip()
            direction = direction.strip().lower() or fallback_dir
        else:
            key = seg
            direction = fallback_dir
        if key not in _ALLOWED_SORT_KEYS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid sort_by key '{key}'. Must be one of: "
                    + ", ".join(sorted(_ALLOWED_SORT_KEYS))
                ),
            )
        if direction not in ("asc", "desc"):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid sort direction '{direction}' for '{key}'. Must be 'asc' or 'desc'.",
            )
        if key in seen:
            # User shift-clicked the same column twice — keep the first
            # (earlier in the chain = higher priority). Silently drop
            # the dupe instead of 422ing, since it's a UI artifact not
            # a wire-protocol violation.
            continue
        seen.add(key)
        parsed.append((key, direction))
    return parsed


@router.get("")
async def list_jobs(
    # Regression finding 218: these four filter params were previously typed
    # `str | None` with no validation — any typo (status=Accepted with a
    # capital A, geography_bucket=global-remote with a dash, role_cluster=
    # infraa) silently filtered to `total: 0` and the user saw "no matches"
    # for what looked like a valid filter. F187 shipped the same fix on the
    # parallel `/export/jobs` handler; this is the matching fix for the list
    # endpoint. `sort_by` was already Literal-typed per F198.
    #
    # Why Literal for status/geography but runtime validation for
    # role_cluster: status values are frozen in the code (models/job.py:33
    # documents them), so Literal gives us parse-time 422s for free.
    # `geography_bucket` is similarly frozen (models/job.py:25). But role
    # clusters are admin-configurable via RoleClusterConfig — a `Literal`
    # here would become stale the moment an admin adds a cluster — so we
    # load the catalog at request time and 400 on miss. Same split as the
    # export handler.
    status: JobStatusFilter | None = None,
    platform: PlatformFilter | None = None,
    source_platform: PlatformFilter | None = None,
    company_id: UUID | None = None,
    company: str | None = None,
    geography_bucket: GeographyBucketFilter | None = None,
    geography: GeographyBucketFilter | None = None,
    role_cluster: str | None = None,
    is_classified: bool | None = None,
    search: str | None = None,
    q: str | None = None,
    # F198: Literal-typed → FastAPI 422s unknown sort keys at parse
    # time instead of 500-ing from the `getattr` path below.
    #
    # Multi-sort extension (Apr 2026): when `sort_by` contains a `,` or
    # `:` it is parsed as a comma-separated list of `key:dir` pairs,
    # e.g. `relevance_score:desc,first_seen_at:desc`. The per-segment
    # direction overrides `sort_dir`. Each key is validated against
    # `_ALLOWED_SORT_KEYS` at request time (FastAPI's Literal can't
    # validate the inside of a comma-separated string, so we parse
    # ourselves and 422 with a key list on miss). The legacy single
    # `sort_by=relevance_score` + `sort_dir=desc` form remains the
    # default and works unchanged for callers that pre-date multi-sort.
    sort_by: str = "first_seen_at",
    sort_dir: JobSortDir = "desc",
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    page_size: int | None = Query(None, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Accept page_size as alias for per_page (frontend sends page_size)
    if page_size is not None:
        per_page = page_size

    # Regression finding 33: the response schema aliases `Job.platform` as
    # `source_platform` and field-level aliases for `search` (`q`) and
    # `company_id` (`company`) are expected by callers who are reading the
    # response field names and assuming the query params match. Accept the
    # aliases here as a non-breaking alternative to the original param
    # names — callers who were passing the original names still work.
    effective_platform = platform or source_platform
    effective_search = search or q

    query = select(Job).options(joinedload(Job.company))

    if status:
        query = query.where(Job.status == status)
    if effective_platform:
        query = query.where(Job.platform == effective_platform)
    if company_id:
        query = query.where(Job.company_id == company_id)
    if company and company.strip():
        # `company=` is a name-substring filter (the id-based filter lives on
        # `company_id`). Matches the same ilike pattern used for the combined
        # `search` box so the two behave consistently. Findings 84+85:
        # escape LIKE metachars and strip whitespace-only input so `"100%"`
        # / `"dev_ops"` / `"   "` don't degenerate into wildcard matches.
        needle = f"%{escape_like(company.strip())}%"
        query = query.where(Job.company.has(Company.name.ilike(needle, escape="\\")))
    geo = geography_bucket or geography
    if geo:
        query = query.where(Job.geography_bucket == geo)
    if role_cluster:
        # F218: validate role_cluster against the configured cluster catalog
        # before filtering. Clusters are admin-configurable, so we load the
        # allowed set from the DB instead of hard-coding a Literal. The
        # "relevant" pseudo-value is a UI alias for "all clusters marked
        # relevant" (F106) and must be allow-listed explicitly. Before this
        # check, role_cluster=infraa silently returned total=0; now it 400s
        # with the catalog in the detail so the caller can self-correct.
        allowed_clusters = set(await _get_all_cluster_names(db)) | {"relevant"}
        if role_cluster not in allowed_clusters:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid role_cluster. Must be one of: "
                    + ", ".join(sorted(allowed_clusters))
                ),
            )
        if role_cluster == "relevant":
            relevant_clusters = await _get_relevant_clusters(db)
            query = query.where(Job.role_cluster.in_(relevant_clusters))
        else:
            query = query.where(Job.role_cluster == role_cluster)

    # Regression finding 87: let callers filter the (huge — ~90% of rows)
    # unclassified pool without hand-crafting `role_cluster=` URLs that
    # some clients strip as empty. `is_classified=false` → the row has
    # NULL or "" cluster; `is_classified=true` → anything else. We
    # check both NULL and "" because historical rows use the empty
    # string while newer inserts may leave it NULL. Combining this with
    # `role_cluster=foo` is contradictory-but-valid SQL (returns 0) —
    # we don't reject it; the frontend just shouldn't send both.
    if is_classified is True:
        query = query.where(
            Job.role_cluster.is_not(None),
            Job.role_cluster != "",
        )
    elif is_classified is False:
        query = query.where(
            or_(Job.role_cluster.is_(None), Job.role_cluster == "")
        )

    if effective_search and effective_search.strip():
        # Search across title, company name, and location. Findings 84+85:
        # strip whitespace-only input and escape LIKE metachars — a search
        # for `"100%"` must not match every row, and a 3-space input must
        # not wildcard-match random titles with triple spaces.
        needle = f"%{escape_like(effective_search.strip())}%"
        query = query.where(
            or_(
                Job.title.ilike(needle, escape="\\"),
                Job.company.has(Company.name.ilike(needle, escape="\\")),
                Job.location_raw.ilike(needle, escape="\\"),
            )
        )

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Parse multi-sort spec (single-sort is just a 1-element chain).
    # `_parse_sort_spec` validates each key + direction and 422s on miss.
    sort_chain = _parse_sort_spec(sort_by, sort_dir)

    # Resolve each (key, dir) into an SQLAlchemy ORDER BY expression,
    # joining once per dependent table. The original logic only had to
    # consider one `sort_by` value at a time; with multi-sort we may
    # need joins for both `resume_score` and `company_name` in the
    # same query, so we track which joins are already attached and
    # apply each at most once.
    joined_company = False
    joined_resume_scores = False
    order_clauses = []
    for key, direction in sort_chain:
        if key == "resume_score" and user.active_resume_id:
            if not joined_resume_scores:
                query = query.outerjoin(
                    ResumeScore,
                    (ResumeScore.job_id == Job.id)
                    & (ResumeScore.resume_id == user.active_resume_id),
                )
                joined_resume_scores = True
            score_col = func.coalesce(ResumeScore.overall_score, 0)
            order_clauses.append(score_col.desc() if direction == "desc" else score_col.asc())
        elif key == "resume_score":
            # No active resume — silently drop this sort key rather than
            # 422-ing, so a user removing their active resume doesn't
            # break their saved sort chain. Skipping degrades gracefully
            # to whatever other sort keys they had.
            continue
        elif key == "company_name":
            if not joined_company:
                query = query.join(Company, Job.company_id == Company.id)
                joined_company = True
            order_clauses.append(Company.name.desc() if direction == "desc" else Company.name.asc())
        else:
            # F198: hard-mapped lookup. Validation above guarantees the
            # key is in `_ALLOWED_SORT_KEYS`; the .get() fallback is
            # defense-in-depth for the case where a future allowed key
            # is added but the column map isn't updated.
            sort_col = _JOB_SORT_COLUMNS.get(key, Job.first_seen_at)
            order_clauses.append(sort_col.desc() if direction == "desc" else sort_col.asc())

    if not order_clauses:
        # Pathological case: chain was `resume_score` only and user has
        # no active resume → fell through with nothing. Fall back to
        # the documented default so the result set isn't database-
        # implementation-defined order.
        order_clauses = [Job.first_seen_at.desc()]

    query = query.order_by(*order_clauses)

    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    jobs = result.unique().scalars().all()

    # Fetch resume scores for these jobs
    resume_scores_map: dict[str, float] = {}
    if user.active_resume_id and jobs:
        job_ids = [j.id for j in jobs]
        score_result = await db.execute(
            select(ResumeScore.job_id, ResumeScore.overall_score)
            .where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id.in_(job_ids),
            )
        )
        for job_id, score in score_result:
            resume_scores_map[str(job_id)] = round(score, 1)

    items = []
    for j in jobs:
        item = JobOut.model_validate(j)
        item.company_name = j.company.name if j.company else None
        items.append(item)

    # Serialize with resume_score enrichment
    items_data = []
    for item, j in zip(items, jobs):
        d = item.model_dump(mode="json")
        d["resume_score"] = resume_scores_map.get(str(j.id))
        items_data.append(d)

    return {"items": items_data, "total": total, "page": page, "page_size": per_page, "total_pages": (total + per_page - 1) // per_page}


@router.get("/review-queue")
async def review_queue(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    """Get next batch of unreviewed jobs sorted by relevance score."""
    query = (
        select(Job).options(joinedload(Job.company))
        .where(Job.status == "new")
        .order_by(Job.relevance_score.desc(), Job.first_seen_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    jobs = result.unique().scalars().all()

    items = []
    for j in jobs:
        item = JobOut.model_validate(j)
        item.company_name = j.company.name if j.company else None
        items.append(item)

    return {"items": items, "total": len(items), "page": 1, "page_size": limit, "total_pages": 1}


@router.get("/{job_id}")
async def get_job(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).options(joinedload(Job.company), joinedload(Job.description)).where(Job.id == job_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    data = JobOut.model_validate(job)
    data.company_name = job.company.name if job.company else None

    d = data.model_dump(mode="json")

    # Enrich with resume score if active resume exists
    if user.active_resume_id:
        # The resume_scores table has no uniqueness constraint on
        # (resume_id, job_id), and in production we routinely end up
        # with 2+ rows for the same pair because the scoring task can
        # be scheduled multiple times (rescore_all_active_resumes +
        # per-upload score + manual rescore). `scalar_one_or_none()`
        # raises `MultipleResultsFound` on those rows, which bubbles
        # out of the handler as a 500 — that's the Senior Security
        # Engineer @ Bitwarden "Couldn't load this job" bug users
        # hit in prod this afternoon. Short-term fix: select the most
        # recently computed row and move on. The cleanup is a
        # follow-up: dedupe the rows + add a `UNIQUE (resume_id,
        # job_id)` constraint so the score-write path uses an
        # ON CONFLICT DO UPDATE. `/jobs` (list) never surfaced this
        # because it maps duplicates via dict last-write-wins — only
        # the single-job handler's `scalar_one_or_none` contract was
        # strict enough to raise.
        score_result = await db.execute(
            select(ResumeScore)
            .where(
                ResumeScore.resume_id == user.active_resume_id,
                ResumeScore.job_id == job.id,
            )
            .order_by(ResumeScore.scored_at.desc())
            .limit(1)
        )
        rs = score_result.scalar_one_or_none()
        if rs:
            d["resume_score"] = round(rs.overall_score, 1)
            d["resume_fit"] = {
                "overall_score": round(rs.overall_score, 1),
                "keyword_score": round(rs.keyword_score, 1),
                "role_match_score": round(rs.role_match_score, 1),
                "format_score": round(rs.format_score, 1),
                "matched_keywords": rs.matched_keywords or [],
                "missing_keywords": rs.missing_keywords or [],
                "suggestions": rs.suggestions or [],
            }
        else:
            d["resume_score"] = None
            d["resume_fit"] = None
    else:
        d["resume_score"] = None
        d["resume_fit"] = None

    return d


@router.get("/{job_id}/score-breakdown")
async def get_job_score_breakdown(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get scoring breakdown for a specific job."""
    result = await db.execute(
        select(Job).options(joinedload(Job.company)).where(Job.id == job_id)
    )
    job = result.unique().scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from app.workers.tasks._scoring import (
        _title_match_score, _company_fit_score, _geography_clarity_score,
        _source_priority_score, _freshness_score,
    )
    from app.workers.tasks._role_matching import match_role

    role_match = match_role(job.title)
    title_score = _title_match_score(role_match["matched_role"], role_match["role_cluster"])
    company_score = _company_fit_score(job.company.is_target if job.company else False)
    geo_score = _geography_clarity_score(job.geography_bucket, job.remote_scope)
    source_score = _source_priority_score(job.platform)
    fresh_score = _freshness_score(job.posted_at)

    return {
        "total": job.relevance_score,
        "breakdown": [
            {"signal": "Title Match", "weight": 0.40, "raw": round(title_score, 2), "weighted": round(title_score * 0.40 * 100, 1), "detail": f"Matched: {role_match['matched_role'] or 'None'} ({role_match['role_cluster'] or 'no cluster'})"},
            {"signal": "Company Fit", "weight": 0.20, "raw": round(company_score, 2), "weighted": round(company_score * 0.20 * 100, 1), "detail": f"Target: {'Yes' if (job.company and job.company.is_target) else 'No'}"},
            {"signal": "Geography Clarity", "weight": 0.20, "raw": round(geo_score, 2), "weighted": round(geo_score * 0.20 * 100, 1), "detail": f"Bucket: {job.geography_bucket or 'unknown'}, Scope: {job.remote_scope or 'none'}"},
            {"signal": "Source Priority", "weight": 0.10, "raw": round(source_score, 2), "weighted": round(source_score * 0.10 * 100, 1), "detail": f"Platform: {job.platform}"},
            {"signal": "Freshness", "weight": 0.10, "raw": round(fresh_score, 2), "weighted": round(fresh_score * 0.10 * 100, 1), "detail": f"Posted: {job.posted_at.strftime('%Y-%m-%d') if job.posted_at else 'Unknown'}"},
        ],
    }


@router.get("/{job_id}/description")
async def get_job_description(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobDescription).where(JobDescription.job_id == job_id))
    jd = result.scalar_one_or_none()
    if jd:
        # The frontend renders this via dangerouslySetInnerHTML, so any HTML
        # coming from ATS boards must be sanitized (strip <script>, event
        # handlers, javascript: URLs, etc.) before we hand it back.
        return JobDescriptionOut(
            id=jd.id,
            job_id=jd.job_id,
            raw_text=sanitize_html(jd.text_content or jd.html_content or ""),
        )

    # Fallback: extract description from raw_json
    import html as html_mod
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    raw_text = ""
    if job and job.raw_json:
        raw = job.raw_json if isinstance(job.raw_json, dict) else {}
        # Platform-specific field mapping
        raw_text = (
            raw.get("content")           # greenhouse
            or raw.get("descriptionHtml")  # ashby
            or raw.get("description")      # lever, himalayas, remoteok, remotive
            or raw.get("descriptionPlain")  # lever/ashby plaintext fallback
            or raw.get("descriptionBody")   # lever additional
            or ""
        )
        # Lever stores lists of requirements — join if the additional field has more
        additional = raw.get("additional") or raw.get("additionalPlain") or ""
        if additional and len(additional) > len(raw_text):
            raw_text = additional
        # Unescape HTML entities (raw_json may store &lt; as escaped)
        if raw_text and "&lt;" in raw_text:
            raw_text = html_mod.unescape(raw_text)

    # Sanitize before returning — frontend renders via dangerouslySetInnerHTML.
    return JobDescriptionOut(raw_text=sanitize_html(raw_text))


@router.get("/{job_id}/reviews")
async def get_job_reviews(job_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get reviews for a specific job."""
    from app.models.review import Review
    from app.schemas.review import ReviewOut
    result = await db.execute(
        select(Review).options(joinedload(Review.reviewer))
        .where(Review.job_id == job_id)
        .order_by(Review.created_at.desc())
    )
    reviews = result.unique().scalars().all()
    items = []
    for r in reviews:
        item = ReviewOut.model_validate(r)
        item.reviewer_name = r.reviewer.name if r.reviewer else None
        items.append(item)
    return items


@router.patch("/{job_id}")
async def update_job_status(
    job_id: UUID, body: JobStatusUpdate,
    request: Request,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    old_status = job.status
    job.status = body.status
    await db.commit()

    await log_action(
        db, user,
        action="job.status_change",
        resource="job",
        request=request,
        metadata={"job_id": str(job_id), "old_status": old_status, "new_status": body.status},
    )

    return {"ok": True}


# Regression finding 69: hard cap on the filter branch. 47k-row corpora
# are realistic, so a "Select all N matching" click on no filter could
# trivially flip the status of every row in the DB. We reject requests
# whose filter matches > BULK_FILTER_MAX rows with a 400 that tells
# the caller the current count, so they can narrow before retry. The
# cap is deliberately generous (5000) — enough for a sales team to
# reject an entire source platform in one go, but small enough that
# a misclick can't corrupt the full corpus without visible friction.
BULK_FILTER_MAX = 5000


async def _build_bulk_filter_query(
    criteria, db: AsyncSession
):
    """Rebuild the same WHERE chain that `GET /jobs` uses so the filter
    branch and the list endpoint agree on which rows match — otherwise
    the "Select all 47,776 matching" count displayed in the UI could
    diverge from the set that actually gets updated, which would be
    exactly the kind of silent-blast-radius bug we're trying to
    prevent. Returns a select(Job) that the caller can execute or
    wrap in a count. Validates `role_cluster` against the configured
    catalog (same contract as `/jobs` F218) so a typo 400s here too
    instead of quietly updating zero rows."""
    query = select(Job)

    if criteria.status:
        query = query.where(Job.status == criteria.status)
    if criteria.platform:
        query = query.where(Job.platform == criteria.platform)
    if criteria.company_id:
        query = query.where(Job.company_id == criteria.company_id)
    if criteria.geography_bucket:
        query = query.where(Job.geography_bucket == criteria.geography_bucket)
    if criteria.role_cluster:
        allowed_clusters = set(await _get_all_cluster_names(db)) | {"relevant"}
        if criteria.role_cluster not in allowed_clusters:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid role_cluster. Must be one of: "
                    + ", ".join(sorted(allowed_clusters))
                ),
            )
        if criteria.role_cluster == "relevant":
            relevant_clusters = await _get_relevant_clusters(db)
            query = query.where(Job.role_cluster.in_(relevant_clusters))
        else:
            query = query.where(Job.role_cluster == criteria.role_cluster)
    if criteria.is_classified is True:
        query = query.where(Job.role_cluster.is_not(None), Job.role_cluster != "")
    elif criteria.is_classified is False:
        query = query.where(or_(Job.role_cluster.is_(None), Job.role_cluster == ""))
    if criteria.search and criteria.search.strip():
        needle = f"%{escape_like(criteria.search.strip())}%"
        query = query.where(
            or_(
                Job.title.ilike(needle, escape="\\"),
                Job.company.has(Company.name.ilike(needle, escape="\\")),
                Job.location_raw.ilike(needle, escape="\\"),
            )
        )
    return query


@router.post("/bulk-action")
async def bulk_action(
    body: BulkActionRequest,
    request: Request,
    user: User = Depends(require_role("admin", "reviewer")),
    db: AsyncSession = Depends(get_db),
):
    # Regression finding 69: two mutually-exclusive input shapes.
    # Reject requests that provide neither or both — ambiguous input
    # shouldn't silently prefer one path.
    if body.job_ids is None and body.filter is None:
        raise HTTPException(
            status_code=400,
            detail="Either `job_ids` or `filter` must be provided.",
        )
    if body.job_ids is not None and body.filter is not None:
        raise HTTPException(
            status_code=400,
            detail="Provide either `job_ids` or `filter`, not both.",
        )

    if body.job_ids is not None:
        # Legacy id-list branch — unchanged semantics.
        if len(body.job_ids) == 0:
            raise HTTPException(status_code=400, detail="`job_ids` cannot be empty.")
        # F69: cap even the id-list branch at BULK_FILTER_MAX. Nothing
        # in the old path prevented a client from POSTing 100k ids;
        # applying the same cap keeps the blast-radius story single-
        # bullet ("at most BULK_FILTER_MAX rows change per call").
        if len(body.job_ids) > BULK_FILTER_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"Too many job_ids ({len(body.job_ids)}). Max per request is {BULK_FILTER_MAX}.",
            )
        result = await db.execute(select(Job).where(Job.id.in_(body.job_ids)))
        jobs = result.scalars().all()
        metadata = {
            "mode": "ids",
            "job_ids": [str(j) for j in body.job_ids],
            "count": len(jobs),
        }
    else:
        # Filter branch — rebuild the same WHERE chain /jobs uses and
        # cap the matching set before mutating anything. The cap
        # check uses a COUNT so we don't pull thousands of rows into
        # memory just to reject them.
        assert body.filter is not None
        filter_query = await _build_bulk_filter_query(body.filter, db)
        count = (await db.execute(
            select(func.count()).select_from(filter_query.subquery())
        )).scalar() or 0
        if count == 0:
            raise HTTPException(status_code=400, detail="Filter matched zero jobs.")
        if count > BULK_FILTER_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Filter matches {count} jobs which exceeds the bulk cap of "
                    f"{BULK_FILTER_MAX}. Narrow the filter before retrying."
                ),
            )
        result = await db.execute(filter_query)
        jobs = result.scalars().all()
        # Serialize the filter into the audit log so post-hoc review
        # can reconstruct exactly which criteria triggered the mass
        # update. Using `model_dump(mode='json')` coerces UUID to str.
        metadata = {
            "mode": "filter",
            "filter": body.filter.model_dump(mode="json"),
            "count": len(jobs),
        }

    for j in jobs:
        j.status = body.action
    await db.commit()

    await log_action(
        db, user,
        action=f"bulk.{body.action}",
        resource="jobs",
        request=request,
        metadata=metadata,
    )

    return {"updated": len(jobs)}
