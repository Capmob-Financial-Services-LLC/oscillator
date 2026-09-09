"""Comments and the append-only raw_events landing table.

raw_events is partitioned BY RANGE (received_at) per month. It is append-only:
every record pulled by a sync run lands here first, then the normalizer projects
it into the typed tables. Composite PK (id, received_at) because the partition
key must be in the PK.
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
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_actor_id", "actor_id"),
        Index("ix_comments_issue_id", "issue_id"),
        Index("ix_comments_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # nullable: rows synced from Zoho Sprints / GitHub carry zoho_id/github_id instead.
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    zoho_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    issue_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("actors.id", ondelete="SET NULL")
    )
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        Index("ix_raw_events_event_type", "event_type"),
        Index("ix_raw_events_received_at", "received_at"),
        Index(
            "ix_raw_events_unprocessed",
            "received_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), server_default=text("'linear'"), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(128))  # e.g. "Issue", "Comment"
    action: Mapped[str | None] = mapped_column(String(64))  # create | update | remove
    delivery_id: Mapped[str | None] = mapped_column(String(128))  # reserved for dedup
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
