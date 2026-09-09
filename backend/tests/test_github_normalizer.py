"""Functional tests for the GitHub normalizer — the label diffing
(upsert_github_issue_labels) and state resolution (upsert_github_issues),
mirroring test_zoho_normalizer.py's shape and coverage for the Zoho port.

Requires a real Postgres reachable via DATABASE_URL (skipped otherwise —
these exercise partitioned-table inserts and ON CONFLICT upserts that
sqlite can't emulate). Each phase opens its OWN session/transaction, exactly
like app/jobs/sync_github.py's run_github_sync().
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.db_partitions import ensure_partitions_around
from app.github.client import GitHubActor, GitHubIssue, GitHubLabel
from app.models import Issue, IssueTag, IssueTagHistory, Tag
from app.services import normalizer

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="requires a live DATABASE_URL"
)

_REPO = {"id": "repo-1", "name": "BSA"}


def _issue_node(
    number: int,
    *,
    label_names: list[str],
    state: str = "OPEN",
    state_reason: str | None = None,
    project_status: str | None = None,
    updated_at: str = "2026-09-01T00:00:00Z",
) -> dict:
    project_items = []
    if project_status is not None:
        project_items.append(
            {
                "project": {"title": "CAM MVP"},
                "fieldValueByName": {"name": project_status},
            }
        )
    return {
        "id": f"issue-{number}",
        "number": number,
        "title": f"Issue {number}",
        "state": state,
        "stateReason": state_reason,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": updated_at,
        "closedAt": "2026-09-01T00:00:00Z" if state == "CLOSED" else None,
        "author": {"login": "octocat", "id": "user-1"},
        "assignees": {"nodes": [{"id": "user-1", "login": "octocat", "name": "Octo Cat", "avatarUrl": None}]},
        "labels": {"nodes": [{"id": f"label-{n}", "name": n, "color": "ededed"} for n in label_names]},
        "milestone": None,
        "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        "projectItems": {"nodes": project_items},
    }


def _github_issue(number: int, **kwargs) -> GitHubIssue:
    return GitHubIssue.from_node(_issue_node(number, **kwargs), project_title="CAM MVP")


@pytest.mark.asyncio
async def test_github_issue_state_resolution_and_label_diffing():
    get_settings.cache_clear()
    engine = get_engine()
    Session = get_sessionmaker()

    async with engine.begin() as conn:
        await ensure_partitions_around(conn, datetime.now(UTC))

    async with Session() as session:
        async with session.begin():
            for table in ("issue_tag_history", "issue_tags", "issues", "tags", "actors", "teams"):
                await session.execute(text(f"DELETE FROM {table}"))

    # --- seed team / actor / labels (one phase per commit, matching sync_github.py) ---
    async with Session() as session:
        async with session.begin():
            await normalizer.upsert_github_team(session, _REPO)
    async with Session() as session:
        team_id = (
            await session.execute(text("SELECT id FROM teams WHERE github_id = 'repo-1'"))
        ).scalar_one()
    async with Session() as session:
        async with session.begin():
            await normalizer.upsert_github_actors(
                session, [GitHubActor.from_node({"id": "user-1", "login": "octocat", "name": "Octo Cat"})]
            )
    async with Session() as session:
        async with session.begin():
            await normalizer.upsert_github_labels(
                session,
                [
                    GitHubLabel.from_node({"id": "label-type:feat-be", "name": "type:feat-be", "color": "0e8a16"}),
                    GitHubLabel.from_node({"id": "label-size:m", "name": "size:m", "color": "5319e7"}),
                    GitHubLabel.from_node({"id": "label-reverted", "name": "reverted", "color": "b60205"}),
                ],
            )

    # --- run 1: an OPEN issue with a "Todo"-ish Status field, carrying type:feat-be + size:m ---
    issue = _github_issue(1, label_names=["type:feat-be", "size:m"], project_status="Todo")
    async with Session() as session:
        async with session.begin():
            n_issues, n_transitions = await normalizer.upsert_github_issues(session, [issue], team_id)
        assert n_issues == 1
        assert n_transitions == 1  # None -> backlog

        row = (
            await session.execute(
                select(Issue.state, Issue.state_type, Issue.identifier).where(Issue.github_id == "issue-1")
            )
        ).one()
        assert row.state_type == "backlog"  # "Todo" matches classify_status_name's backlog hints
        assert row.identifier == "#1"

    async with Session() as session:
        async with session.begin():
            n_touched, n_hist = await normalizer.upsert_github_issue_labels(session, [issue])
        assert n_touched == 2
        assert n_hist == 2

        issue_id = (
            await session.execute(select(Issue.id).where(Issue.github_id == "issue-1"))
        ).scalar_one()
        current = sorted(
            (
                await session.execute(
                    select(Tag.name)
                    .join(IssueTag, IssueTag.tag_id == Tag.id)
                    .where(IssueTag.issue_id == issue_id, IssueTag.removed_at.is_(None))
                )
            ).scalars().all()
        )
        assert current == ["size:m", "type:feat-be"]

    # --- run 2: same label state — idempotent no-op ---
    async with Session() as session:
        async with session.begin():
            n_touched, n_hist = await normalizer.upsert_github_issue_labels(session, [issue])
        assert (n_touched, n_hist) == (0, 0)

    # --- run 3: issue closed via the CAM MVP board's "Done" status, "reverted" label added ---
    issue_v2 = _github_issue(
        1, label_names=["type:feat-be", "size:m", "reverted"],
        state="CLOSED", project_status="Done", updated_at="2026-09-02T00:00:00Z",
    )
    async with Session() as session:
        async with session.begin():
            n_issues, n_transitions = await normalizer.upsert_github_issues(session, [issue_v2], team_id)
        assert n_transitions == 1  # backlog -> completed

        row = (
            await session.execute(
                select(Issue.state_type, Issue.completed_at).where(Issue.github_id == "issue-1")
            )
        ).one()
        assert row.state_type == "completed"
        assert row.completed_at is not None

    async with Session() as session:
        async with session.begin():
            n_touched, n_hist = await normalizer.upsert_github_issue_labels(session, [issue_v2])
        assert n_touched == 1  # "reverted" added
        assert n_hist == 1

        history_actions = sorted(
            (
                await session.execute(
                    select(IssueTagHistory.action).where(IssueTagHistory.issue_id == issue_id)
                )
            ).scalars().all()
        )
        assert history_actions == ["added", "added", "added"]

    # --- CLOSED + stateReason=NOT_PLANNED (no project Status field) -> canceled ---
    issue_np = _github_issue(2, label_names=[], state="CLOSED", state_reason="NOT_PLANNED")
    async with Session() as session:
        async with session.begin():
            await normalizer.upsert_github_issues(session, [issue_np], team_id)
        row = (
            await session.execute(select(Issue.state_type).where(Issue.github_id == "issue-2"))
        ).scalar_one()
        assert row == "canceled"

    await engine.dispose()
