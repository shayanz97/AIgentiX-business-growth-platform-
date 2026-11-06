"""lead intelligence research

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06 15:39:36.338294+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- workflow_runs: generic progress, retries, cancellation, usage; module link moves to research_runs ---
    op.add_column("workflow_runs", sa.Column("current_step", sa.String(length=60), nullable=True))
    op.add_column("workflow_runs", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("workflow_runs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("workflow_runs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workflow_runs", sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("workflow_runs", sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"))
    op.add_column(
        "workflow_runs",
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False, server_default="0"),
    )
    for column in ("progress", "max_attempts", "input_tokens", "output_tokens", "estimated_cost_usd"):
        op.alter_column("workflow_runs", column, server_default=None)

    # Status vocabulary: queued -> pending, succeeded -> completed (+ partial).
    op.drop_constraint(op.f("ck_workflow_runs_status_valid"), "workflow_runs", type_="check")
    op.execute("UPDATE workflow_runs SET status = 'pending' WHERE status = 'queued'")
    op.execute("UPDATE workflow_runs SET status = 'completed' WHERE status = 'succeeded'")
    op.create_check_constraint(
        "status_valid",
        "workflow_runs",
        "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')",
    )
    op.create_check_constraint("progress_range", "workflow_runs", "progress BETWEEN 0 AND 100")
    op.create_check_constraint("attempts_valid", "workflow_runs", "attempts >= 0 AND max_attempts >= 1")

    op.drop_index(
        op.f("ix_workflow_runs_queued"),
        table_name="workflow_runs",
        postgresql_where="((status)::text = 'queued'::text)",
    )
    op.create_index(
        "ix_workflow_runs_pending",
        "workflow_runs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_workflow_runs_running",
        "workflow_runs",
        ["heartbeat_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_unique_constraint("uq_workflow_runs_id_org", "workflow_runs", ["id", "organization_id"])
    # Platform table no longer references a module table (Sprint 1 review finding M3).
    op.drop_index(op.f("ix_workflow_runs_project"), table_name="workflow_runs")
    op.drop_constraint(op.f("fk_workflow_runs_project_same_org"), "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "project_id")

    # --- Lead Intelligence tables ---
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("canonical_domain", sa.String(length=253), nullable=True),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("industry", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(canonical_domain IS NULL) = (website_url IS NULL)", name=op.f("ck_companies_domain_and_url_together")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_companies_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_companies_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("id", "organization_id", name="uq_companies_id_org"),
    )
    op.create_index("ix_companies_org_created", "companies", ["organization_id", "created_at"], unique=False)
    op.create_index(
        "uq_companies_org_domain",
        "companies",
        ["organization_id", "canonical_domain"],
        unique=True,
        postgresql_where=sa.text("canonical_domain IS NOT NULL"),
    )
    op.create_index(
        "uq_companies_org_name_without_domain",
        "companies",
        ["organization_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("canonical_domain IS NULL"),
    )
    op.create_table(
        "research_project_companies",
        sa.Column("research_project_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            name=op.f("fk_research_project_companies_company_id_organization_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_project_id", "organization_id"],
            ["research_projects.id", "research_projects.organization_id"],
            name=op.f("fk_research_project_companies_research_project_id_organization_id_research_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("research_project_id", "company_id", name=op.f("pk_research_project_companies")),
    )
    op.create_index("ix_research_project_companies_company", "research_project_companies", ["company_id"], unique=False)
    op.create_table(
        "research_runs",
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "profile", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("ai_status", sa.String(length=20), nullable=False),
        sa.Column("audit_summary", sa.Text(), nullable=True),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ai_status IN ('pending', 'completed', 'unavailable', 'failed', 'skipped')",
            name=op.f("ck_research_runs_ai_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            name=op.f("fk_research_runs_company_id_organization_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["research_projects.id", "research_projects.organization_id"],
            name=op.f("fk_research_runs_project_id_organization_id_research_projects"),
            ondelete="SET NULL (project_id)",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_research_runs_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "organization_id"],
            ["workflow_runs.id", "workflow_runs.organization_id"],
            name=op.f("fk_research_runs_workflow_run_id_organization_id_workflow_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workflow_run_id", name=op.f("pk_research_runs")),
        sa.UniqueConstraint("workflow_run_id", "organization_id", name="uq_research_runs_id_org"),
    )
    op.create_index("ix_research_runs_company_created", "research_runs", ["company_id", "created_at"], unique=False)
    op.create_index("ix_research_runs_org_created", "research_runs", ["organization_id", "created_at"], unique=False)
    op.create_index("ix_research_runs_project", "research_runs", ["project_id"], unique=False)
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("observed_context", sa.Text(), nullable=False),
        sa.Column("problem_hypothesis", sa.Text(), nullable=False),
        sa.Column("proposed_ai_solution", sa.Text(), nullable=False),
        sa.Column("estimated_business_impact", sa.Text(), nullable=False),
        sa.Column("implementation_complexity", sa.String(length=10), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_step", sa.Text(), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name=op.f("ck_opportunities_confidence_valid")),
        sa.CheckConstraint(
            "implementation_complexity IN ('low', 'medium', 'high')", name=op.f("ck_opportunities_complexity_valid")
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'under_review', 'approved', 'rejected')", name=op.f("ck_opportunities_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            name=op.f("fk_opportunities_company_id_organization_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            name=op.f("fk_opportunities_research_run_id_organization_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_opportunities_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
        sa.UniqueConstraint("id", "organization_id", name="uq_opportunities_id_org"),
    )
    op.create_index("ix_opportunities_company", "opportunities", ["company_id"], unique=False)
    op.create_index("ix_opportunities_org_status", "opportunities", ["organization_id", "status"], unique=False)
    op.create_index("ix_opportunities_run", "opportunities", ["research_run_id"], unique=False)
    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("page_category", sa.String(length=40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("extraction_status", sa.String(length=20), nullable=False),
        sa.Column("extraction_error", sa.String(length=500), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "extraction_status IN ('extracted', 'empty', 'failed', 'skipped')",
            name=op.f("ck_research_sources_extraction_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            name=op.f("fk_research_sources_company_id_organization_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            name=op.f("fk_research_sources_research_run_id_organization_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_sources")),
        sa.UniqueConstraint("id", "organization_id", name="uq_research_sources_id_org"),
        sa.UniqueConstraint("research_run_id", "source_url", name="uq_research_sources_run_url"),
    )
    op.create_index("ix_research_sources_company", "research_sources", ["company_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("research_run_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("observed_fact", sa.Text(), nullable=False),
        sa.Column("supporting_excerpt", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=10), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("basis IN ('observed', 'inferred')", name=op.f("ck_evidence_basis_valid")),
        sa.CheckConstraint("confidence IN ('low', 'medium', 'high')", name=op.f("ck_evidence_confidence_valid")),
        sa.CheckConstraint(
            "evidence_type IN ('company_description', 'service_offering', 'target_customer', 'business_model', 'contact_form', 'quote_request_form', 'online_booking', 'live_chat', 'customer_support', 'faq', 'careers_hiring', 'document_download', 'document_workflow', 'ecommerce', 'technology_signal', 'operational_signal', 'industry', 'location')",
            name=op.f("ck_evidence_evidence_type_valid"),
        ),
        sa.CheckConstraint("origin IN ('deterministic', 'llm')", name=op.f("ck_evidence_origin_valid")),
        sa.ForeignKeyConstraint(
            ["company_id", "organization_id"],
            ["companies.id", "companies.organization_id"],
            name=op.f("fk_evidence_company_id_organization_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id", "organization_id"],
            ["research_runs.workflow_run_id", "research_runs.organization_id"],
            name=op.f("fk_evidence_research_run_id_organization_id_research_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["research_sources.id", "research_sources.organization_id"],
            name=op.f("fk_evidence_source_id_organization_id_research_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("id", "organization_id", name="uq_evidence_id_org"),
    )
    op.create_index("ix_evidence_company", "evidence", ["company_id"], unique=False)
    op.create_index("ix_evidence_run", "evidence", ["research_run_id"], unique=False)
    op.create_table(
        "opportunity_evidence",
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id", "organization_id"],
            ["evidence.id", "evidence.organization_id"],
            name=op.f("fk_opportunity_evidence_evidence_id_organization_id_evidence"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "organization_id"],
            ["opportunities.id", "opportunities.organization_id"],
            name=op.f("fk_opportunity_evidence_opportunity_id_organization_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("opportunity_id", "evidence_id", name=op.f("pk_opportunity_evidence")),
    )
    op.create_index("ix_opportunity_evidence_evidence", "opportunity_evidence", ["evidence_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_opportunity_evidence_evidence", table_name="opportunity_evidence")
    op.drop_table("opportunity_evidence")
    op.drop_index("ix_evidence_run", table_name="evidence")
    op.drop_index("ix_evidence_company", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_research_sources_company", table_name="research_sources")
    op.drop_table("research_sources")
    op.drop_index("ix_opportunities_run", table_name="opportunities")
    op.drop_index("ix_opportunities_org_status", table_name="opportunities")
    op.drop_index("ix_opportunities_company", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index("ix_research_runs_project", table_name="research_runs")
    op.drop_index("ix_research_runs_org_created", table_name="research_runs")
    op.drop_index("ix_research_runs_company_created", table_name="research_runs")
    op.drop_table("research_runs")
    op.drop_index("ix_research_project_companies_company", table_name="research_project_companies")
    op.drop_table("research_project_companies")
    op.drop_index(
        "uq_companies_org_name_without_domain",
        table_name="companies",
        postgresql_where=sa.text("canonical_domain IS NULL"),
    )
    op.drop_index(
        "uq_companies_org_domain", table_name="companies", postgresql_where=sa.text("canonical_domain IS NOT NULL")
    )
    op.drop_index("ix_companies_org_created", table_name="companies")
    op.drop_table("companies")

    op.add_column("workflow_runs", sa.Column("project_id", sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(
        op.f("fk_workflow_runs_project_same_org"),
        "workflow_runs",
        "research_projects",
        ["project_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_workflow_runs_project"), "workflow_runs", ["project_id"], unique=False)
    op.drop_constraint("uq_workflow_runs_id_org", "workflow_runs", type_="unique")
    op.drop_index(
        "ix_workflow_runs_running", table_name="workflow_runs", postgresql_where=sa.text("status = 'running'")
    )
    op.drop_index(
        "ix_workflow_runs_pending", table_name="workflow_runs", postgresql_where=sa.text("status = 'pending'")
    )
    op.create_index(
        op.f("ix_workflow_runs_queued"),
        "workflow_runs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_constraint(op.f("ck_workflow_runs_attempts_valid"), "workflow_runs", type_="check")
    op.drop_constraint(op.f("ck_workflow_runs_progress_range"), "workflow_runs", type_="check")
    op.drop_constraint(op.f("ck_workflow_runs_status_valid"), "workflow_runs", type_="check")
    op.execute("UPDATE workflow_runs SET status = 'queued' WHERE status = 'pending'")
    op.execute("UPDATE workflow_runs SET status = 'succeeded' WHERE status IN ('completed', 'partial')")
    op.create_check_constraint(
        "status_valid", "workflow_runs", "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"
    )
    for column in (
        "estimated_cost_usd",
        "output_tokens",
        "input_tokens",
        "cancel_requested_at",
        "heartbeat_at",
        "next_attempt_at",
        "max_attempts",
        "progress",
        "current_step",
    ):
        op.drop_column("workflow_runs", column)
