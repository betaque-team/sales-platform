"""Analytics and dashboard API."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, text, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.models.review import Review
from app.models.pipeline import PotentialClient
from app.models.company import Company, CompanyATSBoard
from app.models.company_contact import CompanyContact
from app.models.application import Application
from app.models.user import User
from app.api.deps import get_current_user, require_role

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Job counts by status
    status_counts = {}
    result = await db.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    for row in result:
        status_counts[row[0]] = row[1]

    total_jobs = sum(status_counts.values())
    # Count companies from the Company table (consistent with Companies page and
    # Monitoring); previously this used COUNT(DISTINCT jobs.company_id) which
    # undercounts by excluding companies that don't currently have a job row.
    total_companies = (await db.execute(select(func.count(Company.id)))).scalar() or 0
    pipeline_count = (await db.execute(select(func.count(PotentialClient.id)))).scalar() or 0

    accepted_count = status_counts.get("accepted", 0)
    rejected_count = status_counts.get("rejected", 0)
    reviewed_count = accepted_count + rejected_count
    acceptance_rate = (accepted_count / reviewed_count) if reviewed_count > 0 else 0

    avg_relevance = (await db.execute(
        select(func.avg(Job.relevance_score)).where(Job.relevance_score > 0)
    )).scalar() or 0

    return {
        "total_jobs": total_jobs,
        "by_status": status_counts,
        "total_companies": total_companies,
        "pipeline_count": pipeline_count,
        "pipeline_active": pipeline_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "reviewed_count": reviewed_count,
        "acceptance_rate": float(acceptance_rate),
        "avg_relevance_score": round(float(avg_relevance), 2),
    }


@router.get("/sources")
async def sources(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job.platform, func.count(Job.id)).group_by(Job.platform).order_by(func.count(Job.id).desc())
    )
    return [{"platform": row[0], "count": row[1]} for row in result]


@router.get("/trends")
async def trends(days: int = 30, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("""
        SELECT
            DATE(first_seen_at) AS day,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE role_cluster = 'infra') AS infra,
            COUNT(*) FILTER (WHERE role_cluster = 'security') AS security,
            COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
            COUNT(*) FILTER (WHERE status = 'rejected') AS rejected
        FROM jobs
        WHERE first_seen_at >= NOW() - make_interval(days => :days)
        GROUP BY DATE(first_seen_at)
        ORDER BY day
    """).bindparams(days=days))
    return [
        {
            "day": str(row[0]),
            # Keep "date" alias for frontend charts that use date
            "date": str(row[0]),
            "total": row[1],
            "infra": row[2],
            "security": row[3],
            "accepted": row[4],
            "rejected": row[5],
            # Keep legacy "count" and "new_jobs" aliases for backward compat
            "count": row[1],
            "new_jobs": row[1],
        }
        for row in result
    ]


@router.get("/ai-insights")
async def ai_insights(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Generate AI-powered insights about job and company trends using Claude."""
    from app.config import get_settings
    settings = get_settings()

    # ---- Gather stats ----
    status_counts: dict = {}
    result = await db.execute(select(Job.status, func.count(Job.id)).group_by(Job.status))
    for row in result:
        status_counts[row[0]] = row[1]

    total_jobs = sum(status_counts.values())
    accepted = status_counts.get("accepted", 0)
    rejected = status_counts.get("rejected", 0)
    reviewed = accepted + rejected
    acceptance_rate = round(accepted / reviewed * 100, 1) if reviewed else 0

    # Source distribution (top 6 by volume, for display/prompt sizing)
    src_result = await db.execute(
        select(Job.platform, func.count(Job.id))
        .group_by(Job.platform)
        .order_by(func.count(Job.id).desc())
        .limit(6)
    )
    sources = [{"platform": r[0], "count": r[1]} for r in src_result]

    # Total number of distinct ATS sources — used in insight copy.
    # Previously this was `COUNT(DISTINCT Job.platform)`, which hid any
    # configured platform whose boards hadn't produced a job row yet
    # (bamboohr, recruitee, wellfound, etc. at the time of regression
    # finding 28). Match the Platforms page instead: union of the distinct
    # platform names from CompanyATSBoard *and* Job. That way the insight
    # copy always agrees with the Platforms tab.
    board_platforms = (await db.execute(
        select(func.distinct(CompanyATSBoard.platform))
    )).scalars().all()
    job_platforms = (await db.execute(
        select(func.distinct(Job.platform))
    )).scalars().all()
    total_sources = len({p for p in (*board_platforms, *job_platforms) if p})

    # Role cluster split
    cluster_result = await db.execute(
        select(Job.role_cluster, func.count(Job.id)).group_by(Job.role_cluster)
    )
    clusters = {r[0]: r[1] for r in cluster_result}

    # 14-day daily trend (weekly buckets for brevity)
    trend_result = await db.execute(text("""
        SELECT
            DATE_TRUNC('week', first_seen_at) AS week,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE role_cluster = 'infra') AS infra,
            COUNT(*) FILTER (WHERE role_cluster = 'security') AS security
        FROM jobs
        WHERE first_seen_at >= NOW() - INTERVAL '42 days'
        GROUP BY DATE_TRUNC('week', first_seen_at)
        ORDER BY week
    """))
    weekly = [
        {"week": str(r[0])[:10], "total": r[1], "infra": r[2], "security": r[3]}
        for r in trend_result
    ]

    # Companies with active hiring in last 30d
    active_companies = (await db.execute(text("""
        SELECT COUNT(DISTINCT company_id) FROM jobs
        WHERE first_seen_at >= NOW() - INTERVAL '30 days'
    """))).scalar() or 0

    # Contacts coverage
    contact_count = (await db.execute(select(func.count(CompanyContact.id)))).scalar() or 0
    verified_contacts = (await db.execute(
        select(func.count(CompanyContact.id)).where(CompanyContact.email_status == "valid")
    )).scalar() or 0

    stats = {
        "total_jobs": total_jobs,
        "new_jobs_30d": status_counts.get("new", 0),
        "accepted": accepted,
        "rejected": rejected,
        "acceptance_rate_pct": acceptance_rate,
        "infra_jobs": clusters.get("infra", 0),
        "security_jobs": clusters.get("security", 0),
        "top_sources": sources,
        "total_sources": total_sources,
        "active_companies_30d": active_companies,
        "total_contacts": contact_count,
        "verified_contacts": verified_contacts,
        "weekly_trend": weekly,
    }

    # ---- AI call ----
    if not settings.anthropic_api_key:
        return _fallback_insights(stats)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""You are a job-market intelligence analyst reviewing data from a sales & job aggregation platform that tracks cloud/infra/security roles.

