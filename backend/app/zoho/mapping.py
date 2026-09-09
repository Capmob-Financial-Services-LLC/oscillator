"""Zoho status -> our normalized state_type mapping.

The actual heuristic now lives in app.services.status_mapping (shared with
the GitHub sync, which faces the same problem: a free-text status/Status-field
name with no fixed enum). Re-exported here so existing imports/call sites
(app/services/normalizer.py, this module's own former callers) keep working
unchanged.

Zoho Sprints statuses are project-configurable (unlike Linear's fixed
6-value state_type enum), so there is no universal id->state_type table.
Instead, `classify_status_name` seeds a best-effort guess from the status's
display name the first time a project's status is seen; that guess is
persisted in `status_defs` (keyed on (project_id, zoho_status_id)) so it is
looked up — not re-guessed — on every subsequent sync, and can be hand-
corrected directly in the table if a project's status naming is unusual.
"""

from __future__ import annotations

from app.services.status_mapping import classify_status_name

__all__ = ["classify_status_name"]
