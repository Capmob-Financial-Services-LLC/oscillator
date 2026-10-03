"""Pydantic v2 response models for the Engineering Points API.

Additive alongside app/schemas/insights.py — these don't replace
ByActorResponse/ActorStat, they're a parallel resource the frontend merges
client-side (same pattern already used for overview/throughput/by-actor).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.insights import Range


class PointsCategoryBreakdown(BaseModel):
    category: str
    points: int


class PointsActorStat(BaseModel):
    actor_id: int
    name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    total_points: int
    by_category: list[PointsCategoryBreakdown]


class PointsByActorResponse(BaseModel):
    range: Range
    period_start: datetime
    period_end: datetime
    actors: list[PointsActorStat]


class PointsLedgerEntry(BaseModel):
    id: int
    issue_id: int
    identifier: str | None = None
    title: str | None = None
    actor_id: int | None = None
    name: str | None = None
    category: str
    event_kind: str  # award | reversal | bonus
    points: int
    rule_key: str | None = None
    label_state: list[str] | dict | None = None
    effective_at: datetime
    awarded_at: datetime
    reverses_event_id: int | None = None
    related_event_id: int | None = None


class PointsLedgerResponse(BaseModel):
    entries: list[PointsLedgerEntry]
    total: int


class UnscoredTicketItem(BaseModel):
    issue_id: int
    identifier: str | None = None
    title: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    reason: str
    first_detected_at: datetime
    last_checked_at: datetime
    notified_at: datetime | None = None
    # The repo (GitHub) or team (Linear): "#120" alone is ambiguous across repos.
    team: str | None = None


class UnscoredResponse(BaseModel):
    range: Range
    tickets: list[UnscoredTicketItem]
