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

    # Zoho Sprints OAuth (Self Client — https://api-console.zoho.com/).
    # Region-specific hosts: accounts.zoho.com/.eu/.in/.com.au/.jp — match
    # both zoho_accounts_url and zoho_api_url to the same data center.
    zoho_client_id: str = Field(default="")
    zoho_client_secret: str = Field(default="")
    zoho_refresh_token: str = Field(default="")
    zoho_accounts_url: str = Field(default="https://accounts.zoho.com")
    zoho_api_url: str = Field(default="https://sprintsapi.zoho.com")
    zoho_team_id: str = Field(default="")
    # Safety margin under Zoho's documented ~30 calls/min.
    zoho_rate_limit_per_min: int = Field(default=28)

    # GitHub sync (Issues + Projects v2). `github_sync_token` needs `repo` +
    # `read:project` scope on the org that owns github_sync_org/repo — it is
    # deliberately NOT named GITHUB_TOKEN, which Actions auto-populates with
    # a same-repo-only token that would silently shadow a real PAT/App token.
    github_sync_token: str = Field(default="")
    github_sync_org: str = Field(default="")
    github_sync_repo: str = Field(default="")
    # The GitHub Projects v2 board whose "Status" field values are read for
    # state_type mapping (see app/github/mapping.py) — a repo can be linked
    # to more than one project, so this picks the right one by title.
    github_project_title: str = Field(default="CAM MVP")

    # Groq (OpenAI-compatible) powers the narrative digest. When unset the
    # digest degrades gracefully to a deterministic templated summary.
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    groq_api_url: str = Field(default="https://api.groq.com/openai/v1/chat/completions")

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
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def zoho_configured(self) -> bool:
        return bool(self.zoho_client_id and self.zoho_refresh_token and self.zoho_team_id)

    @property
    def github_sync_configured(self) -> bool:
        return bool(self.github_sync_token and self.github_sync_org and self.github_sync_repo)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (import-safe; reads .env once)."""
    return Settings()
