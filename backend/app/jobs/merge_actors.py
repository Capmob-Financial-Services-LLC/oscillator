"""One-off maintenance entrypoint:  python -m app.jobs.merge_actors

Linear and GitHub actors are ingested as separate rows keyed on their own
source id (linear_id / github_id) — there is no email-based identity merge
anywhere in the sync pipeline (see app/services/normalizer.py). A real
person who is both a Linear team member (historical work) and a GitHub user
(new work on the CAM MVP board) therefore shows up as TWO actors — two
separate leaderboard entries, points split across both — until merged here.

Merging repoints every actor-referencing row (issues.assignee_id/creator_id,
issue_history.actor_id, comments.actor_id, tags.created_by_id,
points_events.actor_id, points_unscored_tickets.assignee_id) from the
duplicate onto the kept actor, folds over
any source id / email / avatar / name the kept actor is missing, and deletes
the now-empty duplicate row. Existing points_events rows are repointed
directly — no rescoring needed for the merge itself to show up as one
person's aggregate total.

Order matters for correctness: child rows are repointed BEFORE the
duplicate is deleted (so nothing is lost), and the duplicate's linear_id/
github_id are captured and folded onto the kept row AFTER it is deleted
(both columns are UNIQUE, so both rows can never hold the same value at
once mid-transaction).

Safety: dry-run by default — prints exactly what would move without
committing (the whole thing runs in a transaction that gets rolled back).
Pass --apply to actually commit. Meant to be run via the "Merge Duplicate
Actors" GitHub Actions workflow (workflow_dispatch only, never scheduled),
since this repo's dev/CI environment is the only place with DATABASE_URL.

Usage:
    python -m app.jobs.merge_actors --pairs "Sachin:sachin-capmob;Adarsh:adarshcapmob"
    python -m app.jobs.merge_actors --pairs "Sachin:sachin-capmob" --apply

Each pair is "keep_name:merge_name" (case-insensitive exact match against
actors.name). The FIRST name is kept; the SECOND is folded into it and
removed. If either name matches more than one actor, that pair is skipped
and every match is listed (with id/linear_id/github_id) so you can re-run
with numeric ids instead: "id:123:id:456".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import delete, func, select, text, update

from app.db import get_sessionmaker
from app.models import Actor

logger = logging.getLogger("app.merge_actors")

# (table, column) for every FK onto actors.id — see module docstring.
_ACTOR_REFERENCING_COLUMNS = [
    ("issues", "assignee_id"),
    ("issues", "creator_id"),
    ("issue_history", "actor_id"),
    ("comments", "actor_id"),
    ("tags", "created_by_id"),
    ("points_events", "actor_id"),
    ("points_unscored_tickets", "assignee_id"),
]


class ResolveError(Exception):
    pass


async def _resolve_actor(session, selector: str) -> Actor:
    """selector is either "id:<n>" or a bare name (case-insensitive exact match)."""
    if selector.startswith("id:"):
        actor_id = int(selector[3:])
        row = (await session.execute(select(Actor).where(Actor.id == actor_id))).scalar_one_or_none()
        if row is None:
            raise ResolveError(f"No actor with id={actor_id}")
        return row

    rows = (
        await session.execute(select(Actor).where(func.lower(Actor.name) == selector.lower()))
    ).scalars().all()
    if not rows:
        raise ResolveError(f"No actor found with name '{selector}'")
    if len(rows) > 1:
        listing = "; ".join(
            f"id={r.id} linear_id={r.linear_id} github_id={r.github_id} email={r.email}" for r in rows
        )
        raise ResolveError(f"Ambiguous name '{selector}', {len(rows)} matches: {listing}")
    return rows[0]


async def merge_actor(session, keep: Actor, dup: Actor) -> dict:
    if keep.id == dup.id:
        raise ValueError("keep and merge actor are the same row")

    repointed: dict[str, int] = {}
    for table, col in _ACTOR_REFERENCING_COLUMNS:
        res = await session.execute(
            text(f"UPDATE {table} SET {col} = :keep_id WHERE {col} = :dup_id"),  # noqa: S608 (fixed allowlist above, no user input in SQL)
            {"keep_id": keep.id, "dup_id": dup.id},
        )
        if res.rowcount:
            repointed[f"{table}.{col}"] = res.rowcount

    # Capture what the duplicate has that the kept row is missing, BEFORE
    # deleting it — linear_id/github_id are UNIQUE, so they can only move
    # onto `keep` once `dup` no longer holds them.
    folded = {}
    for field in ("linear_id", "github_id", "email", "avatar_url", "name"):
        if getattr(dup, field) and not getattr(keep, field):
            folded[field] = getattr(dup, field)

    await session.execute(delete(Actor).where(Actor.id == dup.id))

    if folded:
        await session.execute(update(Actor).where(Actor.id == keep.id).values(**folded))

    return {
        "kept": {"id": keep.id, "name": keep.name},
        "removed": {"id": dup.id, "name": dup.name},
        "repointed": repointed,
        "folded_fields": folded,
    }


async def run_merge(pair_specs: list[tuple[str, str]], *, apply: bool) -> list[dict]:
    Session = get_sessionmaker()
    results: list[dict] = []
    async with Session() as session:
        async with session.begin():
            for keep_sel, dup_sel in pair_specs:
                try:
                    keep = await _resolve_actor(session, keep_sel)
                    dup = await _resolve_actor(session, dup_sel)
                except ResolveError as exc:
                    logger.error("Skipping pair (%s, %s): %s", keep_sel, dup_sel, exc)
                    continue
                result = await merge_actor(session, keep, dup)
                results.append(result)
            if not apply:
                logger.info("DRY RUN — rolling back, nothing was committed")
                await session.rollback()
            # else: the `async with session.begin()` block commits on exit.
    return results


def _parse_pairs(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise SystemExit(f"Bad pair '{chunk}' — expected 'keep:merge' (or 'id:1:id:2')")
        # A plain name never contains ':'; an id selector is "id:<n>" — so
        # split on the FIRST ':' only when the left side isn't "id".
        left, _, right = chunk.partition(":")
        if left == "id":
            # "id:1:id:2" -> keep="id:1", merge="id:2"
            rest = chunk[len("id:") :]
            keep_id, _, merge_sel = rest.partition(":")
            pairs.append((f"id:{keep_id}", merge_sel))
        else:
            pairs.append((left, right))
    return pairs


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pairs", required=True,
        help='Semicolon-separated "keep_name:merge_name" pairs, e.g. "Sachin:sachin-capmob;Adarsh:adarshcapmob"',
    )
    parser.add_argument("--apply", action="store_true", help="Actually commit (default: dry run)")
    args = parser.parse_args()

    pair_specs = _parse_pairs(args.pairs)
    if not pair_specs:
        print("No pairs given.")
        return 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== MERGE ACTORS ({mode}) ===")
    try:
        results = asyncio.run(run_merge(pair_specs, apply=args.apply))
    except Exception:
        logger.exception("Merge FAILED")
        return 1

    if not results:
        print("Nothing merged — every pair failed to resolve (see errors above).")
        return 1

    for r in results:
        print(f"\nKEEP  id={r['kept']['id']} name={r['kept']['name']!r}")
        print(f"MERGE id={r['removed']['id']} name={r['removed']['name']!r}  <- removed")
        print(f"  repointed: {r['repointed'] or '(nothing referenced the duplicate)'}")
        print(f"  folded onto kept row: {r['folded_fields'] or '(nothing to fold)'}")

    if not args.apply:
        print("\nDry run only — nothing was committed. Re-run with --apply to make it permanent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
