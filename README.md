# Hyperlocal Gig-Matching Engine API

A high-performance FastAPI microservice that matches field gig-workers to enterprise tasks using real-world geolocation and a priority-queue compound scoring algorithm — modelled on the core operational challenges faced by gig-workforce platforms like Awign.

## Architecture

```
gig-engine/
├── app/
│   ├── main.py          # FastAPI application & lifespan (async DB init)
│   ├── config.py        # Pydantic-settings config (env var driven)
│   ├── database.py      # Async SQLAlchemy engine + session factory
│   ├── models.py        # ORM models: Worker, GigTask
│   ├── schemas.py       # Pydantic request / response schemas
│   ├── crud.py          # Async CRUD helpers
│   ├── algorithms.py    # Haversine formula + heapq matching engine
│   └── routers/
│       ├── workers.py   # CRUD endpoints for workers
│       └── tasks.py     # Task lifecycle + matching trigger
└── tests/
    ├── conftest.py          # Shared fixtures (in-memory SQLite)
    ├── test_algorithms.py   # Pure unit tests for haversine + heapq
    ├── test_workers.py      # Worker endpoint integration tests
    ├── test_tasks.py        # Task + matching pipeline integration tests
    └── test_health.py       # Health probe test
```

## Tech Stack

| Layer | Tool |
|---|---|
| Framework | FastAPI (asyncio) |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2 (async) |
| DB (prod) | PostgreSQL via asyncpg |
| DB (dev/test) | SQLite via aiosqlite |
| Server | Uvicorn |
| Tests | Pytest + pytest-asyncio + httpx |

## Algorithmic Pipeline

### 1 — Haversine Formula

Computes the **real-world great-circle distance** (km) between a task and each available worker:

```
a = sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2)
c = 2 · atan2(√a, √(1−a))
d = R · c          (R = 6,371 km)
```

### 2 — Compound Score (`heapq`)

After filtering workers with `skill_rating < required_min_rating` or `status = Busy`, each eligible worker is ranked by a **compound score**:

```
score = w_dist · (distance / max_dist) + w_rating · (1 − skill_rating / max_rating)
```

Default weights: **60 % distance, 40 % rating**.  Lower score = better match.

Workers are pushed onto a **min-heap** (`heapq`).  The global optimum is obtained in **O(log n)** via `heappop`.

### 3 — Atomic Assignment

The winning worker is marked `Busy` and the task `Assigned` in a single transaction, preventing double-assignment under concurrent requests.

## Quick Start

```bash
cd gig-engine

# Install dependencies
pip install -r requirements.txt

# (Optional) configure environment
cp .env.example .env   # edit DATABASE_URL if using PostgreSQL

# Run server (SQLite by default — no DB setup needed)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Open interactive docs
open http://localhost:8000/api/docs
```

## Running Tests

```bash
cd gig-engine
pytest -v
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./gig_engine.db` | DB connection string |
| `PORT` | `8000` | Uvicorn port |
| `LOG_LEVEL` | `info` | Uvicorn log level |
| `DISTANCE_WEIGHT` | `0.6` | Score weight for normalised distance |
| `RATING_WEIGHT` | `0.4` | Score weight for inverted skill rating |
| `MAX_REFERENCE_DISTANCE_KM` | `100.0` | Normalisation ceiling for distance |
| `MAX_SKILL_RATING` | `10.0` | Normalisation ceiling for skill rating |

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Readiness probe |
| `POST` | `/api/workers` | Register a new field worker |
| `GET` | `/api/workers` | List workers (optional `?status=Available`) |
| `GET` | `/api/workers/{id}` | Get worker by ID |
| `PATCH` | `/api/workers/{id}/status` | Update availability status |
| `POST` | `/api/tasks` | Create a gig task |
| `GET` | `/api/tasks` | List tasks (optional `?status=Pending`) |
| `GET` | `/api/tasks/{id}` | Get task by ID |
| `POST` | `/api/tasks/{id}/assign` | **Run matching engine** |
| `GET` | `/api/tasks/{id}/candidates` | Preview ranked candidates (read-only) |
| `PATCH` | `/api/tasks/{id}/complete` | Mark task completed, free worker |
