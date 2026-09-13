"""Core dimension tables: teams, actors (users), cycles."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # nullable: a row synced from GitHub carries github_id instead.
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    key: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(255))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Actor(Base, TimestampMixin):
    """A Linear or GitHub user. Keyed on whichever source id is set."""

    __tablename__ = "actors"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)


class SyncState(Base):
    """Single-row-per-key watermark for the cron poller (key='linear')."""

    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Cycle(Base, TimestampMixin):
    __tablename__ = "cycles"
    __table_args__ = (Index("ix_cycles_team_id", "team_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # nullable: a row synced from GitHub (milestone) carries github_id instead.
    linear_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="CASCADE")
    )
    number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String(255))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
