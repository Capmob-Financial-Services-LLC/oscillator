"""Linear issue labels and their per-issue associations.

`Tag` is the dimension the Engineering Points system (app/jobs/score_points.py)
reads: type:*/sev:*/area:*/size:* and the triaged/reverted/rca-done modifier
labels, already created in Linear per the team's scoring doc.

issue_tags holds the CURRENT tag set per issue (removed_at IS NULL = still
attached); issue_tag_history is the append-only diff log the scoring job
reads to detect exactly when a `triaged`/`reverted`/`rca-done` label was
added — the same snapshot-before-overwrite-then-diff idiom upsert_issues
already uses for state transitions (see app/services/normalizer.py),
applied to label sets instead of (state, state_type). Both are partitioned
the same way as issue_history where relevant.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class Tag(Base, TimestampMixin):
    """A Linear or GitHub issue label, e.g. 'type:bug-fix', 'sev:critical', 'triaged'.

    `name` is the literal label string the Engineering Points system matches
    against (see app/models/points_rules.py) — not a display label, the key.
    Keyed on whichever source id is set (linear_id or github_id).
    """

    __tablename__ = "tags"
    __table_args__ = (Index("ix_tags_name", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # nullable: a row synced from GitHub carries github_id instead.
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color_code: Mapped[str | None] = mapped_column(String(16))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )


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

    Linear has no bulk label-history API, so `changed_at` is "poll time"
    (when the diff was detected during a sync run), not the true edit
    instant — same limitation issue_history already accepts for state
    transitions. This is what app/jobs/score_points.py reads to know exactly
    when `triaged`, `reverted`, or `rca-done` first appeared on an issue.
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
