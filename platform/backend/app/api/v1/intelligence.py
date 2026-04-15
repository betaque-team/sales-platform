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

# Currency symbols → ISO code. Unambiguous symbols only — `$` is omitted
# because it's used by USD / CAD / AUD / NZD / HKD / SGD / MXN and we can't
# disambiguate from the symbol alone.
_CURRENCY_SYMBOLS = {
    "£": "GBP", "€": "EUR", "¥": "JPY",
    "₹": "INR", "₽": "RUB", "₩": "KRW",
    "₺": "TRY", "₪": "ILS", "₴": "UAH",
}

# ISO currency codes we look for. Checked with a word-boundary regex on the
# lowercased salary string BEFORE space-stripping, so "INR 50000" matches
# but a hypothetical substring like "usdcad" inside a longer word wouldn't.
# Order in the regex alternation doesn't matter — only the first match is
# used and they're all 3-letter codes.
_CURRENCY_CODES = (
    "usd", "gbp", "eur", "cad", "aud", "nzd", "sgd", "hkd",
    "jpy", "inr", "cny", "krw", "zar", "brl", "mxn", "clp",
    "chf", "pln", "czk", "huf", "ron", "bgn", "hrk", "try",
    "dkk", "sek", "nok", "isk", "ils", "aed", "sar",
)
_CURRENCY_CODE_RE = re.compile(r"\b(" + "|".join(_CURRENCY_CODES) + r")\b")


