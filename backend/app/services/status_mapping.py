""""Status name" -> our normalized state_type heuristic, for sources that
give us a free-text status/Status-field label instead of Linear's fixed
6-value state_type enum — namely a GitHub Projects-v2 board's "Status"
single-select field, which can have arbitrary column names (e.g.
"Todo"/"In Progress"/"Done" or "Backlog"/"Doing"/"Shipped").
"""

from __future__ import annotations

# triage | backlog | unstarted | started | completed | canceled
_COMPLETED_HINTS = ("done", "closed", "resolved", "shipped", "complete", "released")
_CANCELED_HINTS = ("cancel", "rejected", "invalid", "duplicate", "won't fix", "wont fix")
_STARTED_HINTS = ("progress", "wip", "active", "in review", "review", "testing", "qa")
_TRIAGE_HINTS = ("triage", "unconfirmed", "needs info", "incoming")
_BACKLOG_HINTS = ("backlog", "open", "new", "to do", "todo")


def classify_status_name(name: str | None) -> str:
    """Best-effort default for a never-before-seen status name."""
    n = (name or "").strip().lower()
    if not n:
        return "unstarted"
    for hints, state_type in (
        (_COMPLETED_HINTS, "completed"),
        (_CANCELED_HINTS, "canceled"),
        (_STARTED_HINTS, "started"),
        (_TRIAGE_HINTS, "triage"),
        (_BACKLOG_HINTS, "backlog"),
    ):
        if any(h in n for h in hints):
            return state_type
    return "unstarted"
