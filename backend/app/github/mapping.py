"""GitHub issue -> our normalized (state, state_type) mapping.

Preference order, most to least authoritative:
1. The CAM MVP project's "Status" field value, if the issue has one — run
   through the same free-text heuristic Zoho's status names use
   (app.services.status_mapping.classify_status_name), since a project board
   can have arbitrary column names (e.g. "Todo"/"In Progress"/"Done" or
   "Backlog"/"Doing"/"Shipped").
2. Otherwise, GitHub's own `state`/`stateReason` on the issue itself: CLOSED
   + stateReason=NOT_PLANNED -> canceled; CLOSED (any other reason, including
   the default COMPLETED) -> completed; OPEN -> unstarted. This is a real,
   explicit signal GitHub gives us that Zoho's API never did (Zoho items have
   no closed/not-planned distinction on the payload itself).
"""

from __future__ import annotations

from app.services.status_mapping import classify_status_name


def resolve_state(
    *, issue_state: str, state_reason: str | None, project_status: str | None
) -> tuple[str, str]:
    """Returns (state_name_for_display, state_type)."""
    if project_status:
        return project_status, classify_status_name(project_status)
    if issue_state == "CLOSED":
        if state_reason == "NOT_PLANNED":
            return "Closed (not planned)", "canceled"
        return "Closed", "completed"
    return "Open", "unstarted"
