"""Async GitHub GraphQL (v4) client.

Structurally mirrors app/linear/client.py: same DTO-with-raw-node shape, same
cursor pagination (pageInfo.hasNextPage/endCursor), same required-`since`
epoch-sentinel pattern for full-backfill vs. incremental runs, same
retry/backoff on 429/5xx respecting Retry-After. GitHub-specific wrinkles:

* Auth is a standard `Authorization: Bearer <token>` header (Linear uses the
  raw key with no prefix).
* GitHub's secondary rate limiter can return 403 (not just 429) with a
  `Retry-After` header — treated the same as 429 here.
* A single "issue" node in this schema already carries everything Linear
  spreads across separate `issues`/`comments` queries: labels, assignees,
  AND a page of comments, all nested in one GraphQL selection. So
  fetch_issues() also returns each issue's comments (flattened out by the
  caller) instead of a separate fetch_comments() call.
* Each issue's Projects-v2 "Status" field value (the CAM MVP board's status
  column) is pulled via `projectItems.fieldValueByName(name:"Status")` —
  matched against `project_title` so a repo linked to multiple projects only
  picks up the one we care about.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from app.config import get_settings

logger = logging.getLogger("app.github")

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
PAGE_SIZE = 100
ISSUE_PAGE_SIZE = 25  # deeply-nested query (labels/assignees/comments/projectItems per issue)
MAX_RETRIES = 6
# Full backfill sentinel: updatedAt >= epoch matches every record.
FULL_BACKFILL_SINCE = datetime(1970, 1, 1, tzinfo=UTC)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _actor_id(node: dict | None) -> str | None:
    """`author`/comment-author fields are the `Actor` interface — `id` is only
    resolvable via the `... on User { id }` inline fragment (see _ISSUES)."""
    if not node:
        return None
    return node.get("id")


# --------------------------------------------------------------------------- #
# DTOs — each carries the original GraphQL node in `raw` for raw_events landing.
# --------------------------------------------------------------------------- #
class GitHubActor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    login: str | None = None
    name: str | None = None
    avatar_url: str | None = None
    raw: dict[str, Any]

    @classmethod
    def from_node(cls, n: dict) -> GitHubActor:
        return cls(id=n["id"], login=n.get("login"), name=n.get("name"),
                    avatar_url=n.get("avatarUrl"), raw=n)


class GitHubLabel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    color: str | None = None
    raw: dict[str, Any]

    @classmethod
    def from_node(cls, n: dict) -> GitHubLabel:
        return cls(id=n["id"], name=n["name"], color=n.get("color"), raw=n)


class GitHubMilestone(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    number: int | None = None
    title: str | None = None
    created_at: datetime | None = None
    due_on: datetime | None = None
    closed_at: datetime | None = None
    raw: dict[str, Any]

    @classmethod
    def from_node(cls, n: dict) -> GitHubMilestone:
        return cls(id=n["id"], number=n.get("number"), title=n.get("title"),
                    created_at=_parse_dt(n.get("createdAt")), due_on=_parse_dt(n.get("dueOn")),
                    closed_at=_parse_dt(n.get("closedAt")), raw=n)


class GitHubComment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    issue_id: str
    user_id: str | None = None
    body: str | None = None
    created_at: datetime | None = None
    raw: dict[str, Any]


class GitHubIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    number: int
    title: str | None = None
    state: str = "OPEN"  # OPEN | CLOSED
    state_reason: str | None = None  # COMPLETED | NOT_PLANNED | REOPENED | None
    project_status: str | None = None  # CAM MVP board's Status field option name, if set
    assignee_id: str | None = None  # first assignee, mirroring Linear's single-assignee shape
    creator_id: str | None = None
    milestone_id: str | None = None
    label_ids: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    comments: list[GitHubComment] = []
    comments_truncated: bool = False  # >50 comments on this issue; see fetch_issues docstring
    raw: dict[str, Any]

    @classmethod
    def from_node(cls, n: dict, *, project_title: str) -> GitHubIssue:
        assignees = (n.get("assignees") or {}).get("nodes") or []
        labels = (n.get("labels") or {}).get("nodes") or []
        comment_conn = n.get("comments") or {}
        comment_nodes = comment_conn.get("nodes") or []

        status = None
        for item in (n.get("projectItems") or {}).get("nodes") or []:
            project = item.get("project") or {}
            if project.get("title") != project_title:
                continue
            fv = item.get("fieldValueByName")
            if fv and fv.get("name"):
                status = fv["name"]
                break

        issue = cls(
            id=n["id"], number=n["number"], title=n.get("title"),
            state=n.get("state") or "OPEN", state_reason=n.get("stateReason"),
            project_status=status,
            assignee_id=assignees[0]["id"] if assignees else None,
            creator_id=_actor_id(n.get("author")),
            milestone_id=(n.get("milestone") or {}).get("id"),
            label_ids=[label_node["id"] for label_node in labels],
            created_at=_parse_dt(n.get("createdAt")),
            updated_at=_parse_dt(n.get("updatedAt")),
            closed_at=_parse_dt(n.get("closedAt")),
            comments_truncated=bool((comment_conn.get("pageInfo") or {}).get("hasNextPage")),
            raw=n,
        )
        issue.comments = [
            GitHubComment(
                id=c["id"], issue_id=issue.id, user_id=_actor_id(c.get("author")),
                body=c.get("body"), created_at=_parse_dt(c.get("createdAt")), raw=c,
            )
            for c in comment_nodes
        ]
        return issue


# --------------------------------------------------------------------------- #
# GraphQL documents. `since` always present (epoch for full backfill).
# --------------------------------------------------------------------------- #
_REPO = """
query($owner:String!,$name:String!){
  repository(owner:$owner, name:$name){ id name }
}"""

_LABELS = """
query($owner:String!,$name:String!,$first:Int!,$after:String){
  repository(owner:$owner, name:$name){
    labels(first:$first, after:$after){
      nodes{ id name color }
      pageInfo{ hasNextPage endCursor }
    }
  }
}"""

_ASSIGNABLE_USERS = """
query($owner:String!,$name:String!,$first:Int!,$after:String){
  repository(owner:$owner, name:$name){
    assignableUsers(first:$first, after:$after){
      nodes{ id login name avatarUrl }
      pageInfo{ hasNextPage endCursor }
    }
  }
}"""

_MILESTONES = """
query($owner:String!,$name:String!,$first:Int!,$after:String){
  repository(owner:$owner, name:$name){
    milestones(first:$first, after:$after){
      nodes{ id number title createdAt dueOn closedAt }
      pageInfo{ hasNextPage endCursor }
    }
  }
}"""

_ISSUES = """
query($owner:String!,$name:String!,$first:Int!,$after:String,$since:DateTime!){
  repository(owner:$owner, name:$name){
    issues(
      first:$first, after:$after,
      filterBy:{ since:$since },
      orderBy:{ field: UPDATED_AT, direction: ASC }
    ){
      nodes{
        id number title state stateReason
        createdAt updatedAt closedAt
        author{ login ... on User{ id } }
        assignees(first:5){ nodes{ id login name avatarUrl } }
        labels(first:20){ nodes{ id name color } }
        milestone{ id }
        comments(first:50){
          nodes{ id body createdAt author{ login ... on User{ id } } }
          pageInfo{ hasNextPage }
        }
        projectItems(first:5){
          nodes{
            project{ title }
            fieldValueByName(name:"Status"){
              ... on ProjectV2ItemFieldSingleSelectValue{ name }
            }
          }
        }
      }
      pageInfo{ hasNextPage endCursor }
    }
  }
}"""


class GitHubClient:
    """Thin async GraphQL client scoped to a single repo. Async context manager.

    A repo must always be passed explicitly by multi-repo callers (see
    app/jobs/sync_github.py, which loops over settings.github_sync_repo_list)
    — the settings fallback below is a single-repo convenience for ad-hoc/
    manual use only, and just picks the first configured repo.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        owner: str | None = None,
        repo: str | None = None,
        project_title: str | None = None,
        timeout: float = 30.0,
    ):
        settings = get_settings()
        self._token = token or settings.github_sync_token
        self.owner = owner or settings.github_sync_org
        repo_list = settings.github_sync_repo_list
        self.repo = repo or (repo_list[0] if repo_list else None)
        self.project_title = project_title or settings.github_project_title
        if not (self._token and self.owner and self.repo):
            raise RuntimeError(
                "GITHUB_SYNC_TOKEN / GITHUB_SYNC_ORG / GITHUB_SYNC_REPOS are not configured."
            )
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST a GraphQL document with retry/backoff on rate limits + 5xx.

        GitHub's *secondary* rate limiter can return 403 (not just 429) with
        a Retry-After header, and a normal rate-limit hit can come back as a
        200 with a `RATE_LIMITED` entry in `errors` instead of a non-2xx
        status — all three are treated as retryable here.
        """
        attempt = 0
        while True:
            attempt += 1
            try:
                # Post the full URL explicitly rather than relying on a
                # client-level base_url + empty-path join — httpx silently
                # appends a trailing slash to a bare base_url
                # (https://api.github.com/graphql -> .../graphql/), and
                # GitHub's endpoint 404s on that trailing-slash form.
                resp = await self._client.post(
                    GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables}
                )
            except httpx.TransportError as exc:
                if attempt >= MAX_RETRIES:
                    raise
                delay = min(2**attempt, 30)
                logger.warning("Transport error (%s); retry %d in %ss", exc, attempt, delay)
                await asyncio.sleep(delay)
                continue

            if resp.status_code in (403, 429) or resp.status_code >= 500:
                if attempt >= MAX_RETRIES:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 30)
                logger.warning(
                    "HTTP %s from GitHub; retry %d in %ss", resp.status_code, attempt, delay
                )
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()
            body = resp.json()
            errors = body.get("errors")
            if errors:
                if attempt < MAX_RETRIES and any(
                    e.get("type") == "RATE_LIMITED" for e in errors
                ):
                    delay = min(2**attempt, 30)
                    logger.warning("GitHub GraphQL rate limited; retry %d in %ss", attempt, delay)
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(f"GitHub GraphQL errors: {errors}")
            return body["data"]

    async def _paginate(
        self, query: str, path: tuple[str, ...], variables: dict[str, Any], *, page_size: int
    ) -> list[dict]:
        """Walk a connection nested under repository.<path[0]>, cursor by cursor."""
        nodes: list[dict] = []
        after: str | None = None
        while True:
            data = await self._execute(
                query, {**variables, "first": page_size, "after": after}
            )
            conn = data["repository"]
            for key in path:
                conn = conn[key]
            nodes.extend(conn["nodes"])
            page = conn["pageInfo"]
            if not page.get("hasNextPage"):
                break
            after = page["endCursor"]
        return nodes

    # --- typed entity methods ---
    async def fetch_repo(self) -> dict:
        data = await self._execute(_REPO, {"owner": self.owner, "name": self.repo})
        return data["repository"]

    async def fetch_labels(self) -> list[GitHubLabel]:
        nodes = await self._paginate(
            _LABELS, ("labels",), {"owner": self.owner, "name": self.repo}, page_size=PAGE_SIZE
        )
        return [GitHubLabel.from_node(n) for n in nodes]

    async def fetch_assignable_users(self) -> list[GitHubActor]:
        nodes = await self._paginate(
            _ASSIGNABLE_USERS, ("assignableUsers",),
            {"owner": self.owner, "name": self.repo}, page_size=PAGE_SIZE,
        )
        return [GitHubActor.from_node(n) for n in nodes]

    async def fetch_milestones(self) -> list[GitHubMilestone]:
        nodes = await self._paginate(
            _MILESTONES, ("milestones",),
            {"owner": self.owner, "name": self.repo}, page_size=PAGE_SIZE,
        )
        return [GitHubMilestone.from_node(n) for n in nodes]

    async def fetch_issues(self, since: datetime | None = None) -> list[GitHubIssue]:
        """Returns issues updated at/after `since`, each carrying its own
        (up to 50) comments — see module docstring. An issue with more than
        50 comments has `comments_truncated=True`; a follow-up backfill for
        those specific issues is a known v1 limitation, logged, not silent.
        """
        s = _iso(since or FULL_BACKFILL_SINCE)
        nodes = await self._paginate(
            _ISSUES, ("issues",),
            {"owner": self.owner, "name": self.repo, "since": s}, page_size=ISSUE_PAGE_SIZE,
        )
        issues = [GitHubIssue.from_node(n, project_title=self.project_title) for n in nodes]
        truncated = [i.number for i in issues if i.comments_truncated]
        if truncated:
            logger.warning(
                "Issues with >50 comments (comment list truncated this run): %s", truncated
            )
        return issues
