"""An issue takes its Status from whichever tracked board it is on.

The org runs two boards ("BSA MVP" for the BSA repo, "capmob.ai" for the
rest), so GITHUB_PROJECT_TITLE is a comma-separated list. A board that is not
listed must never supply the status.
"""

from app.config import Settings
from app.github.client import GitHubIssue

TRACKED = "BSA MVP,capmob.ai"


def _node(*boards: tuple[str, str]) -> dict:
    return {
        "id": "issue-1",
        "number": 1,
        "title": "Issue 1",
        "state": "OPEN",
        "stateReason": None,
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-02T00:00:00Z",
        "closedAt": None,
        "author": {"login": "octocat", "id": "user-1"},
        "assignees": {"nodes": []},
        "labels": {"nodes": []},
        "comments": {"nodes": []},
        "projectItems": {
            "nodes": [{"project": {"title": t}, "fieldValueByName": {"name": s}} for t, s in boards]
        },
    }


def _status(*boards: tuple[str, str], titles: str = TRACKED) -> str | None:
    return GitHubIssue.from_node(_node(*boards), project_title=titles).project_status


def test_status_is_read_from_either_tracked_board():
    assert _status(("BSA MVP", "In review")) == "In review"
    assert _status(("capmob.ai", "Done")) == "Done"


def test_an_untracked_board_never_supplies_the_status():
    assert _status(("Some other board", "Done"), ("capmob.ai", "Ready")) == "Ready"
    assert _status(("Some other board", "Done")) is None


def test_a_single_title_still_works():
    assert _status(("CAM MVP", "Done"), titles="CAM MVP") == "Done"


def test_settings_split_the_titles():
    titles = Settings(github_project_title=" BSA MVP , capmob.ai ").github_project_titles
    assert titles == frozenset({"BSA MVP", "capmob.ai"})
