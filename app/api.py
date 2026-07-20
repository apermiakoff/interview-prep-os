from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query

from app.db import connect, database_path, transaction
from app.learning import (
    daily_recommendation,
    learning_profile,
    learning_roadmap,
    skill_detail,
)
from app.repository import bootstrap, problem_catalog, problem_detail
from app.schemas import AttemptCreate, HealthResponse, HintCreate, NotesUpdate, QueueBulkUpdate
from app.services import (
    ConflictError,
    NotFoundError,
    record_attempt,
    reveal_hint,
    save_notes,
    update_queue,
)

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    path = database_path()
    with connect(path) as connection:
        connection.execute("SELECT 1").fetchone()
    from datetime import date

    return HealthResponse(status="ok", database="ready", today=date.today())


@router.get("/bootstrap")
def get_bootstrap() -> dict:
    with connect() as connection:
        return bootstrap(connection)


@router.get("/problems")
def get_problems(
    search: str = Query(default="", max_length=120),
    status: str | None = Query(default=None, max_length=120),
    pattern: str | None = Query(default=None, max_length=120),
    difficulty: str | None = Query(default=None, max_length=20),
    track: str | None = Query(default=None, max_length=60),
    scope: str = Query(default="all", pattern="^(all|queue|reviews)$"),
    sort: str = Query(default="priority", pattern="^(priority|due|title|evidence|recent)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
) -> dict:
    statuses = [value for value in (status or "").split(",") if value]
    allowed = {
        "active",
        "overdue",
        "due",
        "upcoming",
        "blocked",
        "backlog",
        "learning",
        "stable",
        "archived",
        "catalog",
    }
    if any(value not in allowed for value in statuses):
        raise HTTPException(status_code=422, detail="invalid problem status")
    with connect() as connection:
        return problem_catalog(
            connection,
            search=search,
            statuses=statuses,
            pattern=pattern,
            difficulty=difficulty,
            track=track,
            scope=scope,
            sort=sort,
            page=page,
            page_size=page_size,
        )


@router.get("/learning/profile")
def get_learning_profile() -> dict:
    with transaction() as connection:
        return learning_profile(connection)


@router.get("/learning/today")
def get_learning_today(timebox: int = Query(default=35, ge=10, le=240)) -> dict:
    with transaction() as connection:
        return daily_recommendation(connection, timebox_minutes=timebox)


@router.get("/learning/roadmap")
def get_learning_roadmap() -> dict:
    with transaction() as connection:
        return learning_roadmap(connection)


@router.get("/skills/{skill_id:path}")
def get_skill(skill_id: str) -> dict:
    with transaction() as connection:
        result = skill_detail(connection, skill_id)
    if result is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return result


@router.get("/problems/{problem_id}")
def get_problem(problem_id: int) -> dict:
    with connect() as connection:
        result = problem_detail(connection, problem_id)
    if result is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return result


@router.put("/queue")
def bulk_update_queue(payload: QueueBulkUpdate) -> dict:
    return update_queue(payload)


@router.post("/attempts")
def create_attempt(payload: AttemptCreate) -> dict:
    try:
        return record_attempt(payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="attempt could not be recorded") from exc


@router.post("/hints")
def create_hint(payload: HintCreate) -> dict:
    try:
        return reveal_hint(payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/assignments/{assignment_id}/notes")
def update_notes(assignment_id: str, payload: NotesUpdate) -> dict:
    try:
        return save_notes(assignment_id, payload.content)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
