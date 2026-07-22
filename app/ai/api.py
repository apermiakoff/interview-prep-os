from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.ai.ai_db import connect as ai_connect
from app.ai.ai_db import migrate as migrate_ai
from app.ai.ai_db import now
from app.ai.ai_db import transaction as ai_transaction
from app.ai.artifacts import prompt
from app.ai.config import AIConfig, AIConfigError, estimate_tokens
from app.ai.context import canonical, learning_snapshot, problem_snapshot, session_snapshot
from app.ai.domain import ChatRequest, ConversationCreate, GenerationRequest
from app.ai.repository import (
    AIBudgetError,
    AIConflictError,
    AIInputTooLargeError,
    create_conversation,
    enqueue,
    list_conversations,
    month_usage,
    request_cancel,
    reserved_tokens,
    save_snapshot,
)
from app.db import connect as core_connect
from app.db import transaction as core_transaction
from app.errors import NotFoundError

router = APIRouter(prefix="/api/ai", tags=["community-ai"])


def config() -> AIConfig:
    try:
        return AIConfig.from_env()
    except AIConfigError as exc:
        raise HTTPException(status_code=503, detail=f"invalid AI configuration: {exc}") from exc


def enabled() -> AIConfig:
    value = config()
    if not value.enabled:
        raise HTTPException(status_code=503, detail="community AI is disabled")
    migrate_ai(value.db_path)
    return value


def public_run(row) -> dict:
    allowed = (
        "id",
        "conversation_id",
        "kind",
        "scope",
        "scope_id",
        "status",
        "attempts",
        "max_attempts",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
        "completed_at",
    )
    return {key: row[key] for key in allowed}


def public_artifact(row) -> dict:
    result = dict(row)
    result["content"] = json.loads(result.pop("content_json"))
    return result


def fail(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, AIConflictError):
        return HTTPException(409, str(exc))
    if isinstance(exc, AIBudgetError):
        return HTTPException(402, str(exc))
    if isinstance(exc, AIInputTooLargeError):
        return HTTPException(413, str(exc))
    raise exc


@router.get("/status")
def status() -> dict:
    value = config()
    result = value.masked()
    result["status"] = "ready" if value.enabled else "disabled"
    return result


def _ensure_scope(scope: str, scope_id: str) -> None:
    with core_connect() as connection:
        if scope == "problem":
            problem_snapshot(connection, int(scope_id))
        else:
            session_snapshot(connection, scope_id)


def _create(scope: str, scope_id: str, payload: ConversationCreate) -> dict:
    value = enabled()
    _ensure_scope(scope, scope_id)
    with ai_transaction(value.db_path) as connection:
        return create_conversation(connection, scope, scope_id, payload.title)


def _list(scope: str, scope_id: str) -> list[dict]:
    value = enabled()
    _ensure_scope(scope, scope_id)
    with ai_connect(value.db_path) as connection:
        return list_conversations(connection, scope, scope_id)


@router.post("/problems/{problem_id}/conversations", status_code=201)
def create_problem_conversation(problem_id: int, payload: ConversationCreate) -> dict:
    return _create("problem", str(problem_id), payload)


@router.get("/problems/{problem_id}/conversations")
def list_problem_conversations(problem_id: int) -> list[dict]:
    return _list("problem", str(problem_id))


@router.post("/sessions/{session_id}/conversations", status_code=201)
def create_session_conversation(session_id: str, payload: ConversationCreate) -> dict:
    return _create("session", session_id, payload)


@router.get("/sessions/{session_id}/conversations")
def list_session_conversations(session_id: str) -> list[dict]:
    return _list("session", session_id)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    value = enabled()
    with ai_connect(value.db_path) as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "conversation not found")
        messages = [
            dict(item)
            for item in connection.execute(
                "SELECT id,role,content,run_id,created_at FROM messages "
                "WHERE conversation_id=? ORDER BY created_at,id",
                (conversation_id,),
            )
        ]
    return {**dict(row), "messages": messages}


