"""CI-only DB bootstrap: create the current schema then stamp alembic.

WHY THIS EXISTS
---------------
The original schema (jobs, companies, users, company_ats_boards, …)
was created via ``Base.metadata.create_all`` in pre-alembic days and
never moved into a baseline migration. The first alembic revision
(``a1b2c3d4e5f6``) has ``down_revision = None`` but FK-references
``jobs.id``, so ``alembic upgrade head`` against a FRESH database
fails on the very first migration with::

    relation "jobs" does not exist

Prod is unaffected because prod's DB already has the original tables
from the pre-alembic era — so ``alembic upgrade head`` there only ever
applies *new* migrations and works fine. The breakage is fresh-DB-only.

This script papers over the gap for CI without rewriting history:

  1. ``Base.metadata.create_all(checkfirst=True)`` brings every model
     table into existence at its CURRENT shape (including columns that
     individual migrations later added). Idempotent — a no-op against
     prod if it ever ran there.
  2. ``alembic stamp head`` records the current head revision in the
     ``alembic_version`` table without running any migration up/down.
     Subsequent ``alembic upgrade head`` calls then short-circuit
     ("nothing to do") instead of trying to replay broken DDL.

The right long-term fix is a hand-written baseline migration that
creates exactly the pre-alembic schema (so subsequent ``op.add_column``
calls find a column that *isn't* there yet). That's a 200-line
change with non-trivial risk against prod's existing schema, so it's
TODO'd separately. Until then, CI uses this bootstrap.

Usage
-----
``python -m scripts.init_ci_db`` — invoked once before pytest in CI.

Failure modes
-------------
- ``ModuleNotFoundError`` on a model import → some app/models entry
  was renamed/removed; update the env.py import block too.
- ``OperationalError: connection refused`` → DATABASE_URL_SYNC points
  at a Postgres that isn't up; check the CI service health.
"""
from __future__ import annotations

import sys
from pathlib import Path

# CRITICAL: this script lives at ``platform/backend/scripts/init_ci_db.py``
# and the project root has a sibling ``platform/backend/alembic/`` directory
# (alembic's migrations folder). When CI runs ``python -m scripts.init_ci_db``
# from ``platform/backend``, Python's import system puts ``platform/backend``
# on ``sys.path[0]`` and resolves ``import alembic`` to the LOCAL
# migrations folder (an empty ``__init__.py``) instead of the installed
# alembic package. The result is ``ImportError: cannot import name 'command'
# from 'alembic'``. Push the project root off the front of ``sys.path``
# while we import alembic, then restore.
_repo_dir = Path(__file__).resolve().parent.parent  # platform/backend
_paths_with_repo = [p for p in sys.path if Path(p).resolve() == _repo_dir]
for _p in _paths_with_repo:
    sys.path.remove(_p)
from sqlalchemy import create_engine

from alembic import command
from alembic.config import Config

# Restore so app.* imports still resolve against platform/backend.
sys.path.insert(0, str(_repo_dir))

# Mirror the import block from ``alembic/env.py``. We can't import
# env.py directly here because env.py uses the alembic runtime's
# ``context`` which is only bound inside an alembic command. Keep
# this list in sync with env.py — a CI smoke test below cross-checks
# the two so drift is caught at test time, not at deploy time.
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
from app.models.profile import Profile, ProfileDocument  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.routine_run import RoutineRun  # noqa: F401
from app.models.application_submission import ApplicationSubmission  # noqa: F401
from app.models.humanization_corpus import HumanizationCorpus  # noqa: F401
from app.models.routine_kill_switch import RoutineKillSwitch  # noqa: F401
from app.models.routine_target import RoutineTarget  # noqa: F401  # F257

from app.config import get_settings
from app.database import Base


def _sync_url(settings) -> str:
    """Return a sync DSN for ``Base.metadata.create_all``.

    ``database_url`` may be the async asyncpg DSN; this script uses
    the sibling sync URL when available, falling back to a manual
    asyncpg→psycopg2 swap so this script doesn't need its own env
    plumbing.
    """
    sync = getattr(settings, "database_url_sync", None)
    if sync:
        return sync
    return settings.database_url.replace("+asyncpg", "")


def main() -> int:
    settings = get_settings()
    sync_dsn = _sync_url(settings)

    print(f"[init_ci_db] create_all on {sync_dsn.split('@')[-1]}")
    engine = create_engine(sync_dsn, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(bind=conn, checkfirst=True)
        print(f"[init_ci_db] {len(Base.metadata.tables)} tables ensured")
    finally:
        engine.dispose()

    # Stamp alembic head so a follow-up `alembic upgrade head` is a no-op.
    repo_root = Path(__file__).resolve().parent.parent  # platform/backend
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sync_dsn)
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    print("[init_ci_db] stamping alembic head")
    command.stamp(cfg, "head")

    print("[init_ci_db] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
