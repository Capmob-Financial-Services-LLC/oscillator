"""Zoho Sprints dimensions with no Linear equivalent: projects, epics, tags,
and per-project status mappings.

Zoho's hierarchy is team -> project -> sprint/epic -> item, one level deeper
than Linear's team -> cycle -> issue, so `Project`/`Epic` are new first-class
dimensions rather than renames. `Tag` is the dimension the Engineering Points
system reads (type:*/sev:*/area:*/size:* and the triaged/reverted/rca-done
modifiers); `StatusDef` records each project's Zoho status -> our normalized
`state`/`state_type` mapping, since Zoho lets teams customize status names per
project (Linear's state_type is a fixed 6-value enum; Zoho's is not).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_team_id", "team_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    zoho_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="SET NULL")
    )
    key: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(255))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Epic(Base, TimestampMixin):
    __tablename__ = "epics"
    __table_args__ = (Index("ix_epics_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    zoho_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE")
    )
    name: Mapped[str | None] = mapped_column(String(255))


class Tag(Base, TimestampMixin):
    """A Zoho Sprints or GitHub tag/label, e.g. 'type:bug-fix', 'sev:critical', 'triaged'.

    `name` is the literal label string the Engineering Points system matches
    against (see app/models/points_rules.py) — not a display label, the key.
    Keyed on whichever source id is set (zoho_id or github_id); see the
    nullable-zoho_id migration 0010, mirroring the linear_id/zoho_id dual-
    source pattern the other dimension tables already use.
    """

    __tablename__ = "tags"
    __table_args__ = (Index("ix_tags_name", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    zoho_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_code: Mapped[str | None] = mapped_column(String(16))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )


class StatusDef(Base, TimestampMixin):
    """Per-project Zoho status -> our normalized (state, state_type)."""

    __tablename__ = "status_defs"
    __table_args__ = (
        UniqueConstraint("project_id", "zoho_status_id", name="uq_status_defs_project_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    zoho_status_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    # triage | backlog | unstarted | started | completed | canceled
    state_type: Mapped[str] = mapped_column(String(32), nullable=False)
