from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.attempts import apply_assignment_transition, record_attempt_evidence
from app.content import HINT_LEVELS
from app.db import database_path, transaction
from app.errors import ConflictError, NotFoundError
from app.repository import bootstrap
from app.schemas import AttemptCreate, HintCreate, QueueBulkUpdate

MOSCOW = ZoneInfo("Europe/Moscow")
HINT_RANK = {"H1": 1, "H2": 2, "H3": 3, "H4": 4}

# A 'pending' claim younger than this is an in-flight duplicate and conflicts;
# an older one is debris from a crashed request and may be re-claimed. Both
# subprocess calls time out at 15s, so no live request holds 'pending' longer.
CLAIM_STALE_SECONDS = 60

__all__ = [
    "ConflictError",
    "NotFoundError",
    "record_attempt",
    "reveal_hint",
    "save_notes",
    "update_queue",
]


def _now() -> datetime:
    return datetime.now(MOSCOW)


def _legacy_paths() -> tuple[Path, Path, Path, Path] | None:
    values = [
        os.getenv("INTERVIEW_PREP_LEGACY_STATE"),
        os.getenv("INTERVIEW_PREP_LEGACY_EVENTS"),
        os.getenv("INTERVIEW_PREP_LEGACY_PROFILE"),
        os.getenv("INTERVIEW_PREP_LEGACY_ACTION"),
    ]
    state, events, profile, action = values
    if not state or not events or not profile or not action:
        return None
    paths = (Path(state), Path(events), Path(profile), Path(action))
    return paths if all(path.exists() for path in paths) else None


def _sync_legacy(db_path: Path, paths: tuple[Path, Path, Path, Path]) -> None:
    state, events, profile, _ = paths
    importer = Path(__file__).resolve().parents[1] / "scripts" / "import_legacy.py"
    command = [
        sys.executable,
        str(importer),
        "--state",
        str(state),
        "--events",
        str(events),
        "--profile",
        str(profile),
    ]
    plan = os.getenv("INTERVIEW_PREP_LEGACY_PLAN")
    if plan and Path(plan).exists():
        command.extend(["--plan", plan])
    command.extend(["--db", str(db_path)])
    completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if completed.returncode != 0:
        raise ConflictError(completed.stderr.strip() or "legacy tracker synchronization failed")


