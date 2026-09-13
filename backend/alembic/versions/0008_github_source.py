"""github source: github_id everywhere, plus relaxing linear_id

Adds a `github_id` column (nullable, unique) to teams/actors/cycles/issues/
comments/tags alongside the existing `linear_id`, and relaxes `linear_id` to
nullable on all six — a row synced from GitHub carries `github_id` instead,
never both. Same pattern as if a second source had always been anticipated
here; this is the first one.

Extends the `issues.source` value set with 'github' (no schema change
needed — same free-text column that already holds 'linear'/'custom').

Revision ID: 0008_github_source
Revises: 0007_labels_and_points
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_github_source"
down_revision = "0007_labels_and_points"
branch_labels = None
depends_on = None

_TABLES_WITH_LINEAR_ID = ["teams", "actors", "cycles", "issues", "comments", "tags"]


def upgrade() -> None:
    for table in _TABLES_WITH_LINEAR_ID:
        op.alter_column(table, "linear_id", existing_type=sa.String(64), nullable=True)
        op.add_column(table, sa.Column("github_id", sa.String(64)))
        op.create_unique_constraint(f"uq_{table}_github_id", table, ["github_id"])


def downgrade() -> None:
    for table in _TABLES_WITH_LINEAR_ID:
        op.drop_constraint(f"uq_{table}_github_id", table, type_="unique")
        op.drop_column(table, "github_id")
        op.alter_column(table, "linear_id", existing_type=sa.String(64), nullable=False)
