import enum
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aigentix.core.db import Base, TimestampMixin


class ProjectStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ResearchProject(TimestampMixin, Base):
    """A tenant-owned research project. Sprint 2 adds companies/evidence linked to it."""

    __tablename__ = "research_projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ProjectStatus.DRAFT.value)

    __table_args__ = (
        # Target of the composite FK from workflow_runs (same-organization guarantee).
        UniqueConstraint("id", "organization_id", name="uq_research_projects_id_org"),
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="status_valid"),
        Index("ix_research_projects_org_created", "organization_id", "created_at"),
    )
