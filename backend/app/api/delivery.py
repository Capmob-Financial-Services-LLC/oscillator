"""Delivery score: was dated work done by its Target date.

For every issue with a target_date in the window, by assignee:

  on_time   completed on or before its target date
  late      completed after it (avg_days_late says by how much)
  overdue   still open, and its target date has passed
  due_soon  still open, due within the next 7 days (shown, not scored)

  score = 100 x on_time / (on_time + late + overdue)

Overdue counts against the score exactly like late work: a date that has
passed is a miss whether or not the issue is ever closed. Cancelled issues
are excluded. Issues with no target date are invisible here by design: the
measure is "did we keep the dates we set", and an undated issue set none.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_token
from app.config import get_settings
from app.db import get_session
from app.schemas.delivery import DatedIssue, DeliveryResponse, DeliveryStat

router = APIRouter(prefix="/api/delivery", tags=["delivery"], dependencies=[Depends(require_token)])

# The 31 Oct plan's first sprint. The default window starts here, so the score
# covers exactly the period the dates were set for.
PLAN_START = date(2026, 9, 21)
DUE_SOON_DAYS = 7

_BASE = """
    SELECT i.identifier, i.title, i.source, i.target_date, i.state_type,
           (i.completed_at AT TIME ZONE 'UTC')::date AS done_on,
           t.name AS team, a.id AS actor_id, a.name AS actor, a.avatar_url
    FROM issues i
    LEFT JOIN teams t ON t.id = i.team_id
    LEFT JOIN actors a ON a.id = i.assignee_id
    WHERE i.target_date IS NOT NULL
      AND i.target_date >= :since
      AND coalesce(i.state_type, '') <> 'canceled'
"""


def _score(on_time: int, late: int, overdue: int) -> int | None:
    due = on_time + late + overdue
    return round(100 * on_time / due) if due else None


def _url(row, org: str) -> str | None:
    ident = row["identifier"] or ""
    if row["source"] == "github" and org and row["team"] and ident.startswith("#"):
        return f"https://github.com/{org}/{row['team']}/issues/{ident[1:]}"
    return None


@router.get("", response_model=DeliveryResponse)
async def delivery(
    since: date | None = Query(default=None, description="Window start; default: plan S1."),
    today: date | None = Query(default=None, description="Evaluate as of this day."),
    session: AsyncSession = Depends(get_session),
) -> DeliveryResponse:
    since = since or PLAN_START
    today = today or datetime.now(UTC).date()
    org = get_settings().github_sync_org
    rows = (await session.execute(text(_BASE), {"since": since})).mappings().all()

    per: dict[int | None, dict] = {}
    overdue_items: list[DatedIssue] = []
    soon_items: list[DatedIssue] = []
    for r in rows:
        bucket = per.setdefault(r["actor_id"], {
            "name": r["actor"] or "Unassigned", "avatar_url": r["avatar_url"],
            "on_time": 0, "late": 0, "overdue": 0, "due_soon": 0, "days_late": [],
        })
        target = r["target_date"]
        if r["state_type"] == "completed" and r["done_on"]:
            if r["done_on"] <= target:
                bucket["on_time"] += 1
            else:
                bucket["late"] += 1
                bucket["days_late"].append((r["done_on"] - target).days)
            continue
        if target < today:
            bucket["overdue"] += 1
            overdue_items.append(DatedIssue(
                identifier=r["identifier"], title=r["title"], team=r["team"], assignee=r["actor"],
                target_date=target, days=(today - target).days, url=_url(r, org)))
        elif target <= today + timedelta(days=DUE_SOON_DAYS):
            bucket["due_soon"] += 1
            soon_items.append(DatedIssue(
                identifier=r["identifier"], title=r["title"], team=r["team"], assignee=r["actor"],
                target_date=target, days=(target - today).days, url=_url(r, org)))

    def stat(actor_id, b) -> DeliveryStat:
        late_days = b["days_late"]
        return DeliveryStat(
            actor_id=actor_id, name=b["name"], avatar_url=b["avatar_url"],
            on_time=b["on_time"], late=b["late"], overdue=b["overdue"], due_soon=b["due_soon"],
            avg_days_late=round(sum(late_days) / len(late_days), 1) if late_days else None,
            score=_score(b["on_time"], b["late"], b["overdue"]),
        )

    by_actor = sorted((stat(k, v) for k, v in per.items()),
                      key=lambda s: (s.score is None, -(s.score or 0), s.name))
    all_late = [d for b in per.values() for d in b["days_late"]]
    totals = DeliveryStat(
        actor_id=None, name="Everyone",
        on_time=sum(s.on_time for s in by_actor), late=sum(s.late for s in by_actor),
        overdue=sum(s.overdue for s in by_actor), due_soon=sum(s.due_soon for s in by_actor),
        avg_days_late=round(sum(all_late) / len(all_late), 1) if all_late else None,
        score=_score(sum(s.on_time for s in by_actor), sum(s.late for s in by_actor),
                     sum(s.overdue for s in by_actor)),
    )
    return DeliveryResponse(
        since=since, today=today, totals=totals, by_actor=by_actor,
        overdue=sorted(overdue_items, key=lambda d: -d.days),
        due_soon=sorted(soon_items, key=lambda d: d.days),
    )
