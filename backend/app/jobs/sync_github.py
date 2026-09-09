"""Cron sync entrypoint:  python -m app.jobs.sync_github

Structurally mirrors app/jobs/sync.py (Linear): same watermark-in-sync_state
pattern, same phased-transaction / refresh-views / non-fatal-analytics
skeleton. Pulls from a single GitHub repo (the CAM MVP board's tracked repo)
via app/github/client.py.

Unlike Linear/Zoho, `since` filtering applies ONLY to issues (GitHub's
`filterBy.since` on the issues connection, same semantics as Linear's
`updatedAt: {gt: $since}`) — labels, assignable users, and milestones are
small, cheap-to-paginate dimensions re-pulled in full every run, same
reasoning sync_zoho.py already gives for teams/users there. Comments ride
along inside each fetched issue (see app/github/client.py), so there is no
separate comments phase.

Watermark: last_synced_at in sync_state (key='github'). Advances only after
every phase below succeeds, same all-or-nothing safety net as sync.py.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import get_engine, get_sessionmaker
from app.db_partitions import ensure_partitions_around
from app.github.client import GitHubClient
from app.jobs.sync import refresh_all_views
from app.models import SyncState
from app.services import normalizer
from app.services.anomaly import detect_anomalies
from app.services.digest import generate_digests

logger = logging.getLogger("app.sync_github")

WATERMARK_KEY = "github"
OVERLAP = timedelta(minutes=5)


async def _read_watermark(session) -> datetime | None:
    res = await session.execute(
        select(SyncState.last_synced_at).where(SyncState.key == WATERMARK_KEY)
    )
    return res.scalar_one_or_none()


async def _write_watermark(session, ts: datetime) -> None:
    stmt = pg_insert(SyncState).values(key=WATERMARK_KEY, last_synced_at=ts)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.key], set_={"last_synced_at": ts}
    )
    await session.execute(stmt)


async def run_github_sync() -> dict:
    run_start = datetime.now(UTC)
    engine = get_engine()
    Session = get_sessionmaker()

    async with engine.begin() as conn:
        await ensure_partitions_around(conn, run_start)

    async with Session() as session:
        last = await _read_watermark(session)
    since = (last - OVERLAP) if last else None
    mode = "incremental" if last else "full backfill"
    logger.info("GitHub sync start (%s); previous watermark=%s", mode, last.isoformat() if last else None)

    # --- pull from GitHub ---
    async with GitHubClient() as client:
        repo = await client.fetch_repo()
        labels = await client.fetch_labels()
        users = await client.fetch_assignable_users()
        milestones = await client.fetch_milestones()
        issues = await client.fetch_issues(since)

    comments = [c for it in issues for c in it.comments]

    pulled = {
        "labels": len(labels), "users": len(users), "milestones": len(milestones),
        "issues": len(issues), "comments": len(comments),
    }
    logger.info("Pulled: %s", pulled)

    # --- normalize (dependency order; commit per phase) ---
    counts: dict[str, int] = {}
    async with Session() as session:
        async with session.begin():
            counts["teams"] = await normalizer.upsert_github_team(session, repo)
    # Own session for the plain read: reusing the same session for a bare
    # execute() between two session.begin() blocks autobegins an implicit
    # transaction that the next explicit session.begin() then trips over
    # ("A transaction is already begun on this Session").
    async with Session() as session:
        team_id = (
            await session.execute(
                select(normalizer.Team.id).where(normalizer.Team.github_id == repo["id"])
            )
        ).scalar_one()

    async with Session() as session:
        async with session.begin():
            counts["actors"] = await normalizer.upsert_github_actors(session, users)
        async with session.begin():
            counts["labels"] = await normalizer.upsert_github_labels(session, labels)
        async with session.begin():
            counts["milestones"] = await normalizer.upsert_github_milestones(
                session, milestones, team_id
            )
        async with session.begin():
            counts["issues"], counts["transitions"] = await normalizer.upsert_github_issues(
                session, issues, team_id
            )
        async with session.begin():
            counts["issue_tags"], counts["tag_history"] = await normalizer.upsert_github_issue_labels(
                session, issues
            )
        async with session.begin():
            counts["comments"] = await normalizer.upsert_github_comments(session, comments)
    logger.info("Upserted: %s", counts)

    # --- refresh rollups ---
    views = await refresh_all_views(engine)

    # --- derived analytics: anomaly flags + narrative digest ---
    analytics: dict[str, int] = {"anomalies": 0, "digests": 0}
    try:
        async with Session() as session:
            async with session.begin():
                analytics["anomalies"] = await detect_anomalies(session)
            async with session.begin():
                analytics["digests"] = await generate_digests(session, anchor=run_start.date())
    except Exception:  # noqa: BLE001 — analytics is non-critical to ingestion
        logger.exception("Derived analytics failed (non-fatal)")

    # --- advance watermark only after full success ---
    async with Session() as session:
        async with session.begin():
            await _write_watermark(session, run_start)
    logger.info("GitHub watermark advanced to %s", run_start.isoformat())

    return {
        "mode": mode, "watermark": run_start, "pulled": pulled,
        "upserted": counts, "views_refreshed": views, "analytics": analytics,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        result = asyncio.run(run_github_sync())
    except Exception:
        logger.exception("GitHub sync FAILED")
        return 1
    print("\n=== GITHUB SYNC SUMMARY ===")
    print(f"mode:       {result['mode']}")
    print(f"watermark:  {result['watermark'].isoformat()}")
    print(f"pulled:     {result['pulled']}")
    print(f"upserted:   {result['upserted']}")
    print(f"views:      {result['views_refreshed'] or '(none yet)'}")
    print(f"analytics:  {result['analytics']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
