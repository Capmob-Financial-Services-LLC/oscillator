"""GitHub issue dates: the Start/Target date issue fields are parsed and
stored, and Start date becomes started_at only for work that really started.
Requires a live DATABASE_URL (skipped otherwise); wipes the tables it uses."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.db import get_engine, get_sessionmaker
from app.github.client import GitHubIssue
from app.models import Issue
from app.services import normalizer

pytestmark = [
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="requires a live DATABASE_URL"),
    pytest.mark.asyncio(loop_scope="module"),
]


def _node(
    number: int, state: str, status: str | None, start: str | None, target: str | None
) -> dict:
    fields = [
        {"value": v, "field": {"name": n}}
        for n, v in (("Start date", start), ("Target date", target))
        if v
    ]
    items = (
        [{"project": {"title": "capmob.ai"}, "fieldValueByName": {"name": status}}]
        if status
        else []
    )
    return {
        "id": f"gh-{number}",
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "stateReason": "COMPLETED" if state == "CLOSED" else None,
        "createdAt": "2026-09-20T09:00:00Z",
        "updatedAt": "2026-10-01T09:00:00Z",
        "closedAt": "2026-10-01T09:00:00Z" if state == "CLOSED" else None,
        "author": None,
        "assignees": {"nodes": []},
        "labels": {"nodes": []},
        "comments": {"nodes": []},
        "projectItems": {"nodes": items},
        "issueFieldValues": {"nodes": fields},
    }


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _clean():
    Session = get_sessionmaker()
    async with Session() as s, s.begin():
        for t in (
            "points_unscored_tickets",
            "points_events",
            "issue_tag_history",
            "issue_tags",
            "issues",
            "tags",
            "actors",
            "teams",
            "sync_state",
        ):
            await s.execute(text(f"DELETE FROM {t}"))
    yield
    await get_engine().dispose()


def test_dates_are_parsed():
    issue = GitHubIssue.from_node(
        _node(1, "OPEN", "Ready", "2026-09-22", "2026-10-04"), project_title="capmob.ai"
    )
    assert (issue.start_date, issue.target_date) == (date(2026, 9, 22), date(2026, 10, 4))


async def test_start_date_becomes_started_at_only_for_started_work():
    issues = [
        GitHubIssue.from_node(
            _node(1, "CLOSED", None, "2026-09-22", "2026-09-27"), project_title="capmob.ai"
        ),
        GitHubIssue.from_node(
            _node(2, "OPEN", "In progress", "2026-09-29", "2026-10-04"), project_title="capmob.ai"
        ),
        GitHubIssue.from_node(
            _node(3, "OPEN", "Ready", "2026-10-05", "2026-10-11"), project_title="capmob.ai"
        ),
        GitHubIssue.from_node(
            _node(4, "OPEN", "In progress", None, None), project_title="capmob.ai"
        ),
    ]
    Session = get_sessionmaker()
    async with Session() as s, s.begin():
        await normalizer.upsert_github_issues(s, issues, team_id=None)
    async with Session() as s:
        rows = {r.identifier: r for r in (await s.execute(select(Issue))).scalars()}
    assert rows["#1"].started_at == datetime(2026, 9, 22, tzinfo=UTC)  # completed
    assert rows["#2"].started_at == datetime(2026, 9, 29, tzinfo=UTC)  # in progress
    assert rows["#3"].started_at is None  # not started: a planned date is not a start
    assert rows["#4"].started_at is None  # no Start date: never guessed
    assert rows["#1"].target_date == date(2026, 9, 27)
