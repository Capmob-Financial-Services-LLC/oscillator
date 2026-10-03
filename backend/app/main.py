"""FastAPI application entrypoint (read-only insights API).

Run locally:  uvicorn app.main:app --reload
Ingestion is handled out-of-band by the cron job (`python -m app.jobs.sync`);
this service only reads from Postgres and serves the insights endpoints.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import get_engine
from app.db_partitions import ensure_partitions_around

logger = logging.getLogger("app")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """On startup, ensure the current/adjacent monthly partitions exist.

    Best-effort: a DB outage must not stop the service from serving /health.
    The cron sync job also ensures partitions at the start of every run.
    """
    if settings.database_configured:
        try:
            async with get_engine().begin() as conn:
                created = await ensure_partitions_around(conn, datetime.now(UTC))
            logger.info("Ensured %d monthly partitions on startup", len(created))
        except Exception:  # noqa: BLE001 — never block startup on DB issues
            logger.exception("Could not ensure partitions on startup")
    yield


app = FastAPI(
    title="Linear Team Activity Dashboard API",
    version=__version__,
    description="Ingests Linear workspace data and serves activity insights.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe — always cheap, never touches the database."""
    return {"status": "ok", "version": __version__}


@app.get("/ready", tags=["meta"])
async def ready() -> dict[str, object]:
    """Readiness probe — reports whether required config is present."""
    return {
        "status": "ready",
        "database_configured": settings.database_configured,
        "linear_configured": bool(settings.linear_api_key),
        "environment": settings.environment,
    }


from app.api import custom_issues  # noqa: E402
from app.api import delivery  # noqa: E402
from app.api import insights  # noqa: E402
from app.api import points  # noqa: E402

app.include_router(insights.router)
app.include_router(custom_issues.router)
app.include_router(points.router)
app.include_router(delivery.router)
