"""Add Company.careers_url + careers_url_fetched_at.

Revision ID: w3r4s5t6u7v8
Revises: v2q3r4s5t6u7
Create Date: 2026-04-17

Phase A of the "ATS lockdown fallback" thread. Two cheap additive
columns that let us remember which URL on a company's own site lists
their jobs — populated by the ``fingerprint_existing_companies``
Celery task as a side-effect of the ATS detection it already does.

Why this is Phase A and NOT Phase B/C (snapshot storage + generic
parser):
* **Phase A is standalone useful.** Admins can see "this company's
  careers page is here" even without any fallback logic. Pre-populates
  the data we'd need for future fallback work.
* **Phase B + C (storing HTML snapshots + a generic parser) are NOT
  shipping now** — a live survey on 2026-04-17 showed JSON-LD
  ``JobPosting`` structured data is rare on careers hub pages
  (they're mostly client-rendered SPAs). Building a generic parser
  speculatively would give us a tool that rarely fires. When a
  specific ATS locks down for the first time, we'll build a targeted
  parser for its page shape — not a speculative general one.

Column choices:
* ``careers_url`` (VARCHAR 1000) matches ``DiscoveredCompany.careers_url``
  and ``Job.url`` conventions. Nullable — most companies won't have
  a known careers URL until the fingerprint task runs over them.
* ``careers_url_fetched_at`` (TIMESTAMPTZ) records when we last
  successfully extracted this URL. Nullable for the same reason,
  and also lets a future "re-fingerprint stale entries" task identify
  rows to refresh.

No backfill — all existing rows get NULL, and the fingerprint task
will fill them in over its next several beat cycles.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "w3r4s5t6u7v8"
down_revision = "v2q3r4s5t6u7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("careers_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column(
            "careers_url_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("companies", "careers_url_fetched_at")
    op.drop_column("companies", "careers_url")