def _run_legacy_action(
    action: str,
    paths: tuple[Path, Path, Path, Path],
    extra: list[str] | None = None,
) -> None:
    state, events, _, action_script = paths
    command = [
        sys.executable,
        str(action_script),
        action,
        "--state",
        str(state),
        "--events",
        str(events),
        "--source",
        "web",
        *(extra or []),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if completed.returncode != 0:
        raise ConflictError(
            completed.stderr.strip() or completed.stdout.strip() or "tracker update failed"
        )


def _assignment(connection: sqlite3.Connection, assignment_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise NotFoundError("assignment not found")
    if row["status"] not in {"active", "carryover"}:
        raise ConflictError("assignment is already completed")
    return row


def _claim_age_seconds(reference: str | None, now: datetime) -> float:
    if not reference:
        return float("inf")
    try:
        stamp = datetime.fromisoformat(reference)
    except ValueError:
        return float("inf")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=MOSCOW)
    return (now - stamp).total_seconds()


def begin_claim(
    connection: sqlite3.Connection,
    request_id: str,
    scope: str,
    fingerprint: str,
    now: datetime,
) -> str:
    """Claim one legacy-bridge operation under the caller's write transaction.

    Returns the phase this request must perform next: ``"action"`` (run the
    legacy action, then sync), ``"sync"`` (the action already succeeded — never
    run it again), or ``"done"`` (fully recorded; answer idempotently).

    Ownership: a claim is bound to (scope, fingerprint). Reusing the same
    request id for a different operation or with different facts is a
    deterministic conflict. Rows written before these columns existed carry
    NULL ownership and are rejected: safely replaying an unscoped external
    operation is impossible, and silently treating it as this attempt would
    close a session without evidence.

    Concurrency: a fresh 'pending' claim means another request is mid-flight —
    conflict rather than double-invoke. A 'pending' claim older than
    CLAIM_STALE_SECONDS is debris from a crash *around* the legacy action; it is
    re-claimed and the action re-run, converging toward recording (a rare
    duplicate in the append-only legacy log is visible and correctable; a
    silently swallowed attempt is not).
    """
    now_iso = now.isoformat()
    row = connection.execute(
        "SELECT status, scope, fingerprint, created_at, updated_at FROM request_log "
        "WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO request_log(request_id, status, created_at, scope, fingerprint, "
            "updated_at) VALUES(?, 'pending', ?, ?, ?, ?)",
            (request_id, now_iso, scope, fingerprint, now_iso),
        )
        return "action"
    if row["scope"] is None or row["fingerprint"] is None:
        raise ConflictError("request id belongs to a pre-upgrade operation and cannot be reused")
    if row["scope"] != scope or row["fingerprint"] != fingerprint:
        raise ConflictError("request id is already bound to a different operation")
    if row["status"] == "completed":
        return "done"
    if row["status"] == "action_done":
        return "sync"
    if _claim_age_seconds(row["updated_at"] or row["created_at"], now) < CLAIM_STALE_SECONDS:
        raise ConflictError("this operation is still being recorded — retry in a moment")
    connection.execute(
        "UPDATE request_log SET updated_at = ?, scope = ?, fingerprint = ? WHERE request_id = ?",
        (now_iso, scope, fingerprint, request_id),
    )
    return "action"


def _set_claim_status(db_path: Path, request_id: str, status: str) -> None:
    with transaction(db_path) as connection:
        connection.execute(
            "UPDATE request_log SET status = ?, updated_at = ? WHERE request_id = ?",
            (status, _now().isoformat(), request_id),
        )


def _drop_claim(db_path: Path, request_id: str) -> None:
    with transaction(db_path) as connection:
        connection.execute("DELETE FROM request_log WHERE request_id = ?", (request_id,))


def run_claimed_legacy_step(
    db_path: Path,
    legacy: tuple[Path, Path, Path, Path],
    request_id: str,
    phase: str,
    action: str,
    extra: list[str] | None = None,
) -> None:
    """Run action+sync for a claimed operation, keeping the claim honest.

    Action failure deletes the claim (nothing durable happened; a retry starts
    over). Once the action succeeds the claim is marked 'action_done' before the
    sync runs, so a sync failure leaves a durable instruction to sync-only —
    the legacy action is never executed twice for one claim.
    """
    if phase == "action":
        try:
            _run_legacy_action(action, legacy, extra)
        except Exception:
            _drop_claim(db_path, request_id)
            raise
        _set_claim_status(db_path, request_id, "action_done")
    _sync_legacy(db_path, legacy)


def _sequential_rank(current_hint: str | None, level: str) -> tuple[int, bool]:
    """Rank of the requested level plus whether it is the next new reveal.

    Raises ConflictError when the request skips ahead of the recorded ladder —
    hints unlock strictly in H1→H4 order on every endpoint.
    """
    rank = HINT_RANK[level]
    consumed = HINT_RANK.get(current_hint or "", 0)
    if rank > consumed + 1:
        raise ConflictError(f"hints unlock in order — reveal {HINT_LEVELS[consumed]} first")
    return rank, rank == consumed + 1


def reveal_hint(payload: HintCreate, path: Path | None = None) -> dict:
    db_path = path or database_path()
    legacy = _legacy_paths() if path is None else None
    if legacy:
        claim_id = f"assignment-hint:{payload.assignment_id}:{payload.level}"
        with transaction(db_path) as connection:
            assignment = _assignment(connection, payload.assignment_id)
            hints = json.loads(assignment["hints_json"] or "{}")
            text = hints.get(payload.level)
            if not text:
                raise NotFoundError("hint content is unavailable")
            _, is_new = _sequential_rank(assignment["highest_hint"], payload.level)
            phase = "done"
            if is_new:
                phase = begin_claim(
                    connection,
                    claim_id,
                    f"assignment-hint:{payload.assignment_id}",
                    payload.level,
                    _now(),
                )
        if is_new and phase != "done":
            run_claimed_legacy_step(db_path, legacy, claim_id, phase, payload.level.lower())
            _set_claim_status(db_path, claim_id, "completed")
        highest = payload.level if is_new else assignment["highest_hint"]
        return {"level": payload.level, "text": text, "highest_hint": highest}

    with transaction(db_path) as connection:
        assignment = _assignment(connection, payload.assignment_id)
        hints = json.loads(assignment["hints_json"] or "{}")
        text = hints.get(payload.level)
        if not text:
            raise NotFoundError("hint content is unavailable")
        _, is_new = _sequential_rank(assignment["highest_hint"], payload.level)
        if is_new:
            connection.execute(
                "UPDATE assignments SET highest_hint = ? WHERE id = ?",
                (payload.level, payload.assignment_id),
            )
            event_id = f"hint:{payload.assignment_id}:{payload.level}"
            connection.execute(
                """
                INSERT OR IGNORE INTO hint_events(id, assignment_id, level, occurred_at)
                VALUES(?, ?, ?, ?)
                """,
                (event_id, payload.assignment_id, payload.level, _now().isoformat()),
            )
        highest = payload.level if is_new else assignment["highest_hint"]
        return {"level": payload.level, "text": text, "highest_hint": highest}


def save_notes(assignment_id: str, content: str, path: Path | None = None) -> dict:
    with transaction(path or database_path()) as connection:
        _assignment(connection, assignment_id)
        connection.execute(
            """
            INSERT INTO notes(assignment_id, content, updated_at) VALUES(?, ?, ?)
            ON CONFLICT(assignment_id) DO UPDATE SET
              content=excluded.content,
              updated_at=excluded.updated_at
            """,
            (assignment_id, content, _now().isoformat()),
        )
    return {"assignment_id": assignment_id, "saved": True}


def attempt_fingerprint(payload: AttemptCreate) -> str:
    """Canonical serialization of the facts a client submitted for one attempt.
    The event id is the claim key itself, so it stays out of the fingerprint."""
    return json.dumps(payload.model_dump(exclude={"event_id"}), sort_keys=True, ensure_ascii=False)


def _record_attempt_legacy(
    payload: AttemptCreate,
    db_path: Path,
    legacy: tuple[Path, Path, Path, Path],
    claim_scope: str | None = None,
) -> dict:
    request_id = payload.event_id or str(uuid.uuid4())
    scope = claim_scope or f"assignment-attempt:{payload.assignment_id}"
    with transaction(db_path) as connection:
        phase = begin_claim(connection, request_id, scope, attempt_fingerprint(payload), _now())
        if phase == "done":
            return bootstrap(connection)

    # A skip reports no failure mode; never send a blocker tag to the tracker.
    failure_tag = "unspecified" if payload.result == "skipped" else payload.failure_tag
    extra = [
        "--accepted" if payload.accepted else "--no-accepted",
        "--independent" if payload.independent else "--no-independent",
        "--failure-tag",
        failure_tag,
    ]
    if payload.duration_minutes is not None:
        extra.extend(["--duration-minutes", str(payload.duration_minutes)])
    if payload.explanation_score is not None:
        extra.extend(["--explanation-score", str(payload.explanation_score)])
    action = {"green": "g", "yellow": "y", "red": "r", "skipped": "skip"}[payload.result]
    run_claimed_legacy_step(db_path, legacy, request_id, phase, action, extra)

    with transaction(db_path) as connection:
        connection.execute(
            "UPDATE request_log SET status='completed', updated_at=? WHERE request_id=?",
            (_now().isoformat(), request_id),
        )
        return bootstrap(connection)


def record_attempt(
    payload: AttemptCreate, path: Path | None = None, claim_scope: str | None = None
) -> dict:
    db_path = path or database_path()
    legacy = _legacy_paths() if path is None else None
    if legacy:
        return _record_attempt_legacy(payload, db_path, legacy, claim_scope=claim_scope)

    with transaction(db_path) as connection:
        assignment = _assignment(connection, payload.assignment_id)
        now = _now()
        outcome = record_attempt_evidence(
            connection,
            problem_id=assignment["problem_id"],
            event_id=payload.event_id or str(uuid.uuid4()),
            result=payload.result,
            accepted=payload.accepted,
            independent=payload.independent,
            highest_hint=assignment["highest_hint"],
            duration_minutes=payload.duration_minutes,
            failure_tag=payload.failure_tag,
            explanation_score=payload.explanation_score,
            assignment_id=assignment["id"],
            session_id=None,
            source="web",
            raw_json=payload.model_dump_json(),
            now=now,
        )
        apply_assignment_transition(connection, assignment["id"], outcome, now)
        return bootstrap(connection)


def update_queue(payload: QueueBulkUpdate, path: Path | None = None) -> dict:
    now = _now().isoformat()
    updated = 0
    with transaction(path or database_path()) as connection:
        for problem_id in dict.fromkeys(payload.problem_ids):
            exists = connection.execute(
                "SELECT 1 FROM problems WHERE id = ?", (problem_id,)
            ).fetchone()
            if exists is None:
                continue
            connection.execute(
                """
                INSERT INTO queue_items(
                  problem_id, state, priority, source, created_at, updated_at
                ) VALUES(?, ?, 500, 'manual', ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  state=excluded.state,
                  updated_at=excluded.updated_at
                """,
                (problem_id, payload.state, now, now),
            )
            updated += 1
    return {"updated": updated, "state": payload.state}