Here are the current platform statistics:
{stats}

Generate 5–7 concise, actionable insights about:
1. Hiring velocity and trends (is activity accelerating or slowing?)
2. Which role cluster (infra vs security) is hotter right now
3. Source platform performance (where are the best leads coming from?)
4. Contact/outreach readiness (are we well-positioned to reach decision-makers?)
5. Any patterns, anomalies, or recommendations worth acting on this week

Format: Return ONLY a JSON array of insight strings, like:
["Insight 1 here.", "Insight 2 here.", ...]
Each insight should be 1–2 sentences, specific, and reference actual numbers where useful."""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text_content = message.content[0].text.strip()

        # Parse JSON array
        import json
        start = text_content.find("[")
        end = text_content.rfind("]") + 1
        insights = json.loads(text_content[start:end]) if start != -1 else []
        if not isinstance(insights, list):
            insights = []
    except Exception:
        return _fallback_insights(stats)

    return {
        "insights": insights,
        "stats": stats,
        "ai_generated": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _fallback_insights(stats: dict) -> dict:
    """Rule-based fallback when Anthropic API is unavailable."""
    insights = []
    total = stats["total_jobs"]
    infra = stats["infra_jobs"]
    security = stats["security_jobs"]
    acceptance = stats["acceptance_rate_pct"]
    contacts = stats["total_contacts"]
    verified = stats["verified_contacts"]

    if total:
        source_count = stats.get("total_sources") or len(stats["top_sources"])
        insights.append(f"Platform has {total:,} jobs indexed across {source_count} ATS sources.")

    if infra and security:
        ratio = round(infra / (infra + security) * 100)
        dominant = "infra/cloud" if infra > security else "security/compliance"
        insights.append(f"{dominant.title()} roles dominate at {ratio if infra > security else 100 - ratio}% of relevant listings ({infra:,} infra vs {security:,} security).")

    if acceptance:
        insights.append(f"Current acceptance rate is {acceptance}% — {'strong signal quality' if acceptance >= 20 else 'consider broadening your filters'}.")

    if stats["top_sources"]:
        top = stats["top_sources"][0]
        insights.append(f"{top['platform'].title()} is the top source with {top['count']:,} jobs — prioritize monitoring this platform.")

    if contacts:
        pct = round(verified / contacts * 100) if contacts else 0
        insights.append(f"{contacts:,} contacts tracked; {pct}% have verified emails ({verified:,}) — {'ready for outreach campaigns' if pct >= 30 else 'enrich more companies to improve coverage'}.")

    if stats["active_companies_30d"]:
        insights.append(f"{stats['active_companies_30d']} companies posted new roles in the last 30 days — prime window for outreach.")

    return {
        "insights": insights,
        "stats": stats,
        "ai_generated": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/funnel")
async def funnel(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Job.id)))).scalar() or 0
    reviewed = (await db.execute(
        select(func.count(Job.id)).where(Job.status.in_(["accepted", "rejected"]))
    )).scalar() or 0
    accepted = (await db.execute(select(func.count(Job.id)).where(Job.status == "accepted"))).scalar() or 0
    in_pipeline = (await db.execute(select(func.count(PotentialClient.id)))).scalar() or 0

    return {
        "stages": [
            {"name": "New Jobs", "count": total},
            {"name": "Reviewed", "count": reviewed},
            {"name": "Accepted", "count": accepted},
            {"name": "In Pipeline", "count": in_pipeline},
        ]
    }


@router.get("/application-funnel")
async def application_funnel(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Application conversion funnel: prepared -> applied -> interview -> offer."""
    result = await db.execute(
        select(Application.status, func.count(Application.id))
        .where(Application.user_id == user.id)
        .group_by(Application.status)
    )
    counts = {row[0]: row[1] for row in result}

    prepared = counts.get("prepared", 0) + counts.get("applied", 0) + counts.get("interview", 0) + counts.get("offer", 0)
    applied = counts.get("applied", 0) + counts.get("interview", 0) + counts.get("offer", 0)
    interview = counts.get("interview", 0) + counts.get("offer", 0)
    offer = counts.get("offer", 0)

    return {
        "stages": [
            {"stage": "prepared", "count": prepared},
            {"stage": "applied", "count": applied},
            {"stage": "interview", "count": interview},
            {"stage": "offer", "count": offer},
            {"stage": "rejected", "count": counts.get("rejected", 0)},
            {"stage": "withdrawn", "count": counts.get("withdrawn", 0)},
        ],
        "conversion": {
            "prepared_to_applied": round(applied / prepared * 100, 1) if prepared else 0,
            "applied_to_interview": round(interview / applied * 100, 1) if applied else 0,
            "interview_to_offer": round(offer / interview * 100, 1) if interview else 0,
        },
    }