@router.post("/conversations/{conversation_id}/messages", status_code=202)
def post_message(conversation_id: str, payload: ChatRequest) -> dict:
    value = enabled()
    try:
        with ai_transaction(value.db_path) as ai_connection:
            owner = ai_connection.execute(
                "SELECT scope,scope_id FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not owner:
                raise NotFoundError("conversation not found")
            scope, scope_id = owner["scope"], owner["scope_id"]
            with core_transaction() as core_connection:
                if scope == "session":
                    updated = core_connection.execute(
                        "UPDATE practice_sessions SET ai_assisted=1,updated_at=? WHERE id=?",
                        (now(), scope_id),
                    )
                    if not updated.rowcount:
                        raise NotFoundError("practice session not found")
                    snapshot = session_snapshot(core_connection, scope_id)
                else:
                    snapshot = problem_snapshot(core_connection, int(scope_id))
                snapshot_id = save_snapshot(ai_connection, scope, scope_id, snapshot)
                request = {"content": payload.content}
                system, user = prompt(
                    "chat", snapshot, {**request, "idempotency_key": payload.idempotency_key}
                )
                run, created = enqueue(
                    ai_connection,
                    value,
                    kind="chat",
                    scope=scope,
                    scope_id=scope_id,
                    snapshot_id=snapshot_id,
                    request=request,
                    conversation_id=conversation_id,
                    idempotency_key=payload.idempotency_key,
                    estimated_input_tokens=estimate_tokens(system, user),
                )
        return {"run": public_run(run), "created": created}
    except (NotFoundError, AIConflictError, AIBudgetError, AIInputTooLargeError) as exc:
        raise fail(exc) from exc


def _enqueue_generation(
    connection,
    value: AIConfig,
    kind: str,
    scope: str,
    scope_id: str,
    payload: GenerationRequest,
    snapshot: dict,
) -> dict:
    request = {"instructions": payload.instructions}
    full_request = {**request, "idempotency_key": payload.idempotency_key}
    system, user = prompt(kind, snapshot, full_request)
    digest = hashlib.sha256(
        f"{kind}:{canonical(snapshot)}:{payload.instructions}:{value.provider}:{value.model}".encode()
    ).hexdigest()
    snapshot_id = save_snapshot(connection, scope, scope_id, snapshot)
    run, created = enqueue(
        connection,
        value,
        kind=kind,
        scope=scope,
        scope_id=scope_id,
        snapshot_id=snapshot_id,
        request=request,
        idempotency_key=payload.idempotency_key,
        cache_key=digest,
        schema_version={
            "lesson": "lesson@1",
            "visualization": "visualization@1",
            "diagnosis": "diagnosis@1",
        }[kind],
        estimated_input_tokens=estimate_tokens(system, user),
    )
    return {"run": public_run(run), "created": created}


def _generate(kind: str, scope: str, scope_id: str, payload: GenerationRequest) -> dict:
    value = enabled()
    try:
        if scope == "session":
            with (
                ai_transaction(value.db_path) as connection,
                core_transaction() as core,
            ):
                updated = core.execute(
                    "UPDATE practice_sessions SET ai_assisted=1,updated_at=? WHERE id=?",
                    (now(), scope_id),
                )
                if not updated.rowcount:
                    raise NotFoundError("practice session not found")
                snapshot = session_snapshot(core, scope_id)
                result = _enqueue_generation(
                    connection, value, kind, scope, scope_id, payload, snapshot
                )
            return result
        with core_connect() as core:
            snapshot = (
                problem_snapshot(core, int(scope_id))
                if scope == "problem"
                else learning_snapshot(core)
            )
        with ai_transaction(value.db_path) as connection:
            return _enqueue_generation(connection, value, kind, scope, scope_id, payload, snapshot)
    except (NotFoundError, AIConflictError, AIBudgetError, AIInputTooLargeError) as exc:
        raise fail(exc) from exc


@router.post("/problems/{problem_id}/lesson", status_code=202)
def generate_lesson(problem_id: int, payload: GenerationRequest) -> dict:
    return _generate("lesson", "problem", str(problem_id), payload)


@router.post("/problems/{problem_id}/visualization", status_code=202)
def generate_visualization(problem_id: int, payload: GenerationRequest) -> dict:
    return _generate("visualization", "problem", str(problem_id), payload)


@router.post("/problems/{problem_id}/diagnosis", status_code=202)
def generate_diagnosis(problem_id: int, payload: GenerationRequest) -> dict:
    return _generate("diagnosis", "problem", str(problem_id), payload)


@router.post("/sessions/{session_id}/diagnosis", status_code=202)
def generate_session_diagnosis(session_id: str, payload: GenerationRequest) -> dict:
    return _generate("diagnosis", "session", session_id, payload)


@router.post("/learning/diagnosis", status_code=202)
def generate_learning_diagnosis(payload: GenerationRequest) -> dict:
    return _generate("diagnosis", "learning", "learner", payload)


def _artifacts(scope: str, scope_id: str, kind: str | None, limit: int) -> list[dict]:
    value = enabled()
    if scope != "learning":
        _ensure_scope(scope, scope_id)
    where = "scope=? AND scope_id=?"
    parameters: list[str | int] = [scope, scope_id]
    if kind:
        where += " AND kind=?"
        parameters.append(kind)
    parameters.append(limit)
    with ai_connect(value.db_path) as connection:
        rows = connection.execute(
            "SELECT id,scope,scope_id,kind,version,schema_version,content_json,run_id,"
            "context_snapshot_id,prompt_version,provider,model,created_at FROM artifacts "
            f"WHERE {where} ORDER BY version DESC,created_at DESC,id DESC LIMIT ?",
            parameters,
        ).fetchall()
    return [public_artifact(row) for row in rows]


def _latest_artifact(scope: str, scope_id: str, kind: str) -> dict:
    rows = _artifacts(scope, scope_id, kind, 1)
    if not rows:
        raise HTTPException(404, "AI artifact not found")
    return rows[0]


@router.get("/problems/{problem_id}/artifacts/latest")
def latest_problem_artifact(problem_id: int, kind: str) -> dict:
    return _latest_artifact("problem", str(problem_id), kind)


@router.get("/problems/{problem_id}/artifacts")
def list_problem_artifacts(
    problem_id: int,
    kind: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return _artifacts("problem", str(problem_id), kind, limit)


@router.get("/sessions/{session_id}/artifacts/latest")
def latest_session_artifact(session_id: str, kind: str) -> dict:
    return _latest_artifact("session", session_id, kind)


@router.get("/sessions/{session_id}/artifacts")
def list_session_artifacts(
    session_id: str,
    kind: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return _artifacts("session", session_id, kind, limit)


@router.get("/learning/diagnosis/latest")
def latest_learning_diagnosis() -> dict:
    return _latest_artifact("learning", "learner", "diagnosis")


@router.get("/learning/diagnosis/history")
def learning_diagnosis_history(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return _artifacts("learning", "learner", "diagnosis", limit)


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    value = enabled()
    with ai_connect(value.db_path) as connection:
        row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, "AI run not found")
        artifact = connection.execute(
            "SELECT id,kind,version,schema_version,content_json,created_at "
            "FROM artifacts WHERE run_id=?",
            (run_id,),
        ).fetchone()
    result = public_run(row)
    if artifact:
        result["artifact"] = public_artifact(artifact)
    return result


@router.post("/runs/{run_id}/cancel", status_code=202)
def cancel_run(run_id: str) -> dict:
    value = enabled()
    with ai_transaction(value.db_path) as connection:
        row = request_cancel(connection, run_id)
        if not row:
            raise HTTPException(404, "AI run not found")
    return {
        "id": run_id,
        "status": row["status"],
        "cancel_requested": bool(row["cancel_requested"]),
    }


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    value = enabled()
    try:
        cursor = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise HTTPException(400, "invalid Last-Event-ID") from exc
    with ai_connect(value.db_path) as connection:
        if not connection.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            raise HTTPException(404, "AI run not found")

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        idle = 0
        while not await request.is_disconnected():
            with ai_connect(value.db_path) as connection:
                rows = connection.execute(
                    "SELECT id,event_type,data_json FROM run_events "
                    "WHERE run_id=? AND id>? ORDER BY id LIMIT 100",
                    (run_id, cursor),
                ).fetchall()
                terminal = connection.execute(
                    "SELECT status FROM runs WHERE id=?", (run_id,)
                ).fetchone()["status"]
            if rows:
                idle = 0
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {row['data_json']}\n\n"
            else:
                idle += 1
                if idle >= 15:
                    idle = 0
                    yield ": heartbeat\n\n"
            if terminal in {"completed", "failed", "cancelled"} and not rows:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/usage")
def usage() -> dict:
    value = enabled()
    with ai_connect(value.db_path) as connection:
        used = month_usage(connection)
        reserved = reserved_tokens(connection)
    return {
        "tokens_used": used,
        "tokens_reserved": reserved,
        "token_budget": value.monthly_token_budget,
        "tokens_remaining": max(0, value.monthly_token_budget - used - reserved),
    }
