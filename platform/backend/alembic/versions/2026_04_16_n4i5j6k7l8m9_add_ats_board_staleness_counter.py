"""Add consecutive_zero_scans + deactivated_reason to company_ats_boards.

Revision ID: n4i5j6k7l8m9
Revises: m3h4i5j6k7l8
Create Date: 2026-04-16

Regression finding 7 (auto-deactivation half): boards that consistently
return 0 jobs (BambooHR, Jobvite, Recruitee orgs that migrated ATS or
spun down their career site) stay `is_active=True` forever, inflating
the "active boards" count on Monitoring and spending per-scan HTTP
budget for no return. The scanner side of the fix lives in
`workers/tasks/scan_task.py::_update_board_health`; this migration
adds the two columns that drive the behavior.

Column semantics (enforced in the scan task):
- `consecutive_zero_scans`: incremented only on a *clean* zero return
  (no fetcher error). Reset to 0 on any scan that returns >=1 job.
  Left unchanged on a scan that raised so a Cloudflare-403 blip doesn't
  reset a genuinely-dead board's progress toward deactivation.
- `deactivated_reason`: non-empty string explaining why `is_active`
  flipped to False via the auto path. Lets ops distinguish auto-
  deactivated stale slugs from manually-paused ones via a single
  column filter. Empty = manually paused or never deactivated.

Both columns are NOT NULL with server-side defaults so the backfill
for existing rows is trivial (0 and '' respectively) — no data-
migration step needed.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "n4i5j6k7l8m9"
down_revision = "m3h4i5j6k7l8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_ats_boards",
        sa.Column(
            "consecutive_zero_scans",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "company_ats_boards",
        sa.Column(
            "deactivated_reason",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )


def downgrade() -> None:
    op.drop_column("company_ats_boards", "deactivated_reason")
    op.drop_column("company_ats_boards", "consecutive_zero_scans")
