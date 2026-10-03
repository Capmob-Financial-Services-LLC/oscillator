"""Delivery: was dated work finished by its Target date.

A second measure beside Engineering Points, not a change to them. Points
answer "how much was shipped"; delivery answers "was it shipped when promised".
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DeliveryStat(BaseModel):
    actor_id: int | None
    name: str
    avatar_url: str | None = None
    on_time: int
    late: int
    overdue: int
    due_soon: int
    avg_days_late: float | None
    # 100 x on_time / (on_time + late + overdue); None when nothing was due.
    score: int | None


class DatedIssue(BaseModel):
    identifier: str | None
    title: str | None
    team: str | None
    assignee: str | None
    target_date: date
    days: int  # past the date when overdue (positive), until it when due soon
    url: str | None


class DeliveryResponse(BaseModel):
    since: date
    today: date
    totals: DeliveryStat
    by_actor: list[DeliveryStat]
    overdue: list[DatedIssue]
    due_soon: list[DatedIssue]
