"""
Hyperlocal Gig-Matching Engine API
====================================
FastAPI application entry point.

Startup sequence
----------------
1. Create all database tables (idempotent, uses CREATE TABLE IF NOT EXISTS).
2. Mount /workers and /tasks routers under /api.
3. Expose /api/health for readiness probes.

Concurrency
-----------
All I/O (DB reads/writes) is async — the event loop is never blocked.
The matching algorithm itself is pure CPU work and runs synchronously inside
the event loop, but its O(n log n) heap sort is fast enough for realistic
fleet sizes (< 1 ms for 10 000 workers on a single core).  For very large
fleets consider offloading to asyncio.to_thread().
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import tasks, workers


# ---------------------------------------------------------------------------
# Lifespan — DB table creation on startup
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables if they don't exist yet (safe for both SQLite and PostgreSQL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Graceful shutdown — dispose connection pool
    await engine.dispose()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Hyperlocal Gig-Matching Engine API",
    version="1.0.0",
    description=(
        "High-performance backend microservice that matches field gig-workers to "
        "enterprise tasks using real-world geolocation (Haversine formula) and a "
        "priority-queue compound scoring algorithm (Python heapq).\n\n"
        "Built with FastAPI + asyncio for high-concurrency workloads."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Allow all origins in development; tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(workers.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health", tags=["Health"], summary="Readiness probe")
async def health() -> dict:
    return {"status": "ok", "service": "gig-matching-engine"}


# ---------------------------------------------------------------------------
# Dev entrypoint (python -m app.main)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
