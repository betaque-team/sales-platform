"""Intelligence API: skill gaps, salary insights, application timing, networking suggestions."""

import re
import json
from collections import Counter
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text, case, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job, JobDescription
from app.models.company import Company
from app.models.company_contact import CompanyContact
from app.models.resume import Resume
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter(prefix="/intelligence", tags=["intelligence"])

# ── Tech skills dictionary for extraction ────────────────────────────────────
SKILL_CATEGORIES = {
    "cloud": ["aws", "azure", "gcp", "google cloud", "cloud", "ec2", "s3", "lambda", "cloudformation", "cloudfront"],
    "containers": ["docker", "kubernetes", "k8s", "helm", "containerd", "podman", "ecs", "eks", "aks", "gke", "openshift"],
    "ci_cd": ["jenkins", "github actions", "gitlab ci", "circleci", "argocd", "spinnaker", "tekton", "ci/cd", "cicd"],
    "iac": ["terraform", "ansible", "pulumi", "chef", "puppet", "cloudformation", "bicep", "crossplane"],
    "monitoring": ["prometheus", "grafana", "datadog", "splunk", "elk", "elasticsearch", "kibana", "new relic", "pagerduty", "observability"],
    "security": ["soc", "siem", "pentest", "penetration testing", "vulnerability", "compliance", "iso 27001", "soc 2", "gdpr", "nist", "owasp", "devsecops", "iam"],
    "networking": ["cdn", "dns", "load balancer", "nginx", "envoy", "istio", "vpn", "firewall", "cloudflare", "tcp/ip"],
    "languages": ["python", "go", "golang", "rust", "java", "typescript", "javascript", "bash", "shell", "ruby", "c++", "scala"],
    "databases": ["postgresql", "postgres", "mysql", "mongodb", "redis", "dynamodb", "cassandra", "elasticsearch", "kafka"],
    "qa_testing": ["selenium", "cypress", "playwright", "jest", "pytest", "junit", "test automation", "sdet", "qa", "performance testing", "load testing"],
}

ALL_SKILLS = {}
for cat, skills in SKILL_CATEGORIES.items():
    for skill in skills:
        ALL_SKILLS[skill.lower()] = cat


def _extract_skills_from_text(text_content: str) -> dict[str, int]:
    """Extract skill mentions from text, return {skill: count}."""
    text_lower = text_content.lower()
    found = {}
    for skill in ALL_SKILLS:
        # Word boundary match for short skills
        if len(skill) <= 3:
            pattern = r'\b' + re.escape(skill) + r'\b'
            count = len(re.findall(pattern, text_lower))
        else:
            count = text_lower.count(skill)
        if count > 0:
            found[skill] = count
    return found


# ── Skill Gap Dashboard ──────────────────────────────────────────────────────

