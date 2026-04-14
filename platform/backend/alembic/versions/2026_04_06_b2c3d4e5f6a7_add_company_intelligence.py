"""Add company intelligence: contacts, offices, enrichment fields.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add enrichment columns to companies
    op.add_column("companies", sa.Column("domain", sa.String(255), server_default=""))
    op.add_column("companies", sa.Column("founded_year", sa.Integer, nullable=True))
    op.add_column("companies", sa.Column("total_funding", sa.String(100), server_default=""))
    op.add_column("companies", sa.Column("total_funding_usd", sa.BigInteger, nullable=True))
    op.add_column("companies", sa.Column("linkedin_url", sa.String(500), server_default=""))
    op.add_column("companies", sa.Column("twitter_url", sa.String(500), server_default=""))
    op.add_column("companies", sa.Column("tech_stack", sa.ARRAY(sa.String), server_default="{}"))
    op.add_column("companies", sa.Column("enrichment_status", sa.String(50), server_default="pending"))
    op.add_column("companies", sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies", sa.Column("enrichment_error", sa.Text, server_default=""))

    # Company contacts
    op.create_table(
        "company_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(200), server_default=""),
        sa.Column("last_name", sa.String(200), server_default=""),
        sa.Column("title", sa.String(300), server_default=""),
        sa.Column("role_category", sa.String(100), server_default="other"),
        sa.Column("department", sa.String(200), server_default=""),
        sa.Column("seniority", sa.String(50), server_default="other"),
        sa.Column("email", sa.String(300), server_default=""),
        sa.Column("email_status", sa.String(50), server_default="unverified"),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("phone", sa.String(50), server_default=""),
        sa.Column("linkedin_url", sa.String(500), server_default=""),
        sa.Column("twitter_url", sa.String(500), server_default=""),
        sa.Column("telegram_id", sa.String(200), server_default=""),
        sa.Column("source", sa.String(100), server_default=""),
        sa.Column("confidence_score", sa.Float, server_default="0.0"),
        sa.Column("is_decision_maker", sa.Boolean, server_default="false"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_contacts_company", "company_contacts", ["company_id"])
    op.create_index("idx_contacts_email", "company_contacts", ["email"])
    op.create_index("idx_contacts_role_cat", "company_contacts", ["role_category"])

    # Company offices
    op.create_table(
        "company_offices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(200), server_default=""),
        sa.Column("address", sa.String(500), server_default=""),
        sa.Column("city", sa.String(200), server_default=""),
        sa.Column("state", sa.String(100), server_default=""),
        sa.Column("country", sa.String(100), server_default=""),
        sa.Column("is_headquarters", sa.Boolean, server_default="false"),
        sa.Column("source", sa.String(100), server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_offices_company", "company_offices", ["company_id"])

    # Job-contact relevance
    op.create_table(
        "job_contact_relevance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", UUID(as_uuid=True), sa.ForeignKey("company_contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relevance_reason", sa.String(300), server_default=""),
        sa.Column("relevance_score", sa.Float, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_jcr_job", "job_contact_relevance", ["job_id"])
    op.create_index("idx_jcr_contact", "job_contact_relevance", ["contact_id"])


def downgrade() -> None:
    op.drop_table("job_contact_relevance")
    op.drop_table("company_offices")
    op.drop_table("company_contacts")

    op.drop_column("companies", "enrichment_error")
    op.drop_column("companies", "enriched_at")
    op.drop_column("companies", "enrichment_status")
    op.drop_column("companies", "tech_stack")
    op.drop_column("companies", "twitter_url")
    op.drop_column("companies", "linkedin_url")
    op.drop_column("companies", "total_funding_usd")
    op.drop_column("companies", "total_funding")
    op.drop_column("companies", "founded_year")
    op.drop_column("companies", "domain")
