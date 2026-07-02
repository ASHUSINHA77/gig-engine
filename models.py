"""
SQLAlchemy ORM models.

Worker  — field agent available to pick up gig tasks
GigTask — a unit of work that needs to be assigned to a qualified worker
"""

from __future__ import annotations

import enum
import uuid

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Column,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class WorkerStatus(str, enum.Enum):
    available = "Available"
    busy = "Busy"


class AssignmentStatus(str, enum.Enum):
    pending = "Pending"
    assigned = "Assigned"
    completed = "Completed"


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class Worker(Base):
    __tablename__ = "workers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # Skill rating in [0.0, 10.0].  Enterprise clients filter by minimum rating.
    skill_rating = Column(Float, nullable=False)
    status = Column(
        Enum(WorkerStatus, name="worker_status"),
        nullable=False,
        default=WorkerStatus.available,
    )

    __allow_unmapped__ = True

    # A worker can be assigned to many tasks over their lifetime
    assigned_tasks: List["GigTask"] = relationship("GigTask", back_populates="assigned_worker")

    def __repr__(self) -> str:
        return f"<Worker id={self.id!r} name={self.name!r} status={self.status}>"


# ---------------------------------------------------------------------------
# GigTask
# ---------------------------------------------------------------------------


class GigTask(Base):
    __tablename__ = "gig_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # Workers with skill_rating below this threshold are ineligible
    required_min_rating = Column(Float, nullable=False)
    assignment_status = Column(
        Enum(AssignmentStatus, name="assignment_status"),
        nullable=False,
        default=AssignmentStatus.pending,
    )
    # NULL until a worker is assigned
    assigned_worker_id = Column(String(36), ForeignKey("workers.id"), nullable=True)

    # Denormalised match metadata written at assignment time
    matched_worker_distance_km = Column(Float, nullable=True)
    matched_worker_score = Column(Float, nullable=True)

    __allow_unmapped__ = True

    assigned_worker: Optional["Worker"] = relationship("Worker", back_populates="assigned_tasks")

    def __repr__(self) -> str:
        return f"<GigTask id={self.id!r} title={self.title!r} status={self.assignment_status}>"
