"""GigTask endpoints including the core matching pipeline."""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.algorithms import find_best_worker, rank_all_workers
from app.database import get_db
from app.models import AssignmentStatus
from app.schemas import (
    GigTaskCreate,
    GigTaskResponse,
    MatchResult,
    WorkerResponse,
)

router = APIRouter(prefix="/tasks", tags=["GigTasks"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=GigTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new gig task",
)
async def create_task(payload: GigTaskCreate, db: DbDep) -> GigTaskResponse:
    task = await crud.create_task(db, payload)
    return GigTaskResponse.model_validate(task)


@router.get(
    "",
    response_model=List[GigTaskResponse],
    summary="List gig tasks (optionally filtered by assignment status)",
)
async def list_tasks(
    db: DbDep,
    status_filter: Optional[AssignmentStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[GigTaskResponse]:
    tasks = await crud.list_tasks(db, status=status_filter, limit=limit, offset=offset)
    return [GigTaskResponse.model_validate(t) for t in tasks]


@router.get(
    "/{task_id}",
    response_model=GigTaskResponse,
    summary="Get a specific gig task by ID",
)
async def get_task(task_id: str, db: DbDep) -> GigTaskResponse:
    task = await crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return GigTaskResponse.model_validate(task)


@router.post(
    "/{task_id}/assign",
    response_model=MatchResult,
    summary="Run the Gig-Matching Engine for a pending task",
    description=(
        "Triggers the concurrency-safe algorithmic matching pipeline:\n\n"
        "1. **Row-level lock** — acquires `SELECT … FOR UPDATE` on the task row "
        "(PostgreSQL) so two simultaneous requests cannot both pass the Pending guard.\n"
        "2. **Worker lock** — locks all Available worker rows in the same transaction "
        "to prevent the same worker being double-booked across concurrent tasks.\n"
        "3. **Haversine distance** — computes real-world distances (km) from every "
        "locked available worker to the task location.\n"
        "4. **Eligibility filter** — excludes workers with "
        "`skill_rating < required_min_rating`.\n"
        "5. **Priority-queue ranking** — uses Python `heapq` to rank eligible workers "
        "by a compound score (weighted normalised distance + inverted skill rating).\n"
        "6. **Atomic commit** — marks the winning worker `Busy` and the task "
        "`Assigned` in the same transaction that held the locks."
    ),
)
async def assign_task(task_id: str, db: DbDep) -> MatchResult:
    task, match, candidates_evaluated, error = await crud.assign_task_atomic(db, task_id)

    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    if error == "not_pending":
        raise HTTPException(
            status_code=409,
            detail=f"Task is already '{task.assignment_status.value}' — cannot re-assign",
        )
    if error == "no_match":
        raise HTTPException(
            status_code=422,
            detail=(
                f"No eligible available workers found for task '{task_id}'. "
                f"Evaluated {candidates_evaluated} available worker(s); all were "
                f"filtered by the minimum skill rating ({task.required_min_rating})."
            ),
        )

    return MatchResult(
        task_id=task.id,
        assigned_worker=WorkerResponse.model_validate(match.worker),
        distance_km=round(match.distance_km, 4),
        compound_score=round(match.score, 6),
        candidates_evaluated=candidates_evaluated,
    )


@router.get(
    "/{task_id}/candidates",
    response_model=List[dict],
    summary="Preview ranked candidates for a pending task without assigning",
    description=(
        "Returns all eligible workers ranked by compound score (ascending). "
        "Useful for debugging the matching algorithm without mutating state."
    ),
)
async def list_candidates(task_id: str, db: DbDep) -> list:
    task = await crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    available_workers = await crud.get_available_workers(db)
    ranked = rank_all_workers(
        task_lat=task.latitude,
        task_lon=task.longitude,
        required_min_rating=task.required_min_rating,
        workers=available_workers,
    )

    return [
        {
            "rank": i + 1,
            "worker_id": m.worker.id,
            "worker_name": m.worker.name,
            "skill_rating": m.worker.skill_rating,
            "distance_km": round(m.distance_km, 4),
            "compound_score": round(m.score, 6),
        }
        for i, m in enumerate(ranked)
    ]


@router.patch(
    "/{task_id}/complete",
    response_model=GigTaskResponse,
    summary="Mark an assigned task as completed (frees the worker)",
)
async def complete_task(task_id: str, db: DbDep) -> GigTaskResponse:
    task = await crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    if task.assignment_status != AssignmentStatus.assigned:
        raise HTTPException(
            status_code=409,
            detail=f"Only 'Assigned' tasks can be completed (current: '{task.assignment_status.value}')",
        )

    task = await crud.complete_task(db, task)
    return GigTaskResponse.model_validate(task)
