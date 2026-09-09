"""Issues, their state-transition history, and their tag associations.

issue_history and issue_tag_history are both partitioned BY RANGE per month —
they are the highest-volume relational tables. Postgres requires the
partition key to be part of the primary key, hence the composite PKs.

issue_tags holds the *current* tag set per issue (removed_at IS NULL = still
attached); issue_tag_history is the append-only diff log the Engineering
Points scoring job (app/jobs/score_points.py) reads to detect exactly when a
`triaged`/`reverted`/`rca-done` tag was added — the same
snapshot-before-overwrite-then-diff idiom upsert_issues already uses for
state transitions, applied to tag sets instead of (state, state_type).
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
    # nullable: rows synced from Zoho Sprints / GitHub carry zoho_id/github_id
    # instead (see below).
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    identifier: Mapped[str | None] = mapped_column(String(64))  # e.g. "ENG-123"
    title: Mapped[str | None] = mapped_column(Text)

    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="SET NULL")
    )
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    # Reused for Zoho's `createdBy` — same "who filed this" semantics as Linear's creator.
    creator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    cycle_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cycles.id", ondelete="SET NULL")
    )

    state: Mapped[str | None] = mapped_column(String(128))  # workflow state name
    # triage | backlog | unstarted | started | completed | canceled
    state_type: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int | None] = mapped_column(Integer)  # 0=none .. 4=low (Linear only)
    # Reused for Zoho's `points` — same "size estimate" semantics as Linear's estimate.
    estimate: Mapped[float | None] = mapped_column(Float)
    project_id: Mapped[str | None] = mapped_column(String(64))  # Linear project id (no FK in v1)
    # 'linear' | 'custom' | 'zoho_sprints' | 'github' (all synced except 'custom')
    source: Mapped[str] = mapped_column(String(16), server_default="linear", nullable=False)

    # --- Zoho Sprints fields (nullable; unset on Linear/custom rows) ---
    zoho_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # --- GitHub fields (nullable; unset on non-GitHub rows) ---
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Who the item was actually marked done by; can differ from assignee_id
    # if it was reassigned after completion. No Linear equivalent.
    completed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    epic_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("epics.id", ondelete="SET NULL")
    )
    zoho_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    # Zoho's priority is a project-scoped custom enum, not Linear's fixed 0-4
    # int, so it's stored as the raw label rather than forced into `priority`.
    priority_label: Mapped[str | None] = mapped_column(String(64))

    # Linear/Zoho's own lifecycle timestamps
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


class IssueTag(Base):
    """Current tag set per issue. removed_at IS NULL means still attached."""

    __tablename__ = "issue_tags"
    __table_args__ = (
        Index("ix_issue_tags_issue_id", "issue_id"),
        Index("ix_issue_tags_tag_id", "tag_id"),
    )

    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IssueTagHistory(Base):
    """Append-only tag add/remove log. Partitioned monthly by changed_at.

    No reliable tag-history API exists, so `changed_at` is "poll time" (when
    the diff was detected), not the true edit instant — same limitation
    issue_history already accepts for state transitions. This is what
    app/jobs/score_points.py reads to know exactly when `triaged`, `reverted`,
    or `rca-done` first appeared on an already-closed ticket.
    """

    __tablename__ = "issue_tag_history"
    __table_args__ = (
        Index("ix_issue_tag_history_issue_id", "issue_id"),
        Index("ix_issue_tag_history_tag_id", "tag_id"),
        Index("ix_issue_tag_history_changed_at", "changed_at"),
        {"postgresql_partition_by": "RANGE (changed_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # part of the PK because it is the partition key
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)  # 'added' | 'removed'
