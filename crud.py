"""
Async CRUD helpers.

All database I/O is awaited so FastAPI's event loop is never blocked.

Concurrency safety
------------------
``assign_task_atomic`` is the only function that performs the read-check-write
sequence for task assignment.  It uses ``SELECT … FOR UPDATE`` on PostgreSQL to
acquire row-level locks on both the task and all candidate worker rows before
any mutation, ensuring that two concurrent assignment requests cannot:

  * both pass the ``Pending`` guard (double-assignment of the same task), or
  * both select the same worker as Available (double-booking).

SQLite (used in tests and local dev) serialises writers at the connection level
so it does not support ``FOR UPDATE``; the clause is skipped automatically.
"""

from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms import MatchCandidate, find_best_worker
from app.config import settings
from app.models import AssignmentStatus, GigTask, Worker, WorkerStatus
from app.schemas import GigTaskCreate, WorkerCreate

# True when the configured database supports SELECT … FOR UPDATE
_USE_FOR_UPDATE: bool = not settings.database_url.startswith("sqlite")


# ---------------------------------------------------------------------------
# Worker CRUD
# ---------------------------------------------------------------------------


async def create_worker(db: AsyncSession, data: WorkerCreate) -> Worker:
    worker = Worker(
        name=data.name,
        latitude=data.latitude,
        longitude=data.longitude,
        skill_rating=data.skill_rating,
        status=data.status,
    )
    db.add(worker)
    await db.flush()
    await db.refresh(worker)
    return worker


async def get_worker(db: AsyncSession, worker_id: str) -> Optional[Worker]:
    result = await db.execute(select(Worker).where(Worker.id == worker_id))
    return result.scalar_one_or_none()


async def list_workers(
    db: AsyncSession,
    *,
    status: Optional[WorkerStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[Worker]:
    stmt = select(Worker).offset(offset).limit(limit)
    if status is not None:
        stmt = stmt.where(Worker.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


async def update_worker_status(
    db: AsyncSession, worker: Worker, new_status: WorkerStatus
) -> Worker:
    worker.status = new_status
    db.add(worker)
    await db.flush()
    await db.refresh(worker)
    return worker


# ---------------------------------------------------------------------------
# GigTask CRUD
# ---------------------------------------------------------------------------


async def create_task(db: AsyncSession, data: GigTaskCreate) -> GigTask:
    task = GigTask(
        title=data.title,
        description=data.description,
        latitude=data.latitude,
        longitude=data.longitude,
        required_min_rating=data.required_min_rating,
        assignment_status=AssignmentStatus.pending,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get_task(db: AsyncSession, task_id: str) -> Optional[GigTask]:
    result = await db.execute(select(GigTask).where(GigTask.id == task_id))
    return result.scalar_one_or_none()


async def list_tasks(
    db: AsyncSession,
    *,
    status: Optional[AssignmentStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[GigTask]:
    stmt = select(GigTask).offset(offset).limit(limit)
    if status is not None:
        stmt = stmt.where(GigTask.assignment_status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


async def assign_task_atomic(
    db: AsyncSession,
    task_id: str,
) -> tuple[Optional[GigTask], Optional["MatchCandidate"], int, str]:
    """
    Concurrency-safe, all-in-one task assignment.

    Uses ``SELECT … FOR UPDATE`` (PostgreSQL) to hold row-level locks on the
    target task and all candidate workers for the duration of the transaction,
    so two concurrent requests for the same task — or two requests competing
    for the same worker — cannot both succeed.

    Returns
    -------
    (task, match, candidates_evaluated, error_code)

    error_code values
    -----------------
    ""           — success
    "not_found"  — task does not exist
    "not_pending"— task is already Assigned or Completed
    "no_match"   — no eligible available worker found
    """
    # -----------------------------------------------------------------------
    # 1. Lock the task row (prevents concurrent double-assignment of same task)
    # -----------------------------------------------------------------------
    stmt = select(GigTask).where(GigTask.id == task_id)
    if _USE_FOR_UPDATE:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        return None, None, 0, "not_found"
    if task.assignment_status != AssignmentStatus.pending:
        return task, None, 0, "not_pending"

    # -----------------------------------------------------------------------
    # 2. Lock all available workers (prevents the same worker being double-booked
    #    by two concurrent assignment requests for different tasks)
    # -----------------------------------------------------------------------
    w_stmt = select(Worker).where(Worker.status == WorkerStatus.available)
    if _USE_FOR_UPDATE:
        w_stmt = w_stmt.with_for_update()
    w_result = await db.execute(w_stmt)
    available_workers = w_result.scalars().all()

    # -----------------------------------------------------------------------
    # 3. Run the pure matching algorithm on the locked snapshot
    # -----------------------------------------------------------------------
    match, candidates_evaluated = find_best_worker(
        task_lat=task.latitude,
        task_lon=task.longitude,
        required_min_rating=task.required_min_rating,
        workers=available_workers,
    )

    if match is None:
        return task, None, candidates_evaluated, "no_match"

    # -----------------------------------------------------------------------
    # 4. Commit the assignment — both writes happen in the same transaction
    # -----------------------------------------------------------------------
    task.assignment_status = AssignmentStatus.assigned
    task.assigned_worker_id = match.worker.id
    task.matched_worker_distance_km = round(match.distance_km, 4)
    task.matched_worker_score = round(match.score, 6)
    match.worker.status = WorkerStatus.busy
    db.add(task)
    db.add(match.worker)
    await db.flush()
    await db.refresh(task)
    await db.refresh(match.worker)

    return task, match, candidates_evaluated, ""


async def get_available_workers(db: AsyncSession) -> Sequence[Worker]:
    """Fetch all Available workers — used by the candidates preview endpoint."""
    result = await db.execute(
        select(Worker).where(Worker.status == WorkerStatus.available)
    )
    return result.scalars().all()


async def complete_task(db: AsyncSession, task: GigTask) -> GigTask:
    """Mark task Completed and free the worker."""
    if task.assigned_worker_id:
        worker = await get_worker(db, task.assigned_worker_id)
        if worker:
            worker.status = WorkerStatus.available
            db.add(worker)
    task.assignment_status = AssignmentStatus.completed
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task