@router.get("/applications-by-platform")
async def applications_by_platform(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Application counts grouped by ATS platform."""
    result = await db.execute(
        select(
            Job.platform,
            Application.status,
            func.count(Application.id),
        )
        .join(Job, Application.job_id == Job.id)
        .where(Application.user_id == user.id)
        .group_by(Job.platform, Application.status)
    )

    platform_data: dict[str, dict] = {}
    for platform, status, count in result:
        if platform not in platform_data:
            platform_data[platform] = {"platform": platform, "total": 0, "applied": 0, "interview": 0, "offer": 0}
        platform_data[platform]["total"] += count
        if status in ("applied", "interview", "offer"):
            platform_data[platform][status] += count

    return {"platforms": sorted(platform_data.values(), key=lambda x: x["total"], reverse=True)}


@router.get("/review-insights")
async def review_insights(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Insights from review decisions: rejection reasons, acceptance by platform."""
    # Total counts
    result = await db.execute(
        select(Review.decision, func.count(Review.id)).group_by(Review.decision)
    )
    decision_counts = {row[0]: row[1] for row in result}

    # Tags (rejection reasons) -- tags is a PostgreSQL text array
    tag_result = await db.execute(text("""
        SELECT tag, COUNT(*) as cnt
        FROM reviews, unnest(tags) AS tag
        WHERE decision = 'rejected' AND array_length(tags, 1) > 0
        GROUP BY tag
        ORDER BY cnt DESC
    """))
    rejection_reasons = [{"tag": row[0], "count": row[1]} for row in tag_result]

    # Acceptance rate by platform
    platform_result = await db.execute(
        select(
            Job.platform,
            Review.decision,
            func.count(Review.id),
        )
        .join(Job, Review.job_id == Job.id)
        .where(Review.decision.in_(["accepted", "rejected"]))
        .group_by(Job.platform, Review.decision)
    )
    platform_data: dict[str, dict] = {}
    for platform, decision, count in platform_result:
        if platform not in platform_data:
            platform_data[platform] = {"platform": platform, "accepted": 0, "rejected": 0, "rate": 0}
        platform_data[platform][decision] = count

    for p in platform_data.values():
        total = p["accepted"] + p["rejected"]
        p["rate"] = round(p["accepted"] / total * 100, 1) if total else 0

    return {
        "total_reviewed": sum(decision_counts.values()),
        "accepted": decision_counts.get("accepted", 0),
        "rejected": decision_counts.get("rejected", 0),
        "skipped": decision_counts.get("skipped", 0),
        "rejection_reasons": rejection_reasons,
        "acceptance_by_platform": sorted(platform_data.values(), key=lambda x: x["rate"], reverse=True),
    }


@router.get("/funding-signals")
async def funding_signals(
    days: int = 180,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Companies that recently received funding — sorted by funded_at desc.
    These are the highest-priority outreach targets (expansion mode).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Contact counts per company
    contact_sub = (
        select(
            CompanyContact.company_id,
            func.count(CompanyContact.id).label("total_contacts"),
            func.sum(case((CompanyContact.is_decision_maker.is_(True), 1), else_=0)).label("decision_makers"),
            func.sum(case((CompanyContact.email_status == "valid", 1), else_=0)).label("verified_contacts"),
        )
        .group_by(CompanyContact.company_id)
        .subquery()
    )

    # Job activity counts
    jobs_sub = (
        select(
            Job.company_id,
            func.count(Job.id).label("open_roles"),
        )
        .where(Job.status.in_(["new", "under_review", "accepted"]))
        .group_by(Job.company_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Company.id,
            Company.name,
            Company.domain,
            Company.industry,
            Company.total_funding,
            Company.funding_stage,
            Company.funded_at,
            Company.funding_news_url,
            Company.employee_count,
            Company.is_target,
            contact_sub.c.total_contacts,
            contact_sub.c.decision_makers,
            contact_sub.c.verified_contacts,
            jobs_sub.c.open_roles,
        )
        .outerjoin(contact_sub, Company.id == contact_sub.c.company_id)
        .outerjoin(jobs_sub, Company.id == jobs_sub.c.company_id)
        .where(Company.funded_at >= cutoff)
        .order_by(Company.funded_at.desc(), Company.total_funding_usd.desc().nulls_last())
        .limit(50)
    )

    now = datetime.now(timezone.utc)
    items = []
    for row in result:
        days_ago = (now - row.funded_at).days if row.funded_at else None
        items.append({
            "company_id": str(row.id),
            "company_name": row.name,
            "domain": row.domain or "",
            "industry": row.industry or "",
            "total_funding": row.total_funding or "",
            "funding_stage": row.funding_stage or "",
            "funded_at": row.funded_at.isoformat() if row.funded_at else None,
            "days_since_funded": days_ago,
            "funding_news_url": row.funding_news_url or "",
            "employee_count": row.employee_count or "",
            "is_target": row.is_target,
            "total_contacts": int(row.total_contacts or 0),
            "decision_makers": int(row.decision_makers or 0),
            "verified_contacts": int(row.verified_contacts or 0),
            "open_roles": int(row.open_roles or 0),
        })

    return {"items": items, "total": len(items), "days": days}


@router.get("/warm-leads")
async def warm_leads(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Return the top companies with active hiring + verified/valid contacts.
    These are the 'warm leads' — companies with verified contacts and recent job activity.
    """
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    # Subquery: jobs in last 30 days per company
    jobs_sub = (
        select(
            Job.company_id,
            func.count(Job.id).label("new_jobs_30d"),
            func.sum(case((Job.first_seen_at >= cutoff_7d, 1), else_=0)).label("new_jobs_7d"),
            func.max(Job.relevance_score).label("top_score"),
        )
        .where(
            Job.first_seen_at >= cutoff_30d,
            Job.role_cluster.in_(["infra", "security"]),
        )
        .group_by(Job.company_id)
        .subquery()
    )

    # Subquery: contacts with valid emails per company
    contacts_sub = (
        select(
            CompanyContact.company_id,
            func.count(CompanyContact.id).label("total_contacts"),
            func.sum(case((CompanyContact.email_status == "valid", 1), else_=0)).label("verified_contacts"),
            func.sum(case((CompanyContact.is_decision_maker.is_(True), 1), else_=0)).label("decision_makers"),
        )
        .group_by(CompanyContact.company_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Company.id,
            Company.name,
            Company.domain,
            Company.industry,
            Company.total_funding,
            Company.funding_stage,
            Company.is_target,
            jobs_sub.c.new_jobs_30d,
            jobs_sub.c.new_jobs_7d,
            jobs_sub.c.top_score,
            contacts_sub.c.total_contacts,
            contacts_sub.c.verified_contacts,
            contacts_sub.c.decision_makers,
        )
        .join(jobs_sub, Company.id == jobs_sub.c.company_id)
        .join(contacts_sub, Company.id == contacts_sub.c.company_id)
        .where(contacts_sub.c.total_contacts > 0)
        .order_by(
            contacts_sub.c.decision_makers.desc(),
            contacts_sub.c.verified_contacts.desc(),
            jobs_sub.c.new_jobs_7d.desc(),
        )
        .limit(20)
    )

    items = []
    for row in result:
        items.append({
            "company_id": str(row.id),
            "company_name": row.name,
            "domain": row.domain or "",
            "industry": row.industry or "",
            "total_funding": row.total_funding or "",
            "funding_stage": row.funding_stage or "",
            "is_target": row.is_target,
            "new_jobs_30d": int(row.new_jobs_30d or 0),
            "new_jobs_7d": int(row.new_jobs_7d or 0),
            "top_relevance_score": round(float(row.top_score or 0), 1),
            "total_contacts": int(row.total_contacts or 0),
            "verified_contacts": int(row.verified_contacts or 0),
            "decision_makers": int(row.decision_makers or 0),
        })

    return {"items": items}


@router.get("/scoring-signals")
async def get_scoring_signals(user: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """Get top scoring signals for admin visibility.

    Regression finding 102: the response previously omitted ``user_id``,
    so there was no way for admins to verify Finding 89's per-user
    isolation was working on prod — every row looked identical whether
    it belonged to a specific reviewer or to the legacy shared pool.
    We now return the column verbatim (NULL = legacy shared-pool row,
    UUID = reviewer-scoped). The frontend can surface it as a small
    "reviewer" column / badge so ops can see at a glance whether new
    signals are being written with the expected user attribution.
    """
    from app.models.scoring_signal import ScoringSignal
    result = await db.execute(
        select(ScoringSignal).order_by(ScoringSignal.weight.desc()).limit(50)
    )
    signals = result.scalars().all()
    return {
        "signals": [
            {
                "user_id": str(s.user_id) if s.user_id else None,
                "signal_type": s.signal_type,
                "signal_key": s.signal_key,
                "weight": round(s.weight, 4),
                "source_count": s.source_count,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in signals
        ]
    }
