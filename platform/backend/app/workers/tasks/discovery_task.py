"""Company discovery task -- find new companies via ATS sitemaps and slug probing."""

import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.workers.tasks._db import SyncSession
from app.models.discovery import DiscoveryRun, DiscoveredCompany
from app.models.company import Company, CompanyATSBoard
from app.utils.scan_lock import release_scan_lock

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
USER_AGENT = "JobPlatformBot/1.0 (+https://github.com/your-org/job-platform)"

# ---------------------------------------------------------------------------
# Known slug patterns to probe on various platforms
# ---------------------------------------------------------------------------

LEVER_PROBE_SLUGS = [
    "superside", "omilia", "yassir", "reap", "masabi",
    "zapier", "gitlab", "hashicorp", "elastic", "datadog",
    "snyk", "tailscale", "dbt-labs", "fly-io", "render",
    "planetscale", "grafana-labs", "temporal-technologies",
    "supabase", "airbyte", "pulumi", "cockroach-labs",
    "chainguard", "teleport", "lacework", "orca-security",
]

ASHBY_PROBE_SLUGS = [
    "superside", "omilia", "yassir", "ramp", "notion",
    "linear", "vercel", "resend", "cal-com", "plain",
    "dopt", "mintlify", "graphite", "codeium",
    "replit", "railway", "neon", "turso",
]

WELLFOUND_PROBE_SLUGS = [
    "superside", "omilia", "yassir", "zapier", "figma",
    "notion", "linear", "vercel", "supabase", "dbt-labs",
    "snyk", "tailscale", "render", "fly-io", "planetscale",
    "temporal", "pulumi", "teleport", "grafana-labs",
    "hashicorp", "gitlab", "airbyte", "neon",
]

SMARTRECRUITERS_PROBE_SLUGS = [
    "Visa", "Bosch", "SUSE", "Schwarz-Group", "Adidas",
    "DHL", "Siemens", "McDonalds", "Spotify", "Booking",
    "TUI", "Philips", "ING", "ABB",
]

RECRUITEE_PROBE_SLUGS = [
    "superside", "huntr", "toggl", "deel", "remote-com",
    "remote", "omnipresent", "oyster", "velocity-global",
    "papaya-global", "lano", "multiplier",
]

BAMBOOHR_PROBE_SLUGS = [
    "toggl", "hotjar", "buffer", "uservoice", "aha",
    "linode", "ghost", "sonatype", "zapier", "loom",
]

JOBVITE_PROBE_SLUGS = [
    "twilio", "zendesk", "unity", "pagerduty", "rapid7",
    "fortinet", "talend", "tripactions", "forescout", "sailpoint",
]

HIMALAYAS_PROBE_SLUGS = [
    "gitlab", "zapier", "deel", "remote", "omnipresent",
    "superside", "toptal", "automattic", "canonical", "elastic",
]

# LinkedIn company page slugs (used for both RapidAPI and public search fallback)
# Focus on infra, DevOps, cloud, and security companies hiring remote
LINKEDIN_PROBE_SLUGS = [
    # Cloud / Infrastructure leaders
    "cloudflare", "datadog", "hashicorp", "elastic", "grafana-labs",
    "mongodb", "cockroach-labs", "planetscale", "neon-inc", "supabase",
    "vercel", "netlify", "render", "fly-io", "railway",
    "pulumi", "spacelift", "env0", "terraform",
    # DevOps / SRE / Platform
    "gitlab", "circleci", "buildkite", "dagger-io", "harness-io",
    "launchdarkly", "split-software", "flagsmith",
    "pagerduty", "opsgenie", "incident-io", "firehydrant",
    # Security
    "snyk", "wiz-inc", "orca-security", "lacework", "chainguard",
    "teleport", "tailscale", "crowdstrike", "palo-alto-networks",
    "fortinet", "rapid7", "tenable", "qualys",
    "sentinelone", "cyberark", "sailpoint-technologies",
    "1password", "bitwarden",
    # Remote-first / Global remote
    "zapier", "automattic", "canonical", "toptal", "remote",
    "deel", "omnipresent", "oyster-hr", "papaya-global",
    "superside", "toggl", "buffer", "doist",
    # Big tech (reference, high volume)
    "google", "microsoft", "amazon", "meta", "apple",
    "stripe", "twilio", "confluent",
]


