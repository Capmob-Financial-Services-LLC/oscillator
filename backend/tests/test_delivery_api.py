"""Delivery score end to end: seeded issues -> /api/insights/delivery -> counts and score.
Requires a live DATABASE_URL (skipped otherwise); wipes the tables it uses."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.main import app

# One event loop for the whole module: the async engine's pool binds to the
# loop that first used it (see test_points_api.py's docstring).
pytestmark = [
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires a live DATABASE_URL"),
    pytest.mark.asyncio(loop_scope="module"),
]

_TOKEN = "test-dashboard-token"
TODAY = date(2026, 10, 3)

# (identifier, state_type, completed on, target date)
ROWS = [
    ("#1", "completed", "2026-09-25", "2026-09-27"),  # on time
    ("#2", "completed", "2026-09-27", "2026-09-27"),  # on time: on the day counts
    ("#3", "completed", "2026-10-01", "2026-09-27"),  # late by 4 days
    ("#4", "started", None, "2026-09-30"),            # overdue by 3 days
    ("#5", "unstarted", None, "2026-10-06"),          # due in 3 days: not scored
    ("#6", "canceled", None, "2026-09-25"),           # cancelled: ignored
    ("#7", "completed", "2026-09-10", "2026-09-12"),  # before the window: ignored
    ("#8", "completed", "2026-09-26", None),          # undated: ignored
]


TEAM_SQL = "INSERT INTO teams (github_id, key, name) VALUES ('r1','BSA','BSA') RETURNING id"
ACTOR_SQL = "INSERT INTO actors (github_id, name) VALUES ('u1','Ada') RETURNING id"
ISSUE_SQL = (
    "INSERT INTO issues (github_id, identifier, title, team_id, assignee_id, state_type,"
    " source, completed_at, target_date)"
    " VALUES (:g, :i, :t, :team, :a, :st, 'github', :done, :target)"
)


def _utc_noon(day: str | None) -> datetime | None:
    # A timestamp, not a bare date: the server would read a date as local midnight.
    return datetime.fromisoformat(day + "T12:00:00").replace(tzinfo=UTC) if day else None


def _day(day: str | None) -> date | None:
    return date.fromisoformat(day) if day else None


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _seed():
    os.environ["DASHBOARD_AUTH_TOKEN"] = _TOKEN
    os.environ["GITHUB_SYNC_ORG"] = "Capmob-Financial-Services-LLC"
    get_settings.cache_clear()
    Session = get_sessionmaker()
    async with Session() as s, s.begin():
        for t in ("points_unscored_tickets", "points_events", "issue_tag_history",
                  "issue_tags", "issues", "tags", "actors", "teams", "sync_state"):
            await s.execute(text(f"DELETE FROM {t}"))
        team = (await s.execute(text(TEAM_SQL))).scalar()
        ada = (await s.execute(text(ACTOR_SQL))).scalar()
        for i, (ident, st, done, target) in enumerate(ROWS):
            await s.execute(text(ISSUE_SQL), {
                "g": f"i{i}", "i": ident, "t": f"Issue {ident}", "team": team, "a": ada,
                "st": st, "done": _utc_noon(done), "target": _day(target),
            })
    yield
    # Drop pooled connections bound to this module's event loop, so the next
    # test module's loop starts from a clean pool.
    await get_engine().dispose()


async def _get(path: str) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(path, headers={"Authorization": f"Bearer {_TOKEN}"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_counts_and_score():
    body = await _get(f"/api/insights/delivery?today={TODAY}")
    ada = body["by_actor"][0]
    assert (ada["on_time"], ada["late"], ada["overdue"], ada["due_soon"]) == (2, 1, 1, 1)
    assert ada["avg_days_late"] == 4.0
    assert ada["score"] == 50  # 2 on time of 4 that were due
    assert body["totals"]["score"] == 50


async def test_lists_and_links():
    body = await _get(f"/api/insights/delivery?today={TODAY}")
    assert [(d["identifier"], d["days"]) for d in body["overdue"]] == [("#4", 3)]
    assert [(d["identifier"], d["days"]) for d in body["due_soon"]] == [("#5", 3)]
    assert body["overdue"][0]["url"] == "https://github.com/Capmob-Financial-Services-LLC/BSA/issues/4"


async def test_nothing_due_means_no_score():
    body = await _get("/api/insights/delivery?today=2026-10-03&since=2026-12-01")
    assert body["by_actor"] == [] and body["totals"]["score"] is None


async def test_requires_the_token():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/api/insights/delivery")).status_code in (401, 403)