def _parse_salary(salary_str: str) -> dict | None:
    """Parse salary string into structured data.

    Regression finding 66: previously only GBP and EUR were detected; every
    other currency (DKK / SEK / NOK / CAD / AUD / SGD / JPY / INR / …)
    defaulted to `"USD"`. One live example, `"DKK 780000 - 960000"`, was
    reported as $870,000 USD (~8× over the real ~$112k). We now detect a
    broader ISO-code allow-list and the common currency symbols. The
    aggregator in `salary_insights()` then excludes non-USD entries from
    the USD-labelled rollups (avg / median / top-paying) rather than
    converting — FX rates drift, and we'd rather be conservative than
    wrong. Per-currency rollups are still available on demand.
    """
    if not salary_str:
        return None
    raw_lower = salary_str.lower()
    s = raw_lower.replace(",", "").replace(" ", "")

    # Detect currency — ISO codes first (unambiguous word-boundary match
    # against the un-stripped lowercased input), then symbol chars.
    currency = "USD"
    code_match = _CURRENCY_CODE_RE.search(raw_lower)
    if code_match:
        currency = code_match.group(1).upper()
    else:
        for symbol, code in _CURRENCY_SYMBOLS.items():
            if symbol in salary_str:
                currency = code
                break

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
    include_other: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse and aggregate salary data across all jobs with salary info.

    Regression finding 67: the default used to aggregate *every* job with
    a salary range, not just those in the user's target clusters. 95% of
    the resulting `overall` stats came from `role_cluster="other"` rows
    (875/917 in the live sample), making the "salary insights for your
    target roles" framing of the Intelligence page misleading. Default is
    now `relevance_score > 0` (same filter the Skill Gap and Jobs pages
    apply) — pass `include_other=true` to get the old full-DB view, e.g.
    for admin diagnostics.
    """
    query = select(Job.salary_range, Job.role_cluster, Job.geography_bucket, Job.title, Company.name).join(
        Company, Job.company_id == Company.id
    ).where(Job.salary_range != "", Job.salary_range.isnot(None))

    if not include_other:
        query = query.where(Job.relevance_score > 0)
    if role_cluster:
        query = query.where(Job.role_cluster == role_cluster)
    if geography:
        query = query.where(Job.geography_bucket == geography)

    result = await db.execute(query.limit(1000))
    rows = result.all()

    parsed = []
    by_cluster: dict[str, list] = {}
    by_geography: dict[str, list] = {}
    non_usd_samples: list[dict] = []

    for salary_str, cluster, geo, title, company_name in rows:
        p = _parse_salary(salary_str)
        if not p or p["mid"] < 20000 or p["mid"] > 1000000:  # filter outliers
            continue
        entry = {**p, "role_cluster": cluster, "geography": geo, "title": title, "company": company_name, "raw": salary_str}
        # Regression finding 66: only USD entries feed the USD-labelled
        # rollups (by_cluster / by_geography / buckets / top_paying /
        # overall avg-median). Non-USD rows go into a separate sample so
        # they're visible to the caller but can't silently inflate the
        # USD averages (DKK 870k being reported as $870k).
        if p["currency"] != "USD":
            non_usd_samples.append(entry)
            continue
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

    # Regression finding 66: summarise non-USD entries so the caller can
    # tell they exist without letting them pollute the USD stats above.
    # Grouped by currency and capped per-group so a long list of JPY rows
    # can't blow up the response size.
    non_usd_by_currency: dict[str, list[dict]] = {}
    for e in non_usd_samples:
        non_usd_by_currency.setdefault(e["currency"], []).append(e)

    return {
        "overall": _stats(all_mids),
        "by_cluster": {k: _stats(v) for k, v in by_cluster.items()},
        "by_geography": {k: _stats(v) for k, v in by_geography.items()},
        "distribution": [{"range": k, "count": v} for k, v in buckets.items()],
        "top_paying": sorted(parsed, key=lambda x: x["mid"], reverse=True)[:15],
        "total_with_salary": len(parsed),
        "total_non_usd_excluded": len(non_usd_samples),
        "non_usd_samples_by_currency": {
            # Keep a handful of examples per currency so the UI can label
            # a "DKK / EUR / GBP salaries not included" disclosure.
            cur: sorted(entries, key=lambda x: x["mid"], reverse=True)[:5]
            for cur, entries in non_usd_by_currency.items()
        },
        "total_jobs": (await db.execute(select(func.count(Job.id)))).scalar() or 0,
    }


# ── Application Timing Intelligence ──────────────────────────────────────────

@router.get("/timing")
async def timing_intelligence(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze job posting patterns to find optimal application timing."""
    # Regression finding 26: using `first_seen_at` skewed this heavily toward
    # Sunday because bulk seed / discovery runs happened to kick off on
    # Sundays and each imported thousands of jobs with an identical
    # `first_seen_at`. What users actually want to know is when *job
    # posters* publish — use `posted_at` (set by the upstream ATS) and
    # fall back only when it is missing. We also exclude jobs whose
    # `posted_at` matches `first_seen_at` to the second, because those
    # are rows where the ATS didn't return a posted date and the scanner
    # backfilled with NOW() at ingest time.
    #
    # Regression finding 65: the per-second heuristic above was not tight
    # enough — seed-run rows often diverged by a few seconds between
    # `posted_at` and `first_seen_at` (scanner writes them sequentially
    # in the same upsert), and Sunday still dominated 4.3× the next day.
    # Two additional guards here:
    #   (a) widen the per-second match to per-minute (`> 60`), catching
    #       sub-minute scanner back-fills that slipped through.
    #   (b) exclude any job whose `first_seen_at` falls inside a bulk
    #       scan-log window (`new_jobs > 1000` — a scan that ingested
    #       that much at once is almost certainly a seed/discovery run,
    #       not a routine incremental poll). The NOT EXISTS subquery is
    #       on an indexed column (`first_seen_at`) so the planner can
    #       range-scan; at ~13k jobs this is fast.
    _SEED_RUN_EXCLUSION = """
        AND NOT EXISTS (
            SELECT 1 FROM scan_logs s
            WHERE s.new_jobs > 1000
              AND jobs.first_seen_at BETWEEN s.started_at AND COALESCE(s.completed_at, s.started_at + INTERVAL '1 hour')
        )
    """

    dow_result = await db.execute(text(f"""
        SELECT EXTRACT(DOW FROM posted_at) AS dow, COUNT(*) AS cnt
        FROM jobs
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - INTERVAL '90 days'
          AND ABS(EXTRACT(EPOCH FROM (posted_at - first_seen_at))) > 60
          {_SEED_RUN_EXCLUSION}
        GROUP BY dow ORDER BY dow
    """))
    days_of_week = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    posting_by_day = [{"day": days_of_week[int(r[0])], "count": r[1]} for r in dow_result]

    # Jobs posted by hour — same rationale as above.
    hour_result = await db.execute(text(f"""
        SELECT EXTRACT(HOUR FROM posted_at) AS hr, COUNT(*) AS cnt
        FROM jobs
        WHERE posted_at IS NOT NULL
          AND posted_at >= NOW() - INTERVAL '90 days'
          AND ABS(EXTRACT(EPOCH FROM (posted_at - first_seen_at))) > 60
          {_SEED_RUN_EXCLUSION}
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

# Regression finding 27: the contact enrichment pipeline has been saving
# rows where two page elements got glued together — e.g. `first_name =
# "Gartner"` / `last_name = "PeerInsights"`, or `title = "Wade BillingsVP,
# Technology Services, Instructure"`. The email field was then synthesized
# as `first-word@company-domain`, so users were seeing fabricated addresses
# in outreach suggestions. We filter these out at the API layer so the UI
# stops showing them while the enrichment pipeline itself is repaired
# upstream. Heuristics are deliberately conservative — we'd rather drop a
# real contact than include a corrupted one for outreach.

_COMMA_OR_PIPE = re.compile(r"[,|\t;]")

# Regression finding 64 (extends finding 60): stop-word name filter
# cross-referenced from `services/enrichment/internal_provider`. Kept in
# lockstep with that set — if one grows, the other should too. Exists
# here as a belt-and-suspenders layer in case a future ingest bug lets
# stop-word "names" bypass the enrichment-time filter. Lowercased for
# comparison.
_NAME_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "both", "by",
    "complex", "each", "for", "from", "help", "here", "how", "if",
    "in", "is", "it", "its", "join", "just", "learn", "let", "more",
    "motivated", "now", "of", "on", "or", "our", "read", "should",
    "team", "that", "the", "their", "them", "they", "this", "to",
    "us", "very", "was", "we", "were", "what", "when", "where",
    "who", "with", "you", "your",
})


def _looks_like_corrupted_contact(first_name: str, last_name: str, title: str) -> bool:
    """Return True if this row looks like glued-together scraped strings."""
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    tt = (title or "").strip()

    # Missing given name is unusable for outreach.
    if not fn:
        return True

    # Name fields should never contain commas / pipes / tabs — those are
    # strong signals that multiple page elements were concatenated.
    if _COMMA_OR_PIPE.search(fn) or _COMMA_OR_PIPE.search(ln):
        return True

    # Titles longer than ~120 chars are almost always two roles glued
    # together ("Wade BillingsVP, Technology Services, Instructure").
    if len(tt) > 120:
        return True

    # Titles that contain a company name separator AND a non-role fragment
    # after it ("VP, <team>, <company>") — three comma-separated segments
    # with the last looking like a proper noun.
    parts = [p.strip() for p in tt.split(",") if p.strip()]
    if len(parts) >= 3:
        return True

    # Regression finding 64: extend the internal-caps check to BOTH name
    # parts. Prior version only inspected `fn`, so `{first:"Wade",
    # last:"BillingsVP"}` sailed through — "Wade" has 0 internal caps,
    # and "BillingsVP" was never examined. Additionally, the threshold
    # was `>= 2`, which missed single-cap corruptions like
    # `{first:"Gartner", last:"PeerInsights"}` (the exact example in
    # this function's docstring: "PeerInsights" has only 1 internal cap
    # at position 4).
    #
    # Observation about real names with internal caps: Mc/Mac/De/La/Le/Di/
    # Van/O' prefixes all place the internal cap at position ≤ 3 (short
    # prefix + capital). A single internal cap at position ≥ 4 within a
    # single alpha run is almost always two dictionary words glued
    # together from a bad scrape. Two internal caps anywhere in the same
    # alpha run is also corruption (BillingsVP, WallStreet).
    #
    # Split on non-alpha separators first so that hyphenated names
    # ("Jean-Luc") and apostrophe names ("O'Connor") are evaluated
    # sub-token by sub-token — the separator resets the "word start"
    # position, just like whitespace would.
    def _has_suspicious_caps(part: str) -> bool:
        sub_tokens = re.split(r"[^A-Za-z]+", part)
        for tok in sub_tokens:
            if not tok:
                continue
            cap_positions = [i for i, c in enumerate(tok) if i > 0 and c.isupper()]
            if len(cap_positions) >= 2:
                return True
            if len(cap_positions) == 1 and cap_positions[0] >= 4:
                return True
        return False

    for part in (fn, ln):
        if _has_suspicious_caps(part):
            return True

    # Regression finding 64: English stop-word tokens ("help", "you", "us"
    # etc.) should never appear as a "name" — if one did, it came from the
    # enrichment regex bug fixed under finding 60 and is noise for outreach.
    # Kept here as a read-time safety net in case any future ingest path
    # skips the new `_looks_like_real_name()` filter upstream.
    if fn.lower() in _NAME_STOPWORDS or (ln and ln.lower() in _NAME_STOPWORDS):
        return True

    return False


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
            if _looks_like_corrupted_contact(contact.first_name, contact.last_name, contact.title or ""):
                continue
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
            LIMIT 60
        """))

        suggestions = []
        for r in result:
            if _looks_like_corrupted_contact(r.first_name, r.last_name, r.title or ""):
                continue
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

        # Trim to the 20 the UI expects — we pulled up to 60 candidates
        # above so the corrupted-row filter couldn't starve the list.
        return {"suggestions": suggestions[:20]}


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
