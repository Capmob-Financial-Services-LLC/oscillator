"""Issues and their state-transition history.

issue_history is partitioned BY RANGE (changed_at) per month — it is the
highest-volume relational table and powers cycle-time analysis. Postgres
requires the partition key to be part of the primary key, hence the
composite PK (id, changed_at).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class Issue(Base, TimestampMixin):
    __tablename__ = "issues"
    __table_args__ = (
        Index("ix_issues_assignee_id", "assignee_id"),
        Index("ix_issues_team_id", "team_id"),
        Index("ix_issues_state_type", "state_type"),
        Index("ix_issues_completed_at", "completed_at"),
        Index("ix_issues_cycle_id", "cycle_id"),
        Index("ix_issues_updated_at", "updated_at"),
        Index("ix_issues_source", "source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # nullable: a row synced from GitHub carries github_id instead.
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    identifier: Mapped[str | None] = mapped_column(String(64))  # e.g. "ENG-123"
    title: Mapped[str | None] = mapped_column(Text)

    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="SET NULL")
    )
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    creator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    cycle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cycles.id", ondelete="SET NULL")
    )

    state: Mapped[str | None] = mapped_column(String(128))  # workflow state name
    # triage | backlog | unstarted | started | completed | canceled
    state_type: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int | None] = mapped_column(Integer)  # 0=none .. 4=low
    estimate: Mapped[float | None] = mapped_column(Float)
    project_id: Mapped[str | None] = mapped_column(String(64))  # Linear project id (no FK in v1)
    # 'linear' | 'custom' (manually tracked) | 'github'
    source: Mapped[str] = mapped_column(String(16), server_default="linear", nullable=False)

    # Linear's own lifecycle timestamps
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueHistory(Base):
    """One row per state transition. Partitioned monthly by changed_at."""

    __tablename__ = "issue_history"
    __table_args__ = (
        UniqueConstraint("linear_id", "changed_at", name="uq_issue_history_node"),
        Index("ix_issue_history_issue_id", "issue_id"),
        Index("ix_issue_history_changed_at", "changed_at"),
        {"postgresql_partition_by": "RANGE (changed_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # part of the PK because it is the partition key
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    linear_id: Mapped[str | None] = mapped_column(String(64))  # Linear history node id

    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )

    from_state: Mapped[str | None] = mapped_column(String(128))
    to_state: Mapped[str | None] = mapped_column(String(128))
    from_state_type: Mapped[str | None] = mapped_column(String(32))
    to_state_type: Mapped[str | None] = mapped_column(String(32))
