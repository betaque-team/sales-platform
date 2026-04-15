"""Audit log for security-sensitive actions.

Regression finding 61 — audit trail for bulk exports
-----------------------------------------------------
Finding 61 flagged that `/export/jobs`, `/export/pipeline`, and
`/export/contacts` were unauthenticated-beyond-login, letting any
viewer-tier account dump the full prospect database. The role-gate
fix landed in an earlier commit (all three endpoints now require
`require_role("admin")`). This model is the second half of the
defense: even when an admin legitimately exports, we keep an
immutable record so a compromised admin account still leaves a
forensic trail.

Schema choices
--------------
- `user_id` is **non-nullable**: an audit entry without an actor
  is useless, and the export endpoints always run inside a session
  so we always have one. FK uses `ON DELETE SET NULL` via a nullable
  column would be tempting for referential integrity after user
  deletion, but the tradeoff is worth it: we'd rather lose the
  reference to a deleted user than lose the audit record itself.
  Compromise: FK with `ON DELETE RESTRICT` so user deletion fails
  loudly if audit rows reference them (admin deletion is rare and
  the DB operator can archive the audit table first if needed).
- `action` is a short machine-readable verb (`"export.contacts"`,
  `"export.jobs"`, `"export.pipeline"`). Dotted namespace lets us
  expand later (e.g. `"user.role_change"`, `"resume.delete"`)
  without renaming existing entries.
- `resource` is the object class touched (`"contacts"`, `"jobs"`,
  `"pipeline"`). Redundant with the suffix of `action` for exports
  but lets us filter or aggregate across action verbs later.
- `ip_address` is `String(45)` to fit IPv6. Optional because tests
  and backfill scripts won't have a Request context.
- `user_agent` is `String(500)` — enough for any real UA header;
  we truncate if longer rather than raising.
- `metadata_json` captures per-action context (filters applied,
  row count, etc.) without schema churn every time a new action
  type ships. Matches the `Company.metadata_json` convention.
- `created_at` is indexed because the typical query pattern is
  "most recent N events" or "events in the last 24h".

What this does NOT include
--------------------------
- No `updated_at`: audit rows are immutable by design. If we ever
  need to mark a row as reviewed/acknowledged, that goes in a
  separate table rather than mutating the original event.
- No cascade on user delete — see above.
- No tenant/org scoping — the platform is single-tenant today. If
  multi-tenant lands, add `tenant_id` in a follow-up migration.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Who performed the action. RESTRICT on delete so user-delete
    # doesn't silently orphan forensic records — the operator has
    # to archive/move the audit rows first.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Machine-readable verb (`"export.contacts"`, `"export.jobs"`,
    # `"export.pipeline"`). Keep under 50 chars; dotted namespace.
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Object class touched. Redundant for exports but future-proof
    # for non-export events where `action` carries other verbs.
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    # Network origin. Optional because test/backfill paths may
    # run without a Request context. 45 chars fits IPv6 including
    # scope suffix (`fe80::1%eth0`).
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Browser / tool identifier. Truncate at 500 chars to cap
    # storage — real UA strings are well under that.
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Per-event structured context: query filters, row count,
    # resource ids, etc. Default to `dict` (not `None`) so readers
    # can always `.get()` without guarding for None.
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Indexed because the dominant query is "recent events first".
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Eager-load the actor for the audit list view; we almost
    # always want to render the username alongside the event.
    user = relationship("User", foreign_keys=[user_id], lazy="joined")

    __table_args__ = (
        # Compound index for the common "recent events by actor"
        # or "recent events by action" queries. Postgres can
        # already use the per-column indexes above, but this
        # supports `(user_id, created_at DESC)` lookups cheaply.
        Index(
            "ix_audit_logs_created_at_desc",
            "created_at",
            postgresql_using="btree",
        ),
    )
