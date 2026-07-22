from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from app.ai.ai_db import now
from app.ai.config import AIConfig


class AIConflictError(RuntimeError):
    pass


class AIBudgetError(RuntimeError):
    pass


class AIInputTooLargeError(RuntimeError):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def save_snapshot(connection: sqlite3.Connection, scope: str, scope_id: str, content: dict) -> str:
    # Keep the worker dependency closure independent from core-facing context code.
    body = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    existing = connection.execute(
        "SELECT id FROM context_snapshots WHERE scope=? AND scope_id=? AND content_hash=?",
        (scope, scope_id, digest),
    ).fetchone()
    if existing:
        return existing["id"]
    snapshot_id = _uuid()
    connection.execute(
        "INSERT INTO context_snapshots VALUES(?,?,?,?,?,?,?)",
        (snapshot_id, scope, scope_id, content["schema_version"], body, digest, now()),
    )
    return snapshot_id


def create_conversation(
    connection: sqlite3.Connection, scope: str, scope_id: str, title: str
) -> dict:
    conversation_id = _uuid()
    timestamp = now()
    connection.execute(
        "INSERT INTO conversations VALUES(?,?,?,?,?,?)",
        (conversation_id, scope, scope_id, title, timestamp, timestamp),
    )
    return dict(
        connection.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    )


def conversation(connection: sqlite3.Connection, conversation_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["messages"] = [
        dict(item)
        for item in connection.execute(
            "SELECT id,role,content,run_id,created_at FROM messages "
            "WHERE conversation_id=? ORDER BY created_at,id",
            (conversation_id,),
        )
    ]
    return result


def list_conversations(connection: sqlite3.Connection, scope: str, scope_id: str) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM conversations WHERE scope=? AND scope_id=? ORDER BY updated_at DESC",
            (scope, scope_id),
        )
    ]


def month_usage(connection: sqlite3.Connection) -> int:
    prefix = datetime.now(UTC).strftime("%Y-%m")
    return int(
        connection.execute(
            "SELECT COALESCE(SUM(total_tokens),0) value FROM usage_ledger WHERE occurred_at LIKE ?",
            (f"{prefix}%",),
        ).fetchone()["value"]
    )


def reserved_tokens(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COALESCE(SUM(reserved_tokens),0) value FROM runs "
            "WHERE status IN ('queued','running')"
        ).fetchone()["value"]
    )


def assert_budget(connection: sqlite3.Connection, config: AIConfig, reservation: int) -> None:
    if (
        month_usage(connection) + reserved_tokens(connection) + reservation
        > config.monthly_token_budget
    ):
        raise AIBudgetError("monthly AI token budget exhausted")