@router.get("/skill-gaps")
async def skill_gaps(
    role_cluster: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze skill gaps: what jobs demand vs what your resume has."""
    # Get user's active resume skills
    resume_skills: dict[str, int] = {}
    if user.active_resume_id:
        resume = (await db.execute(
            select(Resume).where(Resume.id == user.active_resume_id, Resume.user_id == user.id)
        )).scalar_one_or_none()
        if resume and resume.text_content:
            resume_skills = _extract_skills_from_text(resume.text_content)

    # Get job descriptions for relevant jobs
    query = (
        select(JobDescription.text_content, Job.role_cluster)
        .join(Job, JobDescription.job_id == Job.id)
        .where(Job.relevance_score > 0)
    )
    if role_cluster:
        query = query.where(Job.role_cluster == role_cluster)
    query = query.limit(500)

    result = await db.execute(query)
    rows = result.all()

    # Aggregate skill demand across all job descriptions
    demand: Counter = Counter()
    job_count = len(rows)
    for raw_text, _ in rows:
        if raw_text:
            skills = _extract_skills_from_text(raw_text)
            for skill in skills:
                demand[skill] += 1

    # Build skill gap analysis
    skills_data = []
    for skill, jobs_mentioning in demand.most_common(50):
        category = ALL_SKILLS.get(skill, "other")
        pct = round(jobs_mentioning / job_count * 100, 1) if job_count else 0
        have = skill in resume_skills
        skills_data.append({
            "skill": skill,
            "category": category,
            "demand_count": jobs_mentioning,
            "demand_pct": pct,
            "on_resume": have,
            "gap": not have,
        })

    # Summary stats
    total_demanded = len([s for s in skills_data if s["demand_pct"] >= 5])
    total_have = len([s for s in skills_data if s["on_resume"] and s["demand_pct"] >= 5])
    total_missing = total_demanded - total_have

    # Top missing skills (high demand, not on resume)
    top_missing = [s for s in skills_data if s["gap"] and s["demand_pct"] >= 10]
    top_missing.sort(key=lambda x: x["demand_pct"], reverse=True)

    # Category breakdown
    cat_demand: dict[str, dict] = {}
    for s in skills_data:
        cat = s["category"]
        if cat not in cat_demand:
            cat_demand[cat] = {"category": cat, "total": 0, "have": 0, "missing": 0}
        if s["demand_pct"] >= 5:
            cat_demand[cat]["total"] += 1
            if s["on_resume"]:
                cat_demand[cat]["have"] += 1
            else:
                cat_demand[cat]["missing"] += 1

    return {
        "skills": skills_data,
        "summary": {
            "jobs_analyzed": job_count,
            "total_skills_tracked": total_demanded,
            "skills_on_resume": total_have,
            "skills_missing": total_missing,
            "coverage_pct": round(total_have / total_demanded * 100, 1) if total_demanded else 0,
        },
        "top_missing": top_missing[:10],
        "category_breakdown": sorted(cat_demand.values(), key=lambda x: x["missing"], reverse=True),
        "has_resume": bool(resume_skills),
    }


# ── Salary Intelligence ──────────────────────────────────────────────────────

def _parse_salary(salary_str: str) -> dict | None:
    """Parse salary string into structured data."""
    if not salary_str:
        return None
    s = salary_str.lower().replace(",", "").replace(" ", "")

    # Detect currency
    currency = "USD"
    if "£" in s or "gbp" in s:
        currency = "GBP"
    elif "€" in s or "eur" in s:
        currency = "EUR"

    # Extract numbers
    numbers = re.findall(r'(\d+(?:\.\d+)?)', s)
    if not numbers:
        return None

    nums = [float(n) for n in numbers]
    # Normalize: if numbers look like thousands (e.g., "150" means 150k)
    nums = [n * 1000 if n < 1000 else n for n in nums]

    # Detect period
    period = "year"
    if "/hr" in s or "hour" in s or "/h" in s:
        period = "hour"
    elif "/mo" in s or "month" in s:
        period = "month"

    # Normalize to annual
    if period == "hour":
        nums = [n * 2080 for n in nums]  # 40h * 52w
    elif period == "month":
        nums = [n * 12 for n in nums]

    if len(nums) >= 2:
        return {"min": int(min(nums)), "max": int(max(nums)), "mid": int(sum(nums) / len(nums)), "currency": currency}
    elif len(nums) == 1:
        return {"min": int(nums[0]), "max": int(nums[0]), "mid": int(nums[0]), "currency": currency}
    return None


@router.get("/salary")
async def salary_insights(
    role_cluster: str = "",
    geography: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse and aggregate salary data across all jobs with salary info."""
    query = select(Job.salary_range, Job.role_cluster, Job.geography_bucket, Job.title, Company.name).join(
        Company, Job.company_id == Company.id
    ).where(Job.salary_range != "", Job.salary_range.isnot(None))

    if role_cluster:
        query = query.where(Job.role_cluster == role_cluster)
    if geography:
        query = query.where(Job.geography_bucket == geography)

    result = await db.execute(query.limit(1000))
    rows = result.all()

    parsed = []
    by_cluster: dict[str, list] = {}
    by_geography: dict[str, list] = {}

    for salary_str, cluster, geo, title, company_name in rows:
        p = _parse_salary(salary_str)
        if not p or p["mid"] < 20000 or p["mid"] > 1000000:  # filter outliers
            continue
        entry = {**p, "role_cluster": cluster, "geography": geo, "title": title, "company": company_name, "raw": salary_str}
        parsed.append(entry)
        by_cluster.setdefault(cluster or "other", []).append(p["mid"])
        by_geography.setdefault(geo or "unspecified", []).append(p["mid"])

    # Aggregate stats
    def _stats(values):
        if not values:
            return {"min": 0, "max": 0, "avg": 0, "median": 0, "count": 0}
        values.sort()
        mid_idx = len(values) // 2
        median = values[mid_idx] if len(values) % 2 else (values[mid_idx - 1] + values[mid_idx]) / 2
        return {
            "min": int(min(values)),
            "max": int(max(values)),
            "avg": int(sum(values) / len(values)),
            "median": int(median),
            "count": len(values),
        }

    all_mids = [p["mid"] for p in parsed]

    # Salary ranges distribution (buckets)
    buckets = {"<80k": 0, "80-120k": 0, "120-160k": 0, "160-200k": 0, "200-250k": 0, "250k+": 0}
    for mid in all_mids:
        if mid < 80000:
            buckets["<80k"] += 1
        elif mid < 120000:
            buckets["80-120k"] += 1
        elif mid < 160000:
            buckets["120-160k"] += 1
        elif mid < 200000:
            buckets["160-200k"] += 1
        elif mid < 250000:
            buckets["200-250k"] += 1
        else:
            buckets["250k+"] += 1

    return {
        "overall": _stats(all_mids),
        "by_cluster": {k: _stats(v) for k, v in by_cluster.items()},
        "by_geography": {k: _stats(v) for k, v in by_geography.items()},
        "distribution": [{"range": k, "count": v} for k, v in buckets.items()],
        "top_paying": sorted(parsed, key=lambda x: x["mid"], reverse=True)[:15],
        "total_with_salary": len(parsed),
        "total_jobs": (await db.execute(select(func.count(Job.id)))).scalar() or 0,
    }


# ── Application Timing Intelligence ──────────────────────────────────────────

@router.get("/timing")
async def timing_intelligence(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze job posting patterns to find optimal application timing."""
    # Jobs posted by day of week
    dow_result = await db.execute(text("""
        SELECT EXTRACT(DOW FROM first_seen_at) AS dow, COUNT(*) AS cnt
        FROM jobs
        WHERE first_seen_at >= NOW() - INTERVAL '90 days'
        GROUP BY dow ORDER BY dow
    """))
    days_of_week = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    posting_by_day = [{"day": days_of_week[int(r[0])], "count": r[1]} for r in dow_result]

    # Jobs posted by hour
    hour_result = await db.execute(text("""
        SELECT EXTRACT(HOUR FROM first_seen_at) AS hr, COUNT(*) AS cnt
        FROM jobs
        WHERE first_seen_at >= NOW() - INTERVAL '90 days'
        GROUP BY hr ORDER BY hr
    """))
    posting_by_hour = [{"hour": int(r[0]), "count": r[1]} for r in hour_result]

    # Job freshness distribution (how old are accepted jobs since first seen)
    freshness_result = await db.execute(text("""
        SELECT
            CASE
                WHEN EXTRACT(DAY FROM (NOW() - first_seen_at)) < 1 THEN 'Same day'
                WHEN EXTRACT(DAY FROM (NOW() - first_seen_at)) < 3 THEN '1-2 days'
                WHEN EXTRACT(DAY FROM (NOW() - first_seen_at)) < 7 THEN '3-6 days'
                WHEN EXTRACT(DAY FROM (NOW() - first_seen_at)) < 14 THEN '1-2 weeks'
                ELSE '2+ weeks'
            END AS age_bucket,
            COUNT(*) AS cnt
        FROM jobs
        WHERE status = 'accepted'
        GROUP BY age_bucket
    """))
    freshness = [{"bucket": r[0], "count": r[1]} for r in freshness_result]

    # Average time from posting to first review
    avg_review_time = await db.execute(text("""
        SELECT AVG(EXTRACT(EPOCH FROM (r.created_at - j.first_seen_at)) / 3600) AS avg_hours
        FROM reviews r
        JOIN jobs j ON r.job_id = j.id
        WHERE j.first_seen_at >= NOW() - INTERVAL '90 days'
    """))
    avg_hours = avg_review_time.scalar() or 0

    # Platform posting patterns (which platforms post most frequently)
    platform_timing = await db.execute(text("""
        SELECT platform,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE first_seen_at >= NOW() - INTERVAL '7 days') AS last_7d,
            COUNT(*) FILTER (WHERE first_seen_at >= NOW() - INTERVAL '30 days') AS last_30d
        FROM jobs
        WHERE first_seen_at >= NOW() - INTERVAL '90 days'
        GROUP BY platform
        ORDER BY last_7d DESC
    """))
    platform_velocity = [{"platform": r[0], "total_90d": r[1], "last_7d": r[2], "last_30d": r[3]} for r in platform_timing]

    # Best apply window
    best_day = max(posting_by_day, key=lambda x: x["count"])["day"] if posting_by_day else "Tuesday"
    peak_hours = sorted(posting_by_hour, key=lambda x: x["count"], reverse=True)[:3]
    peak_hour_str = ", ".join([f"{h['hour']}:00" for h in peak_hours]) if peak_hours else "9:00-11:00"

    return {
        "posting_by_day": posting_by_day,
        "posting_by_hour": posting_by_hour,
        "freshness_distribution": freshness,
        "avg_review_hours": round(float(avg_hours), 1),
        "platform_velocity": platform_velocity,
        "recommendations": {
            "best_day": best_day,
            "peak_posting_hours": peak_hour_str,
            "ideal_apply_window": "Apply within 24-48 hours of posting for best results",
            "fastest_platforms": [p["platform"] for p in platform_velocity[:3]],
        },
    }


# ── Networking Suggestions ───────────────────────────────────────────────────

@router.get("/networking")
async def networking_suggestions(
    job_id: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Suggest contacts to connect with based on accepted jobs or a specific job."""
    if job_id:
        # Specific job: find contacts at that company
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
        if not job:
            return {"suggestions": [], "error": "Job not found"}

        contacts = (await db.execute(
            select(CompanyContact, Company.name)
            .join(Company, CompanyContact.company_id == Company.id)
            .where(CompanyContact.company_id == job.company_id)
            .order_by(
                CompanyContact.is_decision_maker.desc(),
                CompanyContact.email_status.asc(),  # valid first
                CompanyContact.confidence_score.desc(),
            )
        )).all()

        suggestions = []
        for contact, company_name in contacts:
            relevance = _contact_relevance(contact, job)
            suggestions.append({
                "contact_id": str(contact.id),
                "name": f"{contact.first_name} {contact.last_name}".strip(),
                "title": contact.title,
                "company": company_name,
                "email": contact.email,
                "email_status": contact.email_status,
                "linkedin_url": contact.linkedin_url,
                "is_decision_maker": contact.is_decision_maker,
                "outreach_status": contact.outreach_status,
                "relevance_reason": relevance["reason"],
                "relevance_score": relevance["score"],
                "suggested_approach": relevance["approach"],
            })

        suggestions.sort(key=lambda x: x["relevance_score"], reverse=True)
        return {"suggestions": suggestions[:10], "job_title": job.title, "company_id": str(job.company_id)}

    else:
        # General: top contacts across accepted/pipeline companies
        result = await db.execute(text("""
            SELECT c.id, c.first_name, c.last_name, c.title, c.email, c.email_status,
                   c.linkedin_url, c.is_decision_maker, c.outreach_status, c.confidence_score,
                   co.name AS company_name, co.id AS company_id,
                   COUNT(j.id) AS open_roles,
                   MAX(j.relevance_score) AS top_score
            FROM company_contacts c
            JOIN companies co ON c.company_id = co.id
            JOIN jobs j ON j.company_id = co.id AND j.status IN ('new', 'accepted', 'under_review')
            WHERE c.email_status IN ('valid', 'catch_all')
              AND c.outreach_status = 'not_contacted'
            GROUP BY c.id, c.first_name, c.last_name, c.title, c.email, c.email_status,
                     c.linkedin_url, c.is_decision_maker, c.outreach_status, c.confidence_score,
                     co.name, co.id
            ORDER BY c.is_decision_maker DESC, top_score DESC, open_roles DESC
            LIMIT 20
        """))

        suggestions = []
        for r in result:
            suggestions.append({
                "contact_id": str(r.id),
                "name": f"{r.first_name} {r.last_name}".strip(),
                "title": r.title,
                "company": r.company_name,
                "company_id": str(r.company_id),
                "email": r.email,
                "email_status": r.email_status,
                "linkedin_url": r.linkedin_url,
                "is_decision_maker": r.is_decision_maker,
                "outreach_status": r.outreach_status,
                "open_roles": r.open_roles,
                "top_relevance_score": round(float(r.top_score), 1),
                "relevance_reason": "Decision maker" if r.is_decision_maker else f"{r.open_roles} open roles, score {round(float(r.top_score))}",
                "suggested_approach": "Reach out via LinkedIn first, then email" if r.linkedin_url else "Send a personalized email",
            })

        return {"suggestions": suggestions}


def _contact_relevance(contact: CompanyContact, job: Job) -> dict:
    """Score contact relevance for a specific job."""
    score = 50
    reasons = []
    approach = "Send a personalized email"

    if contact.is_decision_maker:
        score += 30
        reasons.append("Decision maker with budget authority")
    if contact.email_status == "valid":
        score += 10
        reasons.append("Verified email")
    if contact.linkedin_url:
        score += 5
        reasons.append("LinkedIn available")
        approach = "Connect on LinkedIn first, then follow up via email"

    title_lower = (contact.title or "").lower()
    if any(kw in title_lower for kw in ["vp", "director", "head of", "chief", "cto", "ciso"]):
        score += 15
        reasons.append("Senior leadership role")
    elif any(kw in title_lower for kw in ["manager", "lead", "principal"]):
        score += 10
        reasons.append("Hiring manager level")
    elif any(kw in title_lower for kw in ["recruiter", "talent", "people"]):
        score += 5
        reasons.append("Talent/recruiting team")
        approach = "Apply first, then reach out mentioning your application"

    return {
        "score": min(score, 100),
        "reason": "; ".join(reasons) if reasons else "Relevant contact at hiring company",
        "approach": approach,
    }
