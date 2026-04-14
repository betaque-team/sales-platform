"""Alembic environment configuration with async engine support."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings

# Import all models so Base.metadata is fully populated
from app.models import (  # noqa: F401
    User, Company, CompanyATSBoard, Job, JobDescription,
    Review, PotentialClient, ScanLog, CareerPageWatch,
    RoleRule, DiscoveryRun, DiscoveredCompany,
    Resume, ResumeScore, AICustomizationLog, RoleClusterConfig,
    PlatformCredential, AnswerBookEntry, Application,
)
from app.models.scoring_signal import ScoringSignal  # noqa: F401
from app.models.job_question import JobQuestion  # noqa: F401
from app.models.company_contact import CompanyContact, JobContactRelevance  # noqa: F401
from app.models.company_office import CompanyOffice  # noqa: F401
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()


def get_url() -> str:
    """Return the database URL, converting async driver for sync usage when needed."""
    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
