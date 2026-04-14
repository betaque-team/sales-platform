"""Seed companies and ATS boards from job-monitor config.yaml into PostgreSQL."""

import asyncio
import uuid
from datetime import datetime, timezone

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.company import Company, CompanyATSBoard
from app.models.rule import RoleRule
from app.models.scan import CareerPageWatch

settings = get_settings()


def slugify(name: str) -> str:
    """Simple slug: lowercase, replace spaces/special chars with hyphens."""
    return name.lower().replace(" ", "-").replace(".", "-").replace("_", "-").strip("-")


async def seed():
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Load config.yaml from mounted path or local
    import os
    config_path = os.environ.get("CONFIG_PATH", "/data/config.yaml")
    if not os.path.exists(config_path):
        # Try relative paths
        for p in ["config.yaml", "../job-monitor/config.yaml", "/app/config.yaml"]:
            if os.path.exists(p):
                config_path = p
                break

    print(f"Loading config from: {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    platforms = config.get("platforms", {})
    career_pages = config.get("career_pages", {})
    role_keywords = config.get("role_keywords", [])

    async with async_session() as session:
        # --- Seed role rules ---
        existing_rules = await session.execute(select(RoleRule))
        if not existing_rules.scalars().first():
            # Group keywords by cluster
            infra_kws = [kw for kw in role_keywords if not any(s in kw for s in ["security", "soc", "devsecops", "compliance", "grc", "pentest", "incident", "red team"])]
            sec_kws = [kw for kw in role_keywords if any(s in kw for s in ["security", "soc", "devsecops", "compliance", "grc", "pentest", "incident", "red team"])]

            if infra_kws:
                session.add(RoleRule(id=uuid.uuid4(), cluster="infra", base_role="infra", keywords=infra_kws, is_active=True))
            if sec_kws:
                session.add(RoleRule(id=uuid.uuid4(), cluster="security", base_role="security", keywords=sec_kws, is_active=True))
            await session.flush()
            print(f"  Seeded role rules: {len(infra_kws)} infra keywords, {len(sec_kws)} security keywords")
        else:
            print("  Role rules already exist, skipping")

        # --- Seed companies from ATS platforms ---
        company_cache = {}  # name -> Company
        boards_created = 0
        companies_created = 0

        for platform_name, slug_map in platforms.items():
            for ats_slug, company_name in slug_map.items():
                # Find or create company
                name_key = company_name.strip().lower()
                if name_key not in company_cache:
                    existing = await session.execute(
                        select(Company).where(Company.name == company_name.strip())
                    )
                    company = existing.scalar_one_or_none()
                    if not company:
                        company = Company(
                            id=uuid.uuid4(),
                            name=company_name.strip(),
                            slug=slugify(company_name.strip()),
                            is_target=False,
                            created_at=datetime.now(timezone.utc),
                        )
                        session.add(company)
                        await session.flush()
                        companies_created += 1
                    company_cache[name_key] = company

                company = company_cache[name_key]

                # Check if board already exists
                existing_board = await session.execute(
                    select(CompanyATSBoard).where(
                        CompanyATSBoard.company_id == company.id,
                        CompanyATSBoard.platform == platform_name,
                        CompanyATSBoard.slug == ats_slug,
                    )
                )
                if not existing_board.scalar_one_or_none():
                    session.add(CompanyATSBoard(
                        id=uuid.uuid4(),
                        company_id=company.id,
                        platform=platform_name,
                        slug=ats_slug,
                        is_active=True,
                    ))
                    boards_created += 1

        await session.flush()
        print(f"  Seeded {companies_created} companies, {boards_created} ATS boards")

        # --- Seed career pages ---
        pages_created = 0
        for url, company_name in career_pages.items():
            name_key = company_name.strip().lower()
            company = company_cache.get(name_key)

            if not company:
                existing = await session.execute(
                    select(Company).where(Company.name == company_name.strip())
                )
                company = existing.scalar_one_or_none()
                if not company:
                    company = Company(
                        id=uuid.uuid4(),
                        name=company_name.strip(),
                        slug=slugify(company_name.strip()),
                        is_target=False,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(company)
                    await session.flush()
                    companies_created += 1
                company_cache[name_key] = company

            existing_page = await session.execute(
                select(CareerPageWatch).where(CareerPageWatch.url == url)
            )
            if not existing_page.scalar_one_or_none():
                session.add(CareerPageWatch(
                    id=uuid.uuid4(),
                    company_id=company.id,
                    url=url,
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                ))
                pages_created += 1

        await session.commit()
        print(f"  Seeded {pages_created} career page watches")
        print(f"\nTotal: {companies_created} companies, {boards_created} boards, {pages_created} career pages")

    await engine.dispose()


async def seed_role_cluster_configs():
    """Seed RoleClusterConfig rows matching the hardcoded keywords in _role_matching.py."""
    from app.models.role_config import RoleClusterConfig

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        existing = (await session.execute(select(RoleClusterConfig))).scalars().all()
        existing_names = {r.name for r in existing}

        clusters = [
            {
                "name": "infra",
                "display_name": "Infrastructure / Cloud / DevOps / SRE",
                "keywords": "devops,cloud,infrastructure,sre,site reliability,platform engineer,platform engineering,kubernetes,docker,terraform,ansible,aws engineer,azure engineer,gcp engineer,linux,systems engineer,systems administrator,network engineer,network administrator,reliability engineer,release engineer,monitoring,observability,ci/cd,cicd,build engineer,finops,mlops,dataops",
                "approved_roles": "DevOps Engineer,Cloud Engineer,Infrastructure Engineer,Site Reliability Engineer",
                "sort_order": 1,
            },
            {
                "name": "security",
                "display_name": "Security / Compliance / DevSecOps",
                "keywords": "security,devsecops,soc,compliance,grc,pentest,penetration,incident response,red team,offensive,cyber,infosec,information security,vulnerability,threat,appsec,application security,cloud security,network security,identity,iam,access management,data protection,privacy engineer,forensic,malware,blue team",
                "approved_roles": "Security Engineer,DevSecOps Engineer,Cloud Security Engineer,SOC Analyst,SOC Engineer,Compliance Analyst,GRC Analyst,Compliance Engineer,Incident Response Engineer,Penetration Tester,Red Team Engineer,Offensive Security Architect",
                "sort_order": 2,
            },
        ]

        created = 0
        for c in clusters:
            if c["name"] not in existing_names:
                session.add(RoleClusterConfig(
                    id=uuid.uuid4(),
                    name=c["name"],
                    display_name=c["display_name"],
                    is_relevant=True,
                    is_active=True,
                    keywords=c["keywords"],
                    approved_roles=c["approved_roles"],
                    sort_order=c["sort_order"],
                ))
                created += 1

        await session.commit()
        print(f"Seeded {created} role cluster configs (skipped {len(clusters) - created} existing)")

    await engine.dispose()


async def seed_common_questions():
    """Seed common ATS application questions as answer book defaults for all users."""
    from app.models.answer_book import AnswerBookEntry
    from app.models.user import User

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    COMMON_QUESTIONS = [
        # personal_info
        ("What is your first name?", "first_name", "personal_info"),
        ("What is your last name?", "last_name", "personal_info"),
        ("What is your full name?", "full_name", "personal_info"),
        ("What is your email address?", "email", "personal_info"),
        ("What is your phone number?", "phone", "personal_info"),
        ("What is your LinkedIn URL?", "linkedin_url", "personal_info"),
        ("What is your GitHub URL?", "github_url", "personal_info"),
        ("What is your website/portfolio?", "website", "personal_info"),
        ("What city do you live in?", "city", "personal_info"),
        ("What country do you live in?", "country", "personal_info"),
        # work_auth
        ("Are you authorized to work in the country of this job?", "work_authorization", "work_auth"),
        ("Do you require visa sponsorship?", "require_sponsorship", "work_auth"),
        ("Are you legally authorized to work in the US?", "legally_authorized_us", "work_auth"),
        # experience
        ("How many years of relevant experience do you have?", "years_of_experience", "experience"),
        ("Please provide a cover letter or tell us why you want this role.", "cover_letter", "experience"),
        ("What is your greatest professional achievement?", "greatest_achievement", "experience"),
        # preferences
        ("What are your salary expectations?", "salary_expectations", "preferences"),
        ("What is your earliest start date?", "start_date", "preferences"),
        ("Are you willing to relocate?", "willing_to_relocate", "preferences"),
        ("What is your preferred work schedule?", "work_schedule", "preferences"),
        ("What is your notice period?", "notice_period", "preferences"),
        # custom
        ("How did you hear about this position?", "how_did_you_hear", "custom"),
        ("What is your gender? (optional)", "gender", "custom"),
        ("What is your race/ethnicity? (optional)", "race_ethnicity", "custom"),
        ("Are you a veteran? (optional)", "veteran_status", "custom"),
        ("Do you have a disability? (optional)", "disability_status", "custom"),
    ]

    async with async_session() as session:
        users = (await session.execute(select(User))).scalars().all()
        total_added = 0

        for user in users:
            existing = (await session.execute(
                select(AnswerBookEntry.question_key).where(
                    AnswerBookEntry.user_id == user.id,
                    AnswerBookEntry.resume_id.is_(None),
                )
            )).scalars().all()
            existing_keys = set(existing)

            for question, key, category in COMMON_QUESTIONS:
                if key not in existing_keys:
                    session.add(AnswerBookEntry(
                        id=uuid.uuid4(),
                        user_id=user.id,
                        resume_id=None,
                        category=category,
                        question=question,
                        question_key=key,
                        answer="",
                        source="admin_default",
                    ))
                    total_added += 1

        await session.commit()
        print(f"Seeded {total_added} common question entries across {len(users)} users")

    await engine.dispose()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "questions":
        asyncio.run(seed_common_questions())
    elif len(sys.argv) > 1 and sys.argv[1] == "clusters":
        asyncio.run(seed_role_cluster_configs())
    else:
        asyncio.run(seed())