def _crawl_greenhouse_sitemap(session, run: DiscoveryRun) -> int:
    """Crawl the Greenhouse public sitemap to discover new company board slugs."""
    sitemap_url = "https://boards.greenhouse.io/sitemap.xml"
    new_count = 0

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(sitemap_url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

        root = ET.fromstring(resp.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = root.findall(".//sm:url/sm:loc", ns)

        seen_slugs: set[str] = set()
        for loc in urls:
            text = loc.text or ""
            parts = text.replace("https://boards.greenhouse.io/", "").split("/")
            if parts and parts[0]:
                seen_slugs.add(parts[0])

        existing = session.execute(
            select(DiscoveredCompany.slug).where(
                DiscoveredCompany.platform == "greenhouse"
            )
        ).scalars().all()
        existing_set = set(existing)

        for slug in seen_slugs:
            if slug in existing_set:
                continue
            company = DiscoveredCompany(
                id=uuid.uuid4(),
                discovery_run_id=run.id,
                name=slug.replace("-", " ").title(),
                platform="greenhouse",
                slug=slug,
                careers_url=f"https://boards.greenhouse.io/{slug}",
                status="new",
            )
            session.add(company)
            new_count += 1

        session.flush()
        logger.info("Greenhouse sitemap: %d total slugs, %d new", len(seen_slugs), new_count)

    except Exception as e:
        logger.error("Greenhouse sitemap crawl failed: %s", e)

    return new_count


def _probe_platform_slugs(session, run: DiscoveryRun, platform: str, slugs: list[str], url_template: str) -> int:
    """Generic slug prober for any platform with a public API."""
    new_count = 0
    existing = set(
        session.execute(
            select(DiscoveredCompany.slug).where(DiscoveredCompany.platform == platform)
        ).scalars().all()
    )

    with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for slug in slugs:
            if slug in existing:
                continue
            url = url_template.format(slug=slug)
            try:
                resp = client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                if resp.status_code == 200:
                    # Verify it actually returns data
                    try:
                        data = resp.json()
                        # Different platforms return different structures
                        has_data = bool(data)
                        if isinstance(data, dict):
                            has_data = bool(
                                data.get("jobs") or data.get("content") or
                                data.get("offers") or data.get("requisitions") or
                                data.get("result") or data.get("data")
                            )
                    except Exception:
                        has_data = False

                    if has_data:
                        from app.schemas.company import ATS_URL_PATTERNS
                        careers_pattern = ATS_URL_PATTERNS.get(platform, "")
                        careers_url = careers_pattern.format(slug=slug) if careers_pattern else url

                        company = DiscoveredCompany(
                            id=uuid.uuid4(),
                            discovery_run_id=run.id,
                            name=slug.replace("-", " ").title(),
                            platform=platform,
                            slug=slug,
                            careers_url=careers_url,
                            status="new",
                        )
                        session.add(company)
                        new_count += 1
            except Exception as e:
                logger.debug("%s probe failed for %s: %s", platform, slug, e)

    session.flush()
    logger.info("%s probe: %d slugs checked, %d new", platform, len(slugs), new_count)
    return new_count


# Platform API URL templates for slug probing
PLATFORM_PROBE_CONFIG = {
    "lever": {
        "slugs": LEVER_PROBE_SLUGS,
        "url": "https://api.lever.co/v0/postings/{slug}",
    },
    "ashby": {
        "slugs": ASHBY_PROBE_SLUGS,
        "url": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    },
    "wellfound": {
        "slugs": WELLFOUND_PROBE_SLUGS,
        "url": "https://wellfound.com/company/{slug}/jobs",
    },
    "smartrecruiters": {
        "slugs": SMARTRECRUITERS_PROBE_SLUGS,
        "url": "https://api.smartrecruiters.com/v1/companies/{slug}/postings",
    },
    "recruitee": {
        "slugs": RECRUITEE_PROBE_SLUGS,
        "url": "https://{slug}.recruitee.com/api/offers",
    },
    "bamboohr": {
        "slugs": BAMBOOHR_PROBE_SLUGS,
        "url": "https://{slug}.bamboohr.com/careers/list",
    },
    "jobvite": {
        "slugs": JOBVITE_PROBE_SLUGS,
        "url": "https://jobs.jobvite.com/{slug}/jobs",
    },
    "himalayas": {
        "slugs": HIMALAYAS_PROBE_SLUGS,
        "url": "https://himalayas.app/jobs/api?company_slug={slug}&limit=1",
    },
}


def _probe_linkedin_slugs(session, run: DiscoveryRun) -> int:
    """Probe LinkedIn company slugs. LinkedIn doesn't return JSON, so we just
    register the slug if it's in our probe list (we know these companies exist).
    The actual job fetching happens via the LinkedInFetcher during scan time."""
    new_count = 0
    existing = set(
        session.execute(
            select(DiscoveredCompany.slug).where(DiscoveredCompany.platform == "linkedin")
        ).scalars().all()
    )

    for slug in LINKEDIN_PROBE_SLUGS:
        if slug in existing:
            continue
        company = DiscoveredCompany(
            id=uuid.uuid4(),
            discovery_run_id=run.id,
            name=slug.replace("-", " ").title(),
            platform="linkedin",
            slug=slug,
            careers_url=f"https://www.linkedin.com/company/{slug}/jobs",
            status="new",
        )
        session.add(company)
        new_count += 1

    session.flush()
    logger.info("LinkedIn probe: %d slugs registered, %d new", len(LINKEDIN_PROBE_SLUGS), new_count)
    return new_count


@celery_app.task(name="app.workers.tasks.discovery_task.run_discovery", bind=True, max_retries=1)
def run_discovery(self, run_id: str | None = None):
    """Run a full discovery cycle: Greenhouse sitemap + multi-platform slug probes.

    Regression finding 186: `POST /discovery/runs` on the API side was
    creating a `DiscoveryRun` row with `status="pending"` and
    commenting "the actual discovery is executed by the background
    worker that picks up runs with status='pending'" — but no such
    polling worker existed. This task always created a fresh row
    with `status="running"` and ignored any pending rows, so every
    manual trigger from the admin UI left an orphan pending row that
    aged indefinitely (3 found aged 3+ hours during regression
    testing). Fix: accept an optional `run_id` from the API caller
    and re-use that row instead of creating a new one. The scheduled
    (cron) path still calls with no arg and creates its own row.
    """
    logger.info("Starting run_discovery run_id=%s", run_id)
    session = SyncSession()

    try:
        run = None
        if run_id:
            # F186: called from the API handler — it already inserted
            # a pending row. Flip it to running and re-use it so we
            # don't accumulate orphans.
            run = session.execute(
                select(DiscoveryRun).where(DiscoveryRun.id == run_id)
            ).scalar_one_or_none()
            if run is not None:
                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
                session.flush()
            else:
                logger.warning(
                    "run_discovery called with run_id=%s but row not found — "
                    "creating a fresh row instead",
                    run_id,
                )

        if run is None:
            run = DiscoveryRun(
                id=uuid.uuid4(),
                source="scheduled",
                status="running",
            )
            session.add(run)
            session.flush()

        total_new = 0

        # Greenhouse sitemap
        gh_new = _crawl_greenhouse_sitemap(session, run)
        total_new += gh_new

        # Probe all platforms
        for platform, config in PLATFORM_PROBE_CONFIG.items():
            platform_new = _probe_platform_slugs(
                session, run, platform, config["slugs"], config["url"]
            )
            total_new += platform_new

        # LinkedIn (special handler — no JSON probe, just register known slugs)
        li_new = _probe_linkedin_slugs(session, run)
        total_new += li_new

        # Count total discovered in this run
        total_found = session.execute(
            select(DiscoveredCompany)
            .where(DiscoveredCompany.discovery_run_id == run.id)
        ).scalars().all()
        total_found_count = len(total_found)

        run.completed_at = datetime.now(timezone.utc)
        run.companies_found = total_found_count
        run.new_companies = total_new
        run.status = "completed"
        session.commit()

        logger.info(
            "run_discovery complete: %d found, %d new",
            total_found_count, total_new,
        )
        return {"found": total_found_count, "new": total_new}

    except Exception as e:
        logger.exception("run_discovery failed: %s", e)
        session.rollback()
        raise self.retry(exc=e, countdown=300)
    finally:
        session.close()


@celery_app.task(name="app.workers.tasks.discovery_task.discover_and_add_boards", bind=True, max_retries=1)
def discover_and_add_boards(self):
    """Discovery + auto-add: Find new company boards and automatically add them to scanning.

    This is the separate platform discovery scan job that:
    1. Runs discovery to find new companies
    2. Automatically creates Company + CompanyATSBoard records for discovered companies
    3. Makes them immediately available for the next scan cycle
    """
    logger.info("Starting discover_and_add_boards")
    session = SyncSession()

    try:
        # First run discovery
        run = DiscoveryRun(
            id=uuid.uuid4(),
            source="auto_add",
            status="running",
        )
        session.add(run)
        session.flush()

        total_new_discovered = 0

        # Greenhouse sitemap
        gh_new = _crawl_greenhouse_sitemap(session, run)
        total_new_discovered += gh_new

        # Probe all platforms
        for platform, config in PLATFORM_PROBE_CONFIG.items():
            platform_new = _probe_platform_slugs(
                session, run, platform, config["slugs"], config["url"]
            )
            total_new_discovered += platform_new

        # LinkedIn (special handler)
        li_new = _probe_linkedin_slugs(session, run)
        total_new_discovered += li_new

        session.commit()

        # Now auto-add newly discovered companies as boards
        new_discoveries = session.execute(
            select(DiscoveredCompany).where(
                DiscoveredCompany.discovery_run_id == run.id,
                DiscoveredCompany.status == "new",
            )
        ).scalars().all()

        boards_added = 0
        for disc in new_discoveries:
            # Check if board already exists
            existing_board = session.execute(
                select(CompanyATSBoard).where(
                    CompanyATSBoard.platform == disc.platform,
                    CompanyATSBoard.slug == disc.slug,
                )
            ).scalar_one_or_none()

            if existing_board:
                disc.status = "duplicate"
                continue

            # Find or create company
            company = session.execute(
                select(Company).where(Company.slug == disc.slug)
            ).scalar_one_or_none()

            if not company:
                company = Company(
                    id=uuid.uuid4(),
                    name=disc.name,
                    slug=disc.slug,
                    website=disc.careers_url or "",
                    is_target=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(company)
                session.flush()

            # Create ATS board
            board = CompanyATSBoard(
                id=uuid.uuid4(),
                company_id=company.id,
                platform=disc.platform,
                slug=disc.slug,
                is_active=True,
            )
            session.add(board)
            disc.status = "added"
            boards_added += 1

        run.completed_at = datetime.now(timezone.utc)
        run.companies_found = len(new_discoveries)
        run.new_companies = boards_added
        run.status = "completed"
        session.commit()

        logger.info(
            "discover_and_add_boards complete: %d discovered, %d boards added",
            len(new_discoveries), boards_added,
        )
        return {
            "discovered": len(new_discoveries),
            "boards_added": boards_added,
            "total_new_discovered": total_new_discovered,
        }

    except Exception as e:
        logger.exception("discover_and_add_boards failed: %s", e)
        session.rollback()
        raise self.retry(exc=e, countdown=300)
    finally:
        session.close()
        # Finding 82: release the discovery lock acquired by
        # POST /platforms/scan/discover. 2-hour TTL safety valve
        # covers the slow-probe case; explicit release handles the
        # normal (successful / failed / retried) path.
        release_scan_lock("discover")
