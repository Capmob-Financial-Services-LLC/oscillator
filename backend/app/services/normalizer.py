"""Normalize Linear DTOs into the typed tables.

Each entity is first landed append-only in ``raw_events`` (payload = the original
GraphQL node), then upserted (ON CONFLICT DO UPDATE keyed on linear_id). Issue
state transitions are derived by comparing the incoming state against what is
already stored — so the pipeline is fully idempotent and overlap-safe (re-syncing
the same record produces no duplicate transition because, post-upsert, the stored
state already equals the incoming one).

Surrogate FK ids are resolved from linear_id via lookup maps read from the DB,
so references resolve even when the referenced row was ingested on a prior run.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_partitions import ensure_month_partition
from app.github.client import (
    GitHubActor,
    GitHubComment,
    GitHubIssue,
    GitHubLabel,
    GitHubMilestone,
)
from app.github.mapping import resolve_state
from app.linear.client import (
    LinearComment,
    LinearCycle,
    LinearIssue,
    LinearTeam,
    LinearUser,
)
from app.models import (
    Actor,
    Comment,
    Cycle,
    Epic,
    Issue,
    IssueHistory,
    IssueTag,
    IssueTagHistory,
    Project,
    RawEvent,
    StatusDef,
    Tag,
    Team,
)
from app.zoho.client import (
    ZohoComment,
    ZohoEpic,
    ZohoItem,
    ZohoProject,
    ZohoSprint,
    ZohoTag,
    ZohoTeam,
    ZohoUser,
)
from app.zoho.mapping import classify_status_name

logger = logging.getLogger("app.normalizer")


async def _land_raw(
    session: AsyncSession, event_type: str, dtos: Iterable, *, source: str = "linear"
) -> None:
    rows = [
        {"event_type": event_type, "action": "sync", "payload": d.raw, "source": source}
        for d in dtos
    ]
    if rows:
        await session.execute(pg_insert(RawEvent), rows)


async def _id_map(session: AsyncSession, model, id_col: str = "linear_id") -> dict[str, int]:
    """Surrogate-id lookup keyed on either source's natural id.

    `id_col` is "linear_id" (default, every existing call site) or
    "zoho_id" — since a row carries at most one of the two (see the
    nullable-linear_id migration 0008), filtering NOT NULL on the chosen
    column keeps the two source's maps disjoint with no risk of collision.
    """
    col = getattr(model, id_col)
    res = await session.execute(select(col, model.id).where(col.is_not(None)))
    return {key: surrogate for key, surrogate in res.all()}


async def upsert_teams(session: AsyncSession, teams: list[LinearTeam]) -> int:
    if not teams:
        return 0
    await _land_raw(session, "Team", teams)
    rows = [
        {"linear_id": t.id, "key": t.key, "name": t.name, "archived_at": t.archived_at}
        for t in teams
    ]
    stmt = pg_insert(Team).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.linear_id],
        set_={
            "key": stmt.excluded.key,
            "name": stmt.excluded.name,
            "archived_at": stmt.excluded.archived_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_actors(session: AsyncSession, users: list[LinearUser]) -> int:
    if not users:
        return 0
    await _land_raw(session, "User", users)
    rows = [
        {
            "linear_id": u.id,
            "name": u.name,
            "email": u.email,
            "avatar_url": u.avatar_url,
            "active": u.active,
        }
        for u in users
    ]
    stmt = pg_insert(Actor).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Actor.linear_id],
        set_={
            "name": stmt.excluded.name,
            "email": stmt.excluded.email,
            "avatar_url": stmt.excluded.avatar_url,
            "active": stmt.excluded.active,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_cycles(session: AsyncSession, cycles: list[LinearCycle]) -> int:
    if not cycles:
        return 0
    await _land_raw(session, "Cycle", cycles)
    team_map = await _id_map(session, Team)
    rows = [
        {
            "linear_id": c.id,
            "team_id": team_map.get(c.team_id),
            "number": c.number,
            "name": c.name,
            "starts_at": c.starts_at,
            "ends_at": c.ends_at,
            "completed_at": c.completed_at,
        }
        for c in cycles
    ]
    stmt = pg_insert(Cycle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Cycle.linear_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "number": stmt.excluded.number,
            "name": stmt.excluded.name,
            "starts_at": stmt.excluded.starts_at,
            "ends_at": stmt.excluded.ends_at,
            "completed_at": stmt.excluded.completed_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_issues(session: AsyncSession, issues: list[LinearIssue]) -> tuple[int, int]:
    """Upsert issues and record state transitions. Returns (upserted, transitions)."""
    if not issues:
        return 0, 0
    await _land_raw(session, "Issue", issues)

    team_map = await _id_map(session, Team)
    actor_map = await _id_map(session, Actor)
    cycle_map = await _id_map(session, Cycle)

    # Snapshot stored state BEFORE upserting so we can diff transitions.
    res = await session.execute(
        select(Issue.linear_id, Issue.state, Issue.state_type)
    )
    stored = {lid: (st, stt) for lid, st, stt in res.all()}

    transitions: list[dict] = []
    for it in issues:
        prev = stored.get(it.id)
        changed_at = it.updated_at or it.created_at or datetime.now(UTC)
        if prev is None:
            # New issue: record an initial (null -> current) baseline transition.
            transitions.append(
                {
                    "issue_linear_id": it.id,
                    "changed_at": changed_at,
                    "from_state": None,
                    "from_state_type": None,
                    "to_state": it.state,
                    "to_state_type": it.state_type,
                }
            )
        elif prev[0] != it.state or prev[1] != it.state_type:
            transitions.append(
                {
                    "issue_linear_id": it.id,
                    "changed_at": changed_at,
                    "from_state": prev[0],
                    "from_state_type": prev[1],
                    "to_state": it.state,
                    "to_state_type": it.state_type,
                }
            )

    rows = [
        {
            "linear_id": it.id,
            "identifier": it.identifier,
            "title": it.title,
            "team_id": team_map.get(it.team_id),
            "assignee_id": actor_map.get(it.assignee_id),
            "creator_id": actor_map.get(it.creator_id),
            "cycle_id": cycle_map.get(it.cycle_id),
            "state": it.state,
            "state_type": it.state_type,
            "priority": it.priority,
            "estimate": it.estimate,
            "project_id": it.project_id,
            "created_at": it.created_at,
            "started_at": it.started_at,
            "completed_at": it.completed_at,
            "canceled_at": it.canceled_at,
            "updated_at": it.updated_at,
        }
        for it in issues
    ]
    stmt = pg_insert(Issue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Issue.linear_id],
        set_={
            c: getattr(stmt.excluded, c)
            for c in (
                "identifier", "title", "team_id", "assignee_id", "creator_id",
                "cycle_id", "state", "state_type", "priority", "estimate",
                "project_id", "created_at", "started_at", "completed_at",
                "canceled_at", "updated_at",
            )
        }
        | {"row_updated_at": func.now()},
    )
    await session.execute(stmt)

    n_transitions = await _write_transitions(session, transitions, actor_map=actor_map)
    return len(rows), n_transitions


async def _write_transitions(
    session: AsyncSession, transitions: list[dict], *, actor_map: dict[str, int]
) -> int:
    if not transitions:
        return 0
    # Resolve issue surrogate ids now that all issues are upserted.
    issue_map = await _id_map(session, Issue)

    # Ensure a monthly partition exists for every changed_at month before inserting.
    conn = await session.connection()
    months = {(t["changed_at"].year, t["changed_at"].month) for t in transitions}
    for year, month in sorted(months):
        await ensure_month_partition(conn, "issue_history", datetime(year, month, 1, tzinfo=UTC))

    rows = []
    for t in transitions:
        issue_id = issue_map.get(t["issue_linear_id"])
        if issue_id is None:
            continue
        rows.append(
            {
                "issue_id": issue_id,
                "changed_at": t["changed_at"],
                "linear_id": None,  # compare-based; no Linear history node id
                "actor_id": None,   # actor unknown without history API
                "from_state": t["from_state"],
                "from_state_type": t["from_state_type"],
                "to_state": t["to_state"],
                "to_state_type": t["to_state_type"],
            }
        )
    if rows:
        await session.execute(pg_insert(IssueHistory), rows)
    return len(rows)


async def upsert_comments(session: AsyncSession, comments: list[LinearComment]) -> int:
    if not comments:
        return 0
    await _land_raw(session, "Comment", comments)
    issue_map = await _id_map(session, Issue)
    actor_map = await _id_map(session, Actor)

    rows = []
    skipped = 0
    for c in comments:
        issue_id = issue_map.get(c.issue_id)
        if issue_id is None:
            skipped += 1  # comment on an issue we have not ingested; skip (issue_id is NOT NULL)
            continue
        rows.append(
            {
                "linear_id": c.id,
                "issue_id": issue_id,
                "actor_id": actor_map.get(c.user_id),
                "body": c.body,
                "created_at": c.created_at,
            }
        )
    if skipped:
        logger.warning("Skipped %d comments referencing unknown issues", skipped)
    if not rows:
        return 0
    stmt = pg_insert(Comment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Comment.linear_id],
        set_={
            "issue_id": stmt.excluded.issue_id,
            "actor_id": stmt.excluded.actor_id,
            "body": stmt.excluded.body,
            "created_at": stmt.excluded.created_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


# =============================================================================
# Zoho Sprints — separate upsert functions (own DTOs, own natural key column
# `zoho_id`) writing into the SAME tables Linear normalizes into, so every
# existing insights query/matview works over both sources with no changes.
# Kept structurally distinct from the Linear functions above rather than
# genericized, since the two DTO shapes differ enough that a shared function
# would need per-source branches anyway — this way the Linear path stays
# byte-for-byte unchanged.
# =============================================================================

_ZOHO_SOURCE = "zoho_sprints"


async def upsert_zoho_teams(session: AsyncSession, teams: list[ZohoTeam]) -> int:
    if not teams:
        return 0
    await _land_raw(session, "ZohoTeam", teams, source=_ZOHO_SOURCE)
    rows = [{"zoho_id": t.id, "name": t.name} for t in teams]
    stmt = pg_insert(Team).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.zoho_id],
        set_={"name": stmt.excluded.name, "row_updated_at": func.now()},
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_zoho_actors(session: AsyncSession, users: list[ZohoUser]) -> int:
    if not users:
        return 0
    await _land_raw(session, "ZohoUser", users, source=_ZOHO_SOURCE)
    rows = [
        {
            "zoho_id": u.id,
            "name": u.name,
            "email": u.email,
            "avatar_url": u.avatar_url,
            "active": u.active,
        }
        for u in users
    ]
    stmt = pg_insert(Actor).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Actor.zoho_id],
        set_={
            "name": stmt.excluded.name,
            "email": stmt.excluded.email,
            "avatar_url": stmt.excluded.avatar_url,
            "active": stmt.excluded.active,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_projects(session: AsyncSession, projects: list[ZohoProject]) -> int:
    if not projects:
        return 0
    await _land_raw(session, "ZohoProject", projects, source=_ZOHO_SOURCE)
    team_map = await _id_map(session, Team, "zoho_id")
    rows = [
        {
            "zoho_id": p.id,
            "team_id": team_map.get(p.team_id),
            "key": p.key,
            "name": p.name,
            "archived_at": p.archived_at,
        }
        for p in projects
    ]
    stmt = pg_insert(Project).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Project.zoho_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "key": stmt.excluded.key,
            "name": stmt.excluded.name,
            "archived_at": stmt.excluded.archived_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_epics(session: AsyncSession, epics: list[ZohoEpic]) -> int:
    if not epics:
        return 0
    await _land_raw(session, "ZohoEpic", epics, source=_ZOHO_SOURCE)
    project_map = await _id_map(session, Project, "zoho_id")
    rows = [
        {"zoho_id": e.id, "project_id": project_map.get(e.project_id), "name": e.name}
        for e in epics
    ]
    stmt = pg_insert(Epic).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Epic.zoho_id],
        set_={
            "project_id": stmt.excluded.project_id,
            "name": stmt.excluded.name,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_zoho_sprints(session: AsyncSession, sprints: list[ZohoSprint]) -> int:
    """Zoho sprints land in the same `cycles` table Linear cycles use.

    A sprint only carries `project_id`; `cycles.team_id` is resolved via the
    project's team so the existing team-scoped rollups keep working unchanged.
    """
    if not sprints:
        return 0
    await _land_raw(session, "ZohoSprint", sprints, source=_ZOHO_SOURCE)
    project_map = await _id_map(session, Project, "zoho_id")
    proj_team = dict((await session.execute(select(Project.id, Project.team_id))).all())
    rows = []
    for s in sprints:
        proj_surrogate = project_map.get(s.project_id)
        rows.append(
            {
                "zoho_id": s.id,
                "team_id": proj_team.get(proj_surrogate) if proj_surrogate else None,
                "number": s.number,
                "name": s.name,
                "starts_at": s.starts_at,
                "ends_at": s.ends_at,
                "completed_at": s.completed_at,
            }
        )
    stmt = pg_insert(Cycle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Cycle.zoho_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "number": stmt.excluded.number,
            "name": stmt.excluded.name,
            "starts_at": stmt.excluded.starts_at,
            "ends_at": stmt.excluded.ends_at,
            "completed_at": stmt.excluded.completed_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_tags(session: AsyncSession, tags: list[ZohoTag]) -> int:
    if not tags:
        return 0
    await _land_raw(session, "ZohoTag", tags, source=_ZOHO_SOURCE)
    team_map = await _id_map(session, Team, "zoho_id")
    actor_map = await _id_map(session, Actor, "zoho_id")
    rows = [
        {
            "zoho_id": t.id,
            "team_id": team_map.get(t.team_id),
            "name": t.name,
            "color_code": t.color_code,
            "created_by_id": actor_map.get(t.created_by),
        }
        for t in tags
    ]
    stmt = pg_insert(Tag).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tag.zoho_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "name": stmt.excluded.name,
            "color_code": stmt.excluded.color_code,
            "created_by_id": stmt.excluded.created_by_id,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_items(session: AsyncSession, items: list[ZohoItem]) -> tuple[int, int]:
    """Upsert Zoho Sprints items into `issues` and record state transitions.

    Exactly the same snapshot-before-overwrite-then-diff shape as
    upsert_issues (Linear): land raw, resolve FK maps, diff (state,
    state_type) against what's stored, upsert, write transitions. The one
    extra step is resolving each item's status through `status_defs`,
    seeding a best-effort mapping (app.zoho.mapping.classify_status_name) the
    first time a (project, status) pair is seen — ON CONFLICT DO NOTHING, so
    a hand-corrected mapping is never clobbered by the heuristic on a later
    sync. Returns (upserted, transitions).
    """
    if not items:
        return 0, 0
    await _land_raw(session, "ZohoItem", items, source=_ZOHO_SOURCE)

    project_map = await _id_map(session, Project, "zoho_id")
    actor_map = await _id_map(session, Actor, "zoho_id")
    cycle_map = await _id_map(session, Cycle, "zoho_id")
    epic_map = await _id_map(session, Epic, "zoho_id")
    proj_team = dict((await session.execute(select(Project.id, Project.team_id))).all())

    # Seed status_defs for every (project, status) pair seen. DO NOTHING
    # preserves any existing (possibly hand-corrected) mapping.
    status_rows = []
    seen_status: set[tuple[int, str]] = set()
    for it in items:
        proj_surrogate = project_map.get(it.project_id)
        if proj_surrogate is None or it.status_id is None:
            continue
        key = (proj_surrogate, it.status_id)
        if key in seen_status:
            continue
        seen_status.add(key)
        status_rows.append(
            {
                "project_id": proj_surrogate,
                "zoho_status_id": it.status_id,
                "name": it.status_name,
                "state_type": classify_status_name(it.status_name),
            }
        )
    if status_rows:
        stmt = pg_insert(StatusDef).values(status_rows)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[StatusDef.project_id, StatusDef.zoho_status_id]
        )
        await session.execute(stmt)

    status_map: dict[tuple[int, str], str] = {}
    if seen_status:
        proj_ids = {pid for pid, _ in seen_status}
        res = await session.execute(
            select(StatusDef.project_id, StatusDef.zoho_status_id, StatusDef.state_type).where(
                StatusDef.project_id.in_(proj_ids)
            )
        )
        status_map = {(pid, sid): st for pid, sid, st in res.all()}

    # Snapshot stored state BEFORE upserting so we can diff transitions.
    res = await session.execute(
        select(Issue.zoho_id, Issue.state, Issue.state_type).where(Issue.zoho_id.is_not(None))
    )
    stored = {zid: (st, stt) for zid, st, stt in res.all()}

    transitions: list[dict] = []
    rows = []
    for it in items:
        proj_surrogate = project_map.get(it.project_id)
        state_type = (
            status_map.get((proj_surrogate, it.status_id))
            if proj_surrogate and it.status_id
            else None
        )
        state_name = it.status_name

        changed_at = it.updated_at or it.created_at or datetime.now(UTC)
        prev = stored.get(it.id)
        if prev is None:
            transitions.append(
                {
                    "issue_zoho_id": it.id,
                    "changed_at": changed_at,
                    "from_state": None,
                    "from_state_type": None,
                    "to_state": state_name,
                    "to_state_type": state_type,
                }
            )
        elif prev[0] != state_name or prev[1] != state_type:
            transitions.append(
                {
                    "issue_zoho_id": it.id,
                    "changed_at": changed_at,
                    "from_state": prev[0],
                    "from_state_type": prev[1],
                    "to_state": state_name,
                    "to_state_type": state_type,
                }
            )

        # No confirmed field distinguishes "cancelled" from "completed" on
        # the item payload itself (see app/zoho/client.py) — the terminal
        # timestamp is resolved from the status_defs-derived state_type
        # instead, using whichever completion-ish timestamp Zoho gave us.
        terminal_at = it.completed_at or it.updated_at
        completed_at = terminal_at if state_type == "completed" else None
        canceled_at = terminal_at if state_type == "canceled" else None

        rows.append(
            {
                "zoho_id": it.id,
                "identifier": it.identifier,
                "title": it.title,
                "team_id": proj_team.get(proj_surrogate) if proj_surrogate else None,
                "assignee_id": actor_map.get(it.owner_id),
                "creator_id": actor_map.get(it.created_by),
                "completed_by_id": actor_map.get(it.completed_by),
                "cycle_id": cycle_map.get(it.sprint_id),
                "epic_id": epic_map.get(it.epic_id),
                "zoho_project_id": proj_surrogate,
                "state": state_name,
                "state_type": state_type,
                "priority_label": it.priority_label,
                "estimate": it.points,
                "source": _ZOHO_SOURCE,
                "created_at": it.created_at,
                "started_at": it.started_at,
                "completed_at": completed_at,
                "canceled_at": canceled_at,
                "updated_at": it.updated_at,
            }
        )

    stmt = pg_insert(Issue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Issue.zoho_id],
        set_={
            c: getattr(stmt.excluded, c)
            for c in (
                "identifier", "title", "team_id", "assignee_id", "creator_id",
                "completed_by_id", "cycle_id", "epic_id", "zoho_project_id",
                "state", "state_type", "priority_label", "estimate", "source",
                "created_at", "started_at", "completed_at", "canceled_at", "updated_at",
            )
        }
        | {"row_updated_at": func.now()},
    )
    await session.execute(stmt)

    n_transitions = await _write_zoho_transitions(session, transitions)
    return len(rows), n_transitions


async def _write_zoho_transitions(session: AsyncSession, transitions: list[dict]) -> int:
    if not transitions:
        return 0
    issue_map = await _id_map(session, Issue, "zoho_id")

    conn = await session.connection()
    months = {(t["changed_at"].year, t["changed_at"].month) for t in transitions}
    for year, month in sorted(months):
        await ensure_month_partition(conn, "issue_history", datetime(year, month, 1, tzinfo=UTC))

    rows = []
    for t in transitions:
        issue_id = issue_map.get(t["issue_zoho_id"])
        if issue_id is None:
            continue
        rows.append(
            {
                "issue_id": issue_id,
                "changed_at": t["changed_at"],
                "linear_id": None,  # Zoho-sourced; no Linear history node id
                "actor_id": None,  # actor unknown without an activity-log API
                "from_state": t["from_state"],
                "from_state_type": t["from_state_type"],
                "to_state": t["to_state"],
                "to_state_type": t["to_state_type"],
            }
        )
    if rows:
        await session.execute(pg_insert(IssueHistory), rows)
    return len(rows)


async def upsert_item_tags(session: AsyncSession, items: list[ZohoItem]) -> tuple[int, int]:
    """Diff each item's incoming tag set against `issue_tags`, upsert the
    current-state table, and append add/remove rows to `issue_tag_history`.

    Same snapshot-before-overwrite-then-diff idiom as upsert_issues, applied
    to tag SETS instead of a single (state, state_type) pair. `changed_at` is
    this poll's timestamp, not the tag's true edit instant — no reliable
    tag-history API exists (same limitation issue_history already accepts
    for state transitions). Returns (issue_tags rows touched, history rows written).
    """
    if not items:
        return 0, 0
    issue_map = await _id_map(session, Issue, "zoho_id")
    tag_map = await _id_map(session, Tag, "zoho_id")

    incoming: dict[int, set[int]] = {}
    for it in items:
        issue_id = issue_map.get(it.id)
        if issue_id is None:
            continue
        incoming[issue_id] = {tag_map[tid] for tid in it.tag_ids if tid in tag_map}

    if not incoming:
        return 0, 0

    res = await session.execute(
        select(IssueTag.issue_id, IssueTag.tag_id).where(
            IssueTag.issue_id.in_(incoming.keys()), IssueTag.removed_at.is_(None)
        )
    )
    current: dict[int, set[int]] = {}
    for issue_id, tag_id in res.all():
        current.setdefault(issue_id, set()).add(tag_id)

    now = datetime.now(UTC)
    added_pairs: list[tuple[int, int]] = []
    removed_pairs: list[tuple[int, int]] = []
    for issue_id, want in incoming.items():
        have = current.get(issue_id, set())
        added_pairs.extend((issue_id, tag_id) for tag_id in want - have)
        removed_pairs.extend((issue_id, tag_id) for tag_id in have - want)

    if added_pairs:
        stmt = pg_insert(IssueTag).values(
            [
                {"issue_id": i, "tag_id": t, "added_at": now, "removed_at": None}
                for i, t in added_pairs
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IssueTag.issue_id, IssueTag.tag_id],
            set_={"added_at": now, "removed_at": None},
        )
        await session.execute(stmt)

    if removed_pairs:
        await session.execute(
            IssueTag.__table__.update()
            .where(tuple_(IssueTag.issue_id, IssueTag.tag_id).in_(removed_pairs))
            .values(removed_at=now)
        )

    history_rows = [
        {"issue_id": i, "tag_id": t, "action": "added", "changed_at": now}
        for i, t in added_pairs
    ] + [
        {"issue_id": i, "tag_id": t, "action": "removed", "changed_at": now}
        for i, t in removed_pairs
    ]
    if history_rows:
        conn = await session.connection()
        await ensure_month_partition(conn, "issue_tag_history", now)
        await session.execute(pg_insert(IssueTagHistory), history_rows)

    return len(added_pairs) + len(removed_pairs), len(history_rows)


async def upsert_item_comments(session: AsyncSession, comments: list[ZohoComment]) -> int:
    if not comments:
        return 0
    await _land_raw(session, "ZohoComment", comments, source=_ZOHO_SOURCE)
    issue_map = await _id_map(session, Issue, "zoho_id")
    actor_map = await _id_map(session, Actor, "zoho_id")

    rows = []
    skipped = 0
    for c in comments:
        issue_id = issue_map.get(c.item_id)
        if issue_id is None:
            skipped += 1
            continue
        rows.append(
            {
                "zoho_id": c.id,
                "issue_id": issue_id,
                "actor_id": actor_map.get(c.user_id),
                "body": c.body,
                "created_at": c.created_at,
            }
        )
    if skipped:
        logger.warning("Skipped %d Zoho comments referencing unknown items", skipped)
    if not rows:
        return 0
    stmt = pg_insert(Comment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Comment.zoho_id],
        set_={
            "issue_id": stmt.excluded.issue_id,
            "actor_id": stmt.excluded.actor_id,
            "body": stmt.excluded.body,
            "created_at": stmt.excluded.created_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


# =============================================================================
# GitHub-specific normalizers. Same idioms as the Zoho section above (land raw
# -> resolve FK maps via _id_map(..., "github_id") -> upsert -> diff-derived
# history rows), reusing the *same* tags/issue_tags/issue_tag_history tables
# Zoho's label pipeline writes to — the Engineering Points scoring job
# (app/jobs/score_points.py) matches on Tag.name regardless of which source
# put it there, so nothing downstream of these functions needs to change.
# =============================================================================

_GITHUB_SOURCE = "github"


async def upsert_github_team(session: AsyncSession, repo_node: dict) -> int:
    """A GitHub repo maps 1:1 onto a `teams` row, same as one Linear
    workspace team or one Zoho team. Single record, not a list, so it lands
    its own raw_events row directly rather than going through _land_raw."""
    await session.execute(
        pg_insert(RawEvent),
        [{"event_type": "GitHubRepo", "action": "sync", "payload": repo_node, "source": _GITHUB_SOURCE}],
    )
    stmt = pg_insert(Team).values(
        [{"github_id": repo_node["id"], "key": repo_node.get("name"), "name": repo_node.get("name")}]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.github_id],
        set_={"key": stmt.excluded.key, "name": stmt.excluded.name, "row_updated_at": func.now()},
    )
    await session.execute(stmt)
    return 1


async def upsert_github_actors(session: AsyncSession, users: list[GitHubActor]) -> int:
    if not users:
        return 0
    await _land_raw(session, "GitHubActor", users, source=_GITHUB_SOURCE)
    rows = [
        {
            "github_id": u.id,
            "name": u.name or u.login,
            "avatar_url": u.avatar_url,
        }
        for u in users
    ]
    stmt = pg_insert(Actor).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Actor.github_id],
        set_={
            "name": stmt.excluded.name,
            "avatar_url": stmt.excluded.avatar_url,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_github_labels(session: AsyncSession, labels: list[GitHubLabel]) -> int:
    """GitHub labels land in the same `tags` table Zoho tags use — the
    Engineering Points system matches on Tag.name, source-agnostic."""
    if not labels:
        return 0
    await _land_raw(session, "GitHubLabel", labels, source=_GITHUB_SOURCE)
    rows = [{"github_id": t.id, "name": t.name, "color_code": t.color} for t in labels]
    stmt = pg_insert(Tag).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tag.github_id],
        set_={
            "name": stmt.excluded.name,
            "color_code": stmt.excluded.color_code,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_github_milestones(
    session: AsyncSession, milestones: list[GitHubMilestone], team_id: int | None
) -> int:
    """GitHub milestones land in the same `cycles` table Linear cycles /
    Zoho sprints use."""
    if not milestones:
        return 0
    await _land_raw(session, "GitHubMilestone", milestones, source=_GITHUB_SOURCE)
    rows = [
        {
            "github_id": m.id,
            "team_id": team_id,
            "number": m.number,
            "name": m.title,
            "ends_at": m.due_on,
            "completed_at": m.closed_at,
        }
        for m in milestones
    ]
    stmt = pg_insert(Cycle).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Cycle.github_id],
        set_={
            "team_id": stmt.excluded.team_id,
            "number": stmt.excluded.number,
            "name": stmt.excluded.name,
            "ends_at": stmt.excluded.ends_at,
            "completed_at": stmt.excluded.completed_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_github_issues(
    session: AsyncSession, issues: list[GitHubIssue], team_id: int | None
) -> tuple[int, int]:
    """Upsert GitHub issues into `issues` and record state transitions.

    Same snapshot-before-overwrite-then-diff shape as upsert_items (Zoho).
    `state`/`state_type` are resolved per-issue via app.github.mapping
    .resolve_state (CAM MVP project Status field first, GitHub's own
    state/stateReason as fallback) — see that module's docstring. Returns
    (upserted, transitions).
    """
    if not issues:
        return 0, 0
    await _land_raw(session, "GitHubIssue", issues, source=_GITHUB_SOURCE)

    actor_map = await _id_map(session, Actor, "github_id")
    cycle_map = await _id_map(session, Cycle, "github_id")

    # Snapshot stored state BEFORE upserting so we can diff transitions.
    res = await session.execute(
        select(Issue.github_id, Issue.state, Issue.state_type).where(Issue.github_id.is_not(None))
    )
    stored = {gid: (st, stt) for gid, st, stt in res.all()}

    transitions: list[dict] = []
    rows = []
    for it in issues:
        state_name, state_type = resolve_state(
            issue_state=it.state, state_reason=it.state_reason, project_status=it.project_status
        )
        changed_at = it.updated_at or it.created_at or datetime.now(UTC)
        prev = stored.get(it.id)
        if prev is None:
            transitions.append(
                {
                    "issue_github_id": it.id, "changed_at": changed_at,
                    "from_state": None, "from_state_type": None,
                    "to_state": state_name, "to_state_type": state_type,
                }
            )
        elif prev[0] != state_name or prev[1] != state_type:
            transitions.append(
                {
                    "issue_github_id": it.id, "changed_at": changed_at,
                    "from_state": prev[0], "from_state_type": prev[1],
                    "to_state": state_name, "to_state_type": state_type,
                }
            )

        completed_at = it.closed_at if state_type == "completed" else None
        canceled_at = it.closed_at if state_type == "canceled" else None
        # No real "started" signal exists on a GitHub issue/Project-v2 item
        # (unlike Zoho's item.started_at) — left null rather than guessed
        # from created_at, which would distort cycle-time analytics.
        started_at = None

        rows.append(
            {
                "github_id": it.id,
                "identifier": f"#{it.number}",
                "title": it.title,
                "team_id": team_id,
                "assignee_id": actor_map.get(it.assignee_id) if it.assignee_id else None,
                "creator_id": actor_map.get(it.creator_id) if it.creator_id else None,
                "cycle_id": cycle_map.get(it.milestone_id) if it.milestone_id else None,
                "state": state_name,
                "state_type": state_type,
                "source": _GITHUB_SOURCE,
                "created_at": it.created_at,
                "started_at": started_at,
                "completed_at": completed_at,
                "canceled_at": canceled_at,
                "updated_at": it.updated_at,
            }
        )

    stmt = pg_insert(Issue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Issue.github_id],
        set_={
            c: getattr(stmt.excluded, c)
            for c in (
                "identifier", "title", "team_id", "assignee_id", "creator_id",
                "cycle_id", "state", "state_type", "source",
                "created_at", "started_at", "completed_at", "canceled_at", "updated_at",
            )
        }
        | {"row_updated_at": func.now()},
    )
    await session.execute(stmt)

    n_transitions = await _write_github_transitions(session, transitions)
    return len(rows), n_transitions


async def _write_github_transitions(session: AsyncSession, transitions: list[dict]) -> int:
    if not transitions:
        return 0
    issue_map = await _id_map(session, Issue, "github_id")

    conn = await session.connection()
    months = {(t["changed_at"].year, t["changed_at"].month) for t in transitions}
    for year, month in sorted(months):
        await ensure_month_partition(conn, "issue_history", datetime(year, month, 1, tzinfo=UTC))

    rows = []
    for t in transitions:
        issue_id = issue_map.get(t["issue_github_id"])
        if issue_id is None:
            continue
        rows.append(
            {
                "issue_id": issue_id,
                "changed_at": t["changed_at"],
                "linear_id": None,  # GitHub-sourced; no Linear history node id
                "actor_id": None,  # actor unknown without the Timeline API (v1 limitation)
                "from_state": t["from_state"],
                "from_state_type": t["from_state_type"],
                "to_state": t["to_state"],
                "to_state_type": t["to_state_type"],
            }
        )
    if rows:
        await session.execute(pg_insert(IssueHistory), rows)
    return len(rows)


async def upsert_github_issue_labels(session: AsyncSession, issues: list[GitHubIssue]) -> tuple[int, int]:
    """Diff each issue's incoming label set against `issue_tags`, upsert the
    current-state table, and append add/remove rows to `issue_tag_history`.

    Identical shape to upsert_item_tags (Zoho) — same "poll-time diff, not
    true edit instant" limitation noted there applies here too, even though
    GitHub's Timeline API *could* give us the real LabeledEvent timestamp; a
    future iteration could read that directly for exact `reverted`/`triaged`
    timing instead of approximating it as "whenever this sync run noticed
    it". Returns (issue_tags rows touched, history rows written).
    """
    if not issues:
        return 0, 0
    issue_map = await _id_map(session, Issue, "github_id")
    tag_map = await _id_map(session, Tag, "github_id")

    incoming: dict[int, set[int]] = {}
    for it in issues:
        issue_id = issue_map.get(it.id)
        if issue_id is None:
            continue
        incoming[issue_id] = {tag_map[lid] for lid in it.label_ids if lid in tag_map}

    if not incoming:
        return 0, 0

    res = await session.execute(
        select(IssueTag.issue_id, IssueTag.tag_id).where(
            IssueTag.issue_id.in_(incoming.keys()), IssueTag.removed_at.is_(None)
        )
    )
    current: dict[int, set[int]] = {}
    for issue_id, tag_id in res.all():
        current.setdefault(issue_id, set()).add(tag_id)

    now = datetime.now(UTC)
    added_pairs: list[tuple[int, int]] = []
    removed_pairs: list[tuple[int, int]] = []
    for issue_id, want in incoming.items():
        have = current.get(issue_id, set())
        added_pairs.extend((issue_id, tag_id) for tag_id in want - have)
        removed_pairs.extend((issue_id, tag_id) for tag_id in have - want)

    if added_pairs:
        stmt = pg_insert(IssueTag).values(
            [
                {"issue_id": i, "tag_id": t, "added_at": now, "removed_at": None}
                for i, t in added_pairs
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[IssueTag.issue_id, IssueTag.tag_id],
            set_={"added_at": now, "removed_at": None},
        )
        await session.execute(stmt)

    if removed_pairs:
        await session.execute(
            IssueTag.__table__.update()
            .where(tuple_(IssueTag.issue_id, IssueTag.tag_id).in_(removed_pairs))
            .values(removed_at=now)
        )

    history_rows = [
        {"issue_id": i, "tag_id": t, "action": "added", "changed_at": now}
        for i, t in added_pairs
    ] + [
        {"issue_id": i, "tag_id": t, "action": "removed", "changed_at": now}
        for i, t in removed_pairs
    ]
    if history_rows:
        conn = await session.connection()
        await ensure_month_partition(conn, "issue_tag_history", now)
        await session.execute(pg_insert(IssueTagHistory), history_rows)

    return len(added_pairs) + len(removed_pairs), len(history_rows)


async def upsert_github_comments(session: AsyncSession, comments: list[GitHubComment]) -> int:
    if not comments:
        return 0
    await _land_raw(session, "GitHubComment", comments, source=_GITHUB_SOURCE)
    issue_map = await _id_map(session, Issue, "github_id")
    actor_map = await _id_map(session, Actor, "github_id")

    rows = []
    skipped = 0
    for c in comments:
        issue_id = issue_map.get(c.issue_id)
        if issue_id is None:
            skipped += 1
            continue
        rows.append(
            {
                "github_id": c.id,
                "issue_id": issue_id,
                "actor_id": actor_map.get(c.user_id) if c.user_id else None,
                "body": c.body,
                "created_at": c.created_at,
            }
        )
    if skipped:
        logger.warning("Skipped %d GitHub comments referencing unknown issues", skipped)
    if not rows:
        return 0
    stmt = pg_insert(Comment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Comment.github_id],
        set_={
            "issue_id": stmt.excluded.issue_id,
            "actor_id": stmt.excluded.actor_id,
            "body": stmt.excluded.body,
            "created_at": stmt.excluded.created_at,
            "row_updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    return len(rows)
