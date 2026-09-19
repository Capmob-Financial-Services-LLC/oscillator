"""Functional tests for app/jobs/merge_actors.py — the identity-merge tool
for a person who exists as both a Linear actor and a GitHub actor.

Requires a real Postgres reachable via DATABASE_URL (skipped otherwise).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.db_partitions import ensure_partitions_around
from app.jobs.merge_actors import ResolveError, _resolve_actor, merge_actor, run_merge
from app.models import Actor, Comment, Issue, PointsEvent

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="requires a live DATABASE_URL"
)


async def _reset(session):
    for table in (
        "points_events", "comments", "issue_history", "issues", "actors",
    ):
        await session.execute(text(f"DELETE FROM {table}"))


@pytest.mark.asyncio
async def test_merge_repoints_every_referencing_table_and_folds_ids():
    get_settings.cache_clear()
    engine = get_engine()
    Session = get_sessionmaker()

    async with engine.begin() as conn:
        await ensure_partitions_around(conn, datetime.now(UTC))

    async with Session() as session:
        async with session.begin():
            await _reset(session)

            keep = Actor(linear_id="lin-sachin", name="Sachin", email="sachin@example.com")
            dup = Actor(github_id="gh-sachin", name="sachin-capmob", avatar_url="http://x/a.png")
            session.add_all([keep, dup])
            await session.flush()

            # A Linear-sourced issue credited to the Linear actor, and a
            # GitHub-sourced issue credited to the GitHub duplicate.
            linear_issue = Issue(
                linear_id="lin-issue-1", title="Old work", assignee_id=keep.id,
                creator_id=keep.id, source="linear",
            )
            github_issue = Issue(
                github_id="gh-issue-1", title="New work", assignee_id=dup.id,
                creator_id=dup.id, source="github",
            )
            session.add_all([linear_issue, github_issue])
            await session.flush()

            session.add(Comment(linear_id="c-1", issue_id=linear_issue.id, actor_id=keep.id, body="hi"))
            session.add(Comment(github_id="c-2", issue_id=github_issue.id, actor_id=dup.id, body="hey"))
            session.add(
                PointsEvent(
                    issue_id=github_issue.id, actor_id=dup.id, category="feature_be",
                    event_kind="award", points=7, rule_key="feature_be:size:m",
                    rules_version="test", effective_at=datetime.now(UTC),
                )
            )
            keep_id, dup_id = keep.id, dup.id

    # --- dry run must NOT commit anything ---
    dry_results = await run_merge([("id:" + str(keep_id), "id:" + str(dup_id))], apply=False)
    assert len(dry_results) == 1
    async with Session() as session:
        still_two = (await session.execute(select(Actor.id).where(Actor.id.in_([keep_id, dup_id])))).scalars().all()
        assert sorted(still_two) == sorted([keep_id, dup_id])  # neither row touched

    # --- real merge ---
    results = await run_merge([("id:" + str(keep_id), "id:" + str(dup_id))], apply=True)
    assert len(results) == 1
    r = results[0]
    assert r["kept"]["id"] == keep_id
    assert r["removed"]["id"] == dup_id
    assert r["repointed"] == {
        "issues.assignee_id": 1,
        "issues.creator_id": 1,
        "comments.actor_id": 1,
        "points_events.actor_id": 1,
    }
    assert set(r["folded_fields"]) == {"github_id", "avatar_url"}

    async with Session() as session:
        # duplicate is gone
        assert (await session.execute(select(Actor).where(Actor.id == dup_id))).scalar_one_or_none() is None

        merged = (await session.execute(select(Actor).where(Actor.id == keep_id))).scalar_one()
        assert merged.linear_id == "lin-sachin"
        assert merged.github_id == "gh-sachin"  # folded from the duplicate
        assert merged.email == "sachin@example.com"  # kept row's own value untouched
        assert merged.avatar_url == "http://x/a.png"  # folded, kept row had none

        # both issues (one from each source) now point at the single actor
        assignees = (
            await session.execute(select(Issue.assignee_id).where(Issue.id.in_([linear_issue.id, github_issue.id])))
        ).scalars().all()
        assert all(a == keep_id for a in assignees)

        # the GitHub-sourced points award moved with its issue's actor
        pe_actor = (await session.execute(select(PointsEvent.actor_id))).scalar_one()
        assert pe_actor == keep_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_ambiguous_name_is_reported_not_guessed():
    get_settings.cache_clear()
    engine = get_engine()
    Session = get_sessionmaker()

    async with Session() as session:
        async with session.begin():
            await _reset(session)
            session.add_all(
                [
                    Actor(linear_id="lin-a", name="Sam"),
                    Actor(github_id="gh-a", name="Sam"),
                ]
            )

    async with Session() as session:
        with pytest.raises(ResolveError, match="Ambiguous name"):
            await _resolve_actor(session, "Sam")

    await engine.dispose()
