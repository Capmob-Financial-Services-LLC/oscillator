"""github source: github_id everywhere, plus relaxing tags.zoho_id

Adds a `github_id` column (nullable, unique) to teams/actors/cycles/issues/
comments/tags alongside the existing linear_id/zoho_id columns — a row
synced from GitHub carries `github_id` instead, never more than one source id
at once. Same dual/triple-nullable pattern 0008 established for Zoho.

`tags.zoho_id` was NOT NULL (it was Zoho-only until now); relaxed to nullable
so a GitHub-sourced label can be stored there too, mirroring the
`linear_id` relaxation 0008 already did on the other tables. Extends the
`issues.source` value set with 'github' (no schema change needed — same
free-text column 0006 added for 'custom', 0008 for 'zoho_sprints').

Revision ID: 0010_github_source
Revises: 0009_points
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_github_source"
down_revision = "0009_points"
branch_labels = None
depends_on = None

_TABLES_WITH_SOURCE_ID = ["teams", "actors", "cycles", "issues", "comments", "tags"]


def upgrade() -> None:
    op.alter_column("tags", "zoho_id", existing_type=sa.String(64), nullable=True)

    for table in _TABLES_WITH_SOURCE_ID:
        op.add_column(table, sa.Column("github_id", sa.String(64)))
        op.create_unique_constraint(f"uq_{table}_github_id", table, ["github_id"])


def downgrade() -> None:
    for table in _TABLES_WITH_SOURCE_ID:
        op.drop_constraint(f"uq_{table}_github_id", table, type_="unique")
        op.drop_column(table, "github_id")

    op.alter_column("tags", "zoho_id", existing_type=sa.String(64), nullable=False)
