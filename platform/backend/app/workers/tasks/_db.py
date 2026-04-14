"""Synchronous SQLAlchemy session for Celery workers."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SYNC_DATABASE_URL = os.environ.get(
    "DATABASE_URL_SYNC",
    os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/jobplatform"),
)
# Strip asyncpg driver if accidentally passed the async URL
if "+asyncpg" in SYNC_DATABASE_URL:
    SYNC_DATABASE_URL = SYNC_DATABASE_URL.replace("+asyncpg", "")

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

SyncSession = sessionmaker(bind=sync_engine)
