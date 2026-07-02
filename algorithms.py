"""
Core algorithmic pipeline for the Gig-Matching Engine.

The two building blocks are:

1. haversine()       — Real-world great-circle distance (km) from two
                       (lat, lon) pairs using the Haversine formula.

2. compound_score()  — Weighted normalisation of distance and (inverted)
                       skill rating into a single sortable float.  Lower is
                       better — a worker very close to the task with a high
                       rating scores near 0.0.

3. find_best_worker() — O(n log n) heap-based matching that:
                        a) Filters workers by minimum skill rating and
                           availability.
                        b) Pushes (score, distance, worker) tuples onto a
                           min-heap (Python heapq).
                        c) Pops the minimum — the best match — in O(log n).

All functions are pure and synchronous; they are called from async route
handlers that await database I/O around them.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Optional, Sequence

from app.config import settings
from app.models import Worker, WorkerStatus


# ---------------------------------------------------------------------------
# Haversine formula
# ---------------------------------------------------------------------------


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Compute the great-circle distance (kilometres) between two geographic
    points identified by their decimal-degree latitude and longitude.

    Uses the Haversine formula which is numerically stable for small distances
    and has an error of less than 0.5 % for terrestrial distances.

    Args:
        lat1, lon1: Latitude / longitude of the first point (degrees).
        lat2, lon2: Latitude / longitude of the second point (degrees).

    Returns:
        Distance in kilometres (float).
    """
    R = 6_371.0  # Mean Earth radius, km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    return R * c


# ---------------------------------------------------------------------------
# Compound score
# ---------------------------------------------------------------------------


def compound_score(
    distance_km: float,
    skill_rating: float,
    *,
    max_distance_km: float | None = None,
    max_rating: float | None = None,
    distance_weight: float | None = None,
    rating_weight: float | None = None,
) -> float:
    """
    Compute a normalised compound score in [0.0, 1.0+].  Lower is better.

    Score = distance_weight * (distance / max_distance)
          + rating_weight   * (1 - skill_rating / max_rating)

    The two weight parameters default to the values in ``settings`` so
    callers can use the tunable knobs from the environment without passing
    them explicitly.

    Args:
        distance_km:     Haversine distance between worker and task (km).
        skill_rating:    Worker's skill rating (0.0 – max_rating).
        max_distance_km: Normalisation ceiling for distance (default from settings).
        max_rating:      Normalisation ceiling for ratings (default from settings).
        distance_weight: Contribution of distance term (default from settings).
        rating_weight:   Contribution of inverted-rating term (default from settings).

    Returns:
        Compound score as a float (lower ⇒ better match).
    """
    max_d = max_distance_km if max_distance_km is not None else settings.max_reference_distance_km
    max_r = max_rating if max_rating is not None else settings.max_skill_rating
    w_d = distance_weight if distance_weight is not None else settings.distance_weight
    w_r = rating_weight if rating_weight is not None else settings.rating_weight

    dist_norm = min(distance_km / max_d, 1.0)          # cap at 1.0 if worker is very far
    rating_norm = 1.0 - min(skill_rating / max_r, 1.0) # inverted: lower skill → higher penalty

    return w_d * dist_norm + w_r * rating_norm


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class MatchCandidate:
    """Lightweight wrapper for a candidate returned by the heap."""

    worker: Worker
    distance_km: float
    score: float


# ---------------------------------------------------------------------------
# Heap-based matching engine
# ---------------------------------------------------------------------------


def find_best_worker(
    task_lat: float,
    task_lon: float,
    required_min_rating: float,
    workers: Sequence[Worker],
) -> tuple[Optional[MatchCandidate], int]:
    """
    Select the optimal available worker for a gig task.

    Algorithm
    ---------
    1. For each worker, skip if skill_rating < required_min_rating or status
       is not Available.
    2. Compute Haversine distance and compound score.
    3. Push (score, distance, worker.id, worker) onto a min-heap.  worker.id
       is used as the tiebreaker when two scores are equal to avoid comparing
       Worker ORM objects.
    4. heappop() yields the globally optimal candidate in O(log n).

    Returns
    -------
    (MatchCandidate | None, candidates_evaluated: int)
    """
    heap: list[tuple[float, float, str, Worker]] = []

    candidates_evaluated = 0

    for worker in workers:
        # Filter: wrong status or insufficient skill
        if worker.status != WorkerStatus.available:
            continue
        if worker.skill_rating < required_min_rating:
            continue

        dist = haversine(task_lat, task_lon, worker.latitude, worker.longitude)
        score = compound_score(dist, worker.skill_rating)

        # Heap tuple: (score, distance, id-tiebreaker, worker-object)
        heapq.heappush(heap, (score, dist, worker.id, worker))
        candidates_evaluated += 1

    if not heap:
        return None, candidates_evaluated

    best_score, best_dist, _, best_worker = heapq.heappop(heap)
    return MatchCandidate(worker=best_worker, distance_km=best_dist, score=best_score), candidates_evaluated


# ---------------------------------------------------------------------------
# Convenience: rank all eligible workers (for /tasks/{id}/candidates endpoint)
# ---------------------------------------------------------------------------


def rank_all_workers(
    task_lat: float,
    task_lon: float,
    required_min_rating: float,
    workers: Sequence[Worker],
) -> list[MatchCandidate]:
    """
    Return ALL eligible workers sorted by compound score (ascending).

    Useful for diagnostics and transparency endpoints.  Uses heapify + repeated
    heappop so the sort is still O(n log n) via the heap.
    """
    heap: list[tuple[float, float, str, Worker]] = []

    for worker in workers:
        if worker.status != WorkerStatus.available:
            continue
        if worker.skill_rating < required_min_rating:
            continue
        dist = haversine(task_lat, task_lon, worker.latitude, worker.longitude)
        score = compound_score(dist, worker.skill_rating)
        heapq.heappush(heap, (score, dist, worker.id, worker))

    result: list[MatchCandidate] = []
    while heap:
        score, dist, _, worker = heapq.heappop(heap)
        result.append(MatchCandidate(worker=worker, distance_km=dist, score=score))

    return result
