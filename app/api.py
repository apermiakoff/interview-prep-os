from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException

from app.db import connect, database_path
from app.repository import bootstrap
from app.schemas import AttemptCreate, HealthResponse, HintCreate, NotesUpdate
from app.services import ConflictError, NotFoundError, record_attempt, reveal_hint, save_notes

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
