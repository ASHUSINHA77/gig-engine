"""
Pydantic schemas for request / response validation.

Kept separate from ORM models so that the API contract is independent of the
database layer.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AssignmentStatus, WorkerStatus


# ---------------------------------------------------------------------------
# Worker schemas
# ---------------------------------------------------------------------------


class WorkerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Alice"])
    latitude: float = Field(..., ge=-90.0, le=90.0, examples=[12.9716])
    longitude: float = Field(..., ge=-180.0, le=180.0, examples=[77.5946])
    skill_rating: float = Field(..., ge=0.0, le=10.0, examples=[7.5])
    status: WorkerStatus = Field(WorkerStatus.available, examples=["Available"])


class WorkerUpdate(BaseModel):
    """Partial update for worker status only."""

    status: WorkerStatus


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    latitude: float
    longitude: float
    skill_rating: float
    status: WorkerStatus


# ---------------------------------------------------------------------------
# GigTask schemas
# ---------------------------------------------------------------------------


class GigTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, examples=["Delivery — Koramangala"])
    description: Optional[str] = Field(None, examples=["Deliver 5 parcels by 6 PM"])
    latitude: float = Field(..., ge=-90.0, le=90.0, examples=[12.9352])
    longitude: float = Field(..., ge=-180.0, le=180.0, examples=[77.6245])
    required_min_rating: float = Field(..., ge=0.0, le=10.0, examples=[6.0])

    @field_validator("required_min_rating")
    @classmethod
    def rating_precision(cls, v: float) -> float:
        return round(v, 2)


class GigTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: Optional[str]
    latitude: float
    longitude: float
    required_min_rating: float
    assignment_status: AssignmentStatus
    assigned_worker_id: Optional[str]
    matched_worker_distance_km: Optional[float]
    matched_worker_score: Optional[float]


# ---------------------------------------------------------------------------
# Matching result schema
# ---------------------------------------------------------------------------


class MatchResult(BaseModel):
    """Returned by the POST /tasks/{task_id}/assign endpoint."""

    task_id: str
    assigned_worker: WorkerResponse
    distance_km: float = Field(..., description="Haversine distance from worker to task (km)")
    compound_score: float = Field(
        ...,
        description=(
            "Compound optimisation score (lower = better). "
            "Weighted blend of normalised distance and inverted skill rating."
        ),
    )
    candidates_evaluated: int = Field(
        ..., description="Number of eligible workers evaluated by the heap"
    )
