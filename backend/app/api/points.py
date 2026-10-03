"""Engineering Points API — read-only over the points_events ledger.

Additive alongside app/api/insights.py: ByActorResponse/ActorStat are
untouched. The frontend fetches both and merges client-side, same as it
already independently fetches overview/throughput/by-actor today. Mounted
at /api/insights/points/* so it rides the existing Next.js catch-all proxy
(frontend/app/api/insights/[...path]/route.ts) with zero proxy changes.

Reuses `_period_bounds`/`_ref` from app.api.insights rather than duplicating
the range/anchor -> (period_start, period_end) bucketing logic.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.api.insights import _period_bounds, _ref
from app.db import get_session
from app.models import Actor, Issue, PointsEvent, Team, UnscoredTicket
from app.schemas.insights import Range
from app.schemas.points import (
    PointsActorStat,
    PointsByActorResponse,
    PointsCategoryBreakdown,
    PointsLedgerEntry,
    PointsLedgerResponse,
    UnscoredResponse,
    UnscoredTicketItem,
)

router = APIRouter(
    prefix="/api/insights/points", tags=["points"], dependencies=[Depends(require_token)]
)


@router.get("/by-actor", response_model=PointsByActorResponse)
async def points_by_actor(
    range: Range = Query(default=Range.week),
    anchor: date | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> PointsByActorResponse:
    """Per-actor total Engineering Points (+ category breakdown) for the period.

    Sums every points_events row (award, reversal, bonus alike — they're all
    signed) whose `effective_at` falls in the window, so a revert that lands
    in-period correctly nets against its original award.
    """
    cs, ce, _, _ = _period_bounds(range, _ref(anchor))
    rows = (
        await session.execute(
            select(
                Actor.id, Actor.name, Actor.email, Actor.avatar_url,
                PointsEvent.category, func.sum(PointsEvent.points),
            )
            .join(PointsEvent, PointsEvent.actor_id == Actor.id)
            .where(PointsEvent.effective_at >= cs, PointsEvent.effective_at < ce)
            .group_by(Actor.id, Actor.name, Actor.email, Actor.avatar_url, PointsEvent.category)
        )
    ).all()

    by_actor: dict[int, dict] = {}
    for actor_id, name, email, avatar_url, category, points in rows:
        entry = by_actor.setdefault(
            actor_id,
            {
                "actor_id": actor_id, "name": name, "email": email, "avatar_url": avatar_url,
                "total_points": 0, "by_category": [],
            },
        )
        entry["total_points"] += int(points)
        entry["by_category"].append(PointsCategoryBreakdown(category=category, points=int(points)))

    actors = sorted(
        (PointsActorStat(**v) for v in by_actor.values()), key=lambda a: a.total_points, reverse=True
    )
    return PointsByActorResponse(range=range, period_start=cs, period_end=ce, actors=actors)


@router.get("/ledger", response_model=PointsLedgerResponse)
async def points_ledger(
    actor_id: int | None = Query(default=None),
    issue_id: int | None = Query(default=None),
    range: Range = Query(default=Range.week),
    anchor: date | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> PointsLedgerResponse:
    """Raw ledger rows — proves revert/RCA history stays legible (never rewritten)."""
    cs, ce, _, _ = _period_bounds(range, _ref(anchor))
    conditions = [PointsEvent.effective_at >= cs, PointsEvent.effective_at < ce]
    if actor_id is not None:
        conditions.append(PointsEvent.actor_id == actor_id)
    if issue_id is not None:
        conditions.append(PointsEvent.issue_id == issue_id)

    base = (
        select(PointsEvent, Issue.identifier, Issue.title, Actor.name)
        .join(Issue, Issue.id == PointsEvent.issue_id)
        .outerjoin(Actor, Actor.id == PointsEvent.actor_id)
        .where(*conditions)
    )
    total = (
        await session.execute(select(func.count()).select_from(base.with_only_columns(PointsEvent.id).subquery()))
    ).scalar_one()
    rows = (
        await session.execute(
            base.order_by(PointsEvent.effective_at.desc()).limit(limit).offset(offset)
        )
    ).all()

    entries = [
        PointsLedgerEntry(
            id=pe.id, issue_id=pe.issue_id, identifier=identifier, title=title,
            actor_id=pe.actor_id, name=name, category=pe.category, event_kind=pe.event_kind,
            points=pe.points, rule_key=pe.rule_key, label_state=pe.label_state,
            effective_at=pe.effective_at, awarded_at=pe.awarded_at,
            reverses_event_id=pe.reverses_event_id, related_event_id=pe.related_event_id,
        )
        for pe, identifier, title, name in rows
    ]
    return PointsLedgerResponse(entries=entries, total=total)


@router.get("/unscored", response_model=UnscoredResponse)
async def unscored_tickets(
    range: Range = Query(default=Range.week),  # noqa: ARG001 — see note below
    session: AsyncSession = Depends(get_session),
) -> UnscoredResponse:
    """Currently-unresolved unscored tickets (a queue, not a period-scoped
    metric — every outstanding ticket is returned regardless of when it was
    detected). `range` is accepted only for URL symmetry with the other
    points endpoints."""
    rows = (
        await session.execute(
            select(UnscoredTicket, Issue.identifier, Issue.title, Actor.name, Team.name)
            .join(Issue, Issue.id == UnscoredTicket.issue_id)
            .outerjoin(Actor, Actor.id == UnscoredTicket.assignee_id)
            .outerjoin(Team, Team.id == Issue.team_id)
            .where(UnscoredTicket.resolved_at.is_(None))
            .order_by(UnscoredTicket.first_detected_at)
        )
    ).all()
    tickets = [
        UnscoredTicketItem(
            issue_id=ut.issue_id, identifier=identifier, title=title,
            assignee_id=ut.assignee_id, assignee_name=name, reason=ut.reason,
            first_detected_at=ut.first_detected_at, last_checked_at=ut.last_checked_at,
            notified_at=ut.notified_at, team=team,
        )
        for ut, identifier, title, name, team in rows
    ]
    return UnscoredResponse(range=range, tickets=tickets)