def enqueue(
    connection: sqlite3.Connection,
    config: AIConfig,
    *,
    kind: str,
    scope: str,
    scope_id: str,
    snapshot_id: str,
    request: dict,
    conversation_id: str | None = None,
    idempotency_key: str,
    cache_key: str | None = None,
    schema_version: str | None = None,
    estimated_input_tokens: int,
) -> tuple[dict, bool]:
    if conversation_id:
        owner = connection.execute(
            "SELECT scope,scope_id FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if not owner or owner["scope"] != scope or owner["scope_id"] != scope_id:
            raise AIConflictError("conversation belongs to a different scope")
        existing_message = connection.execute(
            "SELECT run_id,content FROM messages WHERE conversation_id=? AND idempotency_key=?",
            (conversation_id, idempotency_key),
        ).fetchone()
        if existing_message:
            run = connection.execute(
                "SELECT * FROM runs WHERE id=?", (existing_message["run_id"],)
            ).fetchone()
            if existing_message["content"] != request.get("content"):
                raise AIConflictError("idempotency key was used with a different message")
            return dict(run), False
    else:
        existing = connection.execute(
            "SELECT * FROM runs WHERE scope=? AND scope_id=? AND kind=? "
            "AND json_extract(request_json,'$.idempotency_key')=?",
            (scope, scope_id, kind, idempotency_key),
        ).fetchone()
        if existing:
            stored = json.loads(existing["request_json"])
            if stored != {**request, "idempotency_key": idempotency_key}:
                raise AIConflictError("idempotency key was used with a different payload")
            return dict(existing), False
    if cache_key:
        cached = connection.execute(
            "SELECT artifact_id FROM cache_entries WHERE cache_key=? "
            "AND (expires_at IS NULL OR expires_at>?)",
            (cache_key, now()),
        ).fetchone()
        if cached:
            artifact = connection.execute(
                "SELECT run_id FROM artifacts WHERE id=?", (cached["artifact_id"],)
            ).fetchone()
            if artifact:
                return dict(
                    connection.execute(
                        "SELECT * FROM runs WHERE id=?", (artifact["run_id"],)
                    ).fetchone()
                ), False
    # Cache hits do not reserve provider capacity. New work reserves conservative
    # estimated input plus the full output cap under this IMMEDIATE transaction.
    if estimated_input_tokens > config.max_input_tokens:
        raise AIInputTooLargeError("AI input exceeds configured token limit")
    reservation = estimated_input_tokens + config.max_output_tokens
    assert_budget(connection, config, reservation)
    run_id = _uuid()
    timestamp = now()
    full_request = {**request, "idempotency_key": idempotency_key}
    connection.execute(
        """INSERT INTO runs(id,conversation_id,kind,scope,scope_id,status,request_json,
           context_snapshot_id,provider,model,prompt_version,schema_version,cache_key,max_attempts,
           reserved_tokens,estimated_input_tokens,created_at,updated_at)
           VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id,
            conversation_id,
            kind,
            scope,
            scope_id,
            json.dumps(full_request),
            snapshot_id,
            config.provider,
            config.model,
            "community-ai@1",
            schema_version,
            cache_key,
            config.max_retries + 1,
            reservation,
            estimated_input_tokens,
            timestamp,
            timestamp,
        ),
    )
    if conversation_id:
        connection.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
            (
                _uuid(),
                conversation_id,
                "user",
                request["content"],
                idempotency_key,
                run_id,
                timestamp,
            ),
        )
        connection.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (timestamp, conversation_id)
        )
    add_event(connection, run_id, "queued", {"status": "queued"})
    return dict(connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()), True


def add_event(
    connection: sqlite3.Connection,
    run_id: str,
    event_type: str,
    data: dict,
    claim_generation: int = 0,
) -> int:
    cursor = connection.execute(
        "INSERT INTO run_events(run_id,event_type,data_json,created_at,claim_generation) "
        "VALUES(?,?,?,?,?)",
        (
            run_id,
            event_type,
            json.dumps(data, separators=(",", ":")),
            now(),
            claim_generation,
        ),
    )
    return int(cursor.lastrowid)


def claim(connection: sqlite3.Connection, owner: str, lease_seconds: int) -> dict | None:
    timestamp = now()
    exhausted = connection.execute(
        "SELECT id,claim_generation FROM runs WHERE status='running' AND lease_until<? "
        "AND attempts>=max_attempts ORDER BY created_at",
        (timestamp,),
    ).fetchall()
    for expired in exhausted:
        updated = connection.execute(
            "UPDATE runs SET status='failed',lease_owner=NULL,lease_until=NULL,reserved_tokens=0,"
            "error_code='attempts_exhausted',error_message='AI run exhausted retry attempts',"
            "updated_at=?,completed_at=? WHERE id=? AND status='running' AND lease_until<? "
            "AND attempts>=max_attempts",
            (timestamp, timestamp, expired["id"], timestamp),
        )
        if updated.rowcount:
            add_event(
                connection,
                expired["id"],
                "failed",
                {"code": "attempts_exhausted"},
                expired["claim_generation"],
            )
    row = connection.execute(
        """SELECT * FROM runs WHERE cancel_requested=0 AND attempts < max_attempts AND
           (status='queued' OR (status='running' AND lease_until<?)) ORDER BY created_at LIMIT 1""",
        (timestamp,),
    ).fetchone()
    if not row:
        return None
    lease = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
    updated = connection.execute(
        """UPDATE runs SET status='running',lease_owner=?,lease_until=?,attempts=attempts+1,
           claim_generation=claim_generation+1,updated_at=?
           WHERE id=? AND (status='queued' OR (status='running' AND lease_until<?))""",
        (owner, lease, timestamp, row["id"], timestamp),
    )
    if not updated.rowcount:
        return None
    claimed = dict(connection.execute("SELECT * FROM runs WHERE id=?", (row["id"],)).fetchone())
    # Failed-attempt deltas must never be concatenated with the retry output.
    connection.execute(
        "DELETE FROM run_events WHERE run_id=? AND event_type='text'",
        (row["id"],),
    )
    add_event(
        connection,
        row["id"],
        "started",
        {"attempt": claimed["attempts"]},
        claimed["claim_generation"],
    )
    return claimed


def request_cancel(connection: sqlite3.Connection, run_id: str) -> dict | None:
    """Atomically cancel queued work or flag running work; terminal calls are idempotent."""
    row = connection.execute(
        "SELECT status,cancel_requested,claim_generation FROM runs WHERE id=?", (run_id,)
    ).fetchone()
    if not row:
        return None
    timestamp = now()
    if row["status"] == "queued":
        updated = connection.execute(
            "UPDATE runs SET status='cancelled',cancel_requested=1,reserved_tokens=0,"
            "lease_owner=NULL,lease_until=NULL,updated_at=?,completed_at=? "
            "WHERE id=? AND status='queued'",
            (timestamp, timestamp, run_id),
        )
        if updated.rowcount:
            add_event(
                connection,
                run_id,
                "cancelled",
                {"status": "cancelled"},
                row["claim_generation"],
            )
    elif row["status"] == "running" and not row["cancel_requested"]:
        connection.execute(
            "UPDATE runs SET cancel_requested=1,updated_at=? WHERE id=? AND status='running'",
            (timestamp, run_id),
        )
    return dict(connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def renew_lease(
    connection: sqlite3.Connection,
    run_id: str,
    owner: str,
    generation: int,
    lease_seconds: int,
) -> bool:
    lease = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
    updated = connection.execute(
        "UPDATE runs SET lease_until=?,updated_at=? WHERE id=? AND status='running' "
        "AND lease_owner=? AND claim_generation=?",
        (lease, now(), run_id, owner, generation),
    )
    return bool(updated.rowcount)
