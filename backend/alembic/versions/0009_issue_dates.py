"""issue planned dates: start_date and target_date

Revision ID: 0009_issue_dates
Revises: 0008_github_source

GitHub's org-level "Start date" / "Target date" issue fields, synced so the
delivery score can compare when work was done against when it was due.
Nullable: most issues, and every Linear issue, have neither.

Also clears the GitHub sync watermark. The sync is incremental (issues
updated since the last run), so without this the dates of every issue that
has not changed since would never arrive. The next hourly run does one full
backfill, then carries on incrementally. Linear's watermark is untouched.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_issue_dates"
down_revision = "0008_github_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("start_date", sa.Date()))
    op.add_column("issues", sa.Column("target_date", sa.Date()))
    op.create_index("ix_issues_target_date", "issues", ["target_date"])
    op.execute("DELETE FROM sync_state WHERE key = 'github'")


def downgrade() -> None:
    op.drop_index("ix_issues_target_date", table_name="issues")
    op.drop_column("issues", "target_date")
    op.drop_column("issues", "start_date")
