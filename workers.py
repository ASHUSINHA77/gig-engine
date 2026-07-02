"""Worker endpoints."""

from __future__ import annotations

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.database import get_db
from app.models import WorkerStatus
from app.schemas import WorkerCreate, WorkerResponse, WorkerUpdate

router = APIRouter(prefix="/workers", tags=["Workers"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "",
    response_model=WorkerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new field worker",
)
async def create_worker(payload: WorkerCreate, db: DbDep) -> WorkerResponse:
    worker = await crud.create_worker(db, payload)
    return WorkerResponse.model_validate(worker)


@router.get(
    "",
    response_model=List[WorkerResponse],
    summary="List workers (optionally filtered by status)",
)
async def list_workers(
    db: DbDep,
    status_filter: Optional[WorkerStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[WorkerResponse]:
    workers = await crud.list_workers(db, status=status_filter, limit=limit, offset=offset)
    return [WorkerResponse.model_validate(w) for w in workers]


@router.get(
    "/{worker_id}",
    response_model=WorkerResponse,
    summary="Get a specific worker by ID",
)
async def get_worker(worker_id: str, db: DbDep) -> WorkerResponse:
    worker = await crud.get_worker(db, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found")
    return WorkerResponse.model_validate(worker)


@router.patch(
    "/{worker_id}/status",
    response_model=WorkerResponse,
    summary="Update a worker's availability status",
)
async def update_worker_status(
    worker_id: str, payload: WorkerUpdate, db: DbDep
) -> WorkerResponse:
    worker = await crud.get_worker(db, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found")
    worker = await crud.update_worker_status(db, worker, payload.status)
    return WorkerResponse.model_validate(worker)
