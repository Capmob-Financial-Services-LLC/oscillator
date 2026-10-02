"""Application configuration, loaded from environment / .env via pydantic-settings.

Env var names are matched case-insensitively, so the uppercase names from the
project spec (LINEAR_API_KEY, DATABASE_URL, ...) map onto the lowercase fields below.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Secrets / external services ---
    linear_api_key: str = Field(default="")
    database_url: str = Field(default="")
    dashboard_auth_token: str = Field(default="")

    # GitHub sync (Issues + Projects v2). `github_sync_token` needs `repo` +
    # `read:project` scope on the org that owns github_sync_org/repos — it is
    # deliberately NOT named GITHUB_TOKEN, which Actions auto-populates with
    # a same-repo-only token that would silently shadow a real PAT/App token.
    github_sync_token: str = Field(default="")
    github_sync_org: str = Field(default="")
    # Comma-separated repo names within github_sync_org, e.g. "BSA,Capmob-AI"
    # — each becomes its own `teams` row (see app/jobs/sync_github.py),
    # exactly like Linear's multiple workspace teams.
    github_sync_repos: str = Field(default="")
    # The GitHub Projects v2 boards whose "Status" field values are read for
    # state_type mapping (see app/github/mapping.py), by title, comma-separated.
    # More than one because the org runs two boards: "BSA MVP" (#7, the BSA
    # repo) and "capmob.ai" (#9, every other repo). An issue takes its status
    # from whichever listed board it is on. The old default, "CAM MVP", named
    # a board that no longer exists, so no status was ever read.
    github_project_title: str = Field(default="BSA MVP,capmob.ai")

    @property
    def github_sync_repo_list(self) -> list[str]:
        return [r.strip() for r in self.github_sync_repos.split(",") if r.strip()]

    @property
    def github_project_titles(self) -> frozenset[str]:
        return frozenset(t.strip() for t in self.github_project_title.split(",") if t.strip())

    # --- App behavior ---
    environment: str = Field(default="development")
    # TLS for the DB connection. Required by Neon (keep true in prod); set
    # DB_SSL=false for a local Postgres that has no TLS configured.
    db_ssl: bool = Field(default=True)
    # Comma-separated list accepted via env, e.g. CORS_ORIGINS="http://localhost:3000,https://app.example.com"
    cors_origins: str = Field(default="http://localhost:3000")
    linear_api_url: str = Field(default="https://api.linear.app/graphql")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def async_database_url(self) -> str:
        """Normalize a Neon/Postgres URL to the SQLAlchemy asyncpg driver.

        Neon hands out `postgresql://...`; SQLAlchemy async needs
        `postgresql+asyncpg://...`. We also strip libpq-only query params
        (e.g. `sslmode`, `channel_binding`) that asyncpg does not understand —
        TLS is configured on the engine instead (see app/db.py).
        """
        url = self.database_url
        if not url:
            return ""
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Drop query string; asyncpg rejects libpq params like sslmode.
        return url.split("?", 1)[0]

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def github_sync_configured(self) -> bool:
        return bool(self.github_sync_token and self.github_sync_org and self.github_sync_repo_list)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (import-safe; reads .env once)."""
    return Settings()
