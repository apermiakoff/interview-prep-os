from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import connect, database_path, transaction
from app.repository import bootstrap
from app.scheduler import MemoryInput, schedule
from app.schemas import AttemptCreate, HintCreate, QueueBulkUpdate

MOSCOW = ZoneInfo("Europe/Moscow")
HINT_RANK = {"H1": 1, "H2": 2, "H3": 3, "H4": 4}


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


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


def reveal_hint(payload: HintCreate, path: Path | None = None) -> dict:
    db_path = path or database_path()
    legacy = _legacy_paths() if path is None else None
    if legacy:
        with connect(db_path) as connection:
            assignment = _assignment(connection, payload.assignment_id)
            hints = json.loads(assignment["hints_json"] or "{}")
            text = hints.get(payload.level)
        if not text:
            raise NotFoundError("hint content is unavailable")
        _run_legacy_action(payload.level.lower(), legacy)
        _sync_legacy(db_path, legacy)
        return {"level": payload.level, "text": text, "highest_hint": payload.level}

    with transaction(db_path) as connection:
        assignment = _assignment(connection, payload.assignment_id)
        current = assignment["highest_hint"]
        if not current or HINT_RANK[payload.level] > HINT_RANK.get(current, 0):
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
        hints = json.loads(assignment["hints_json"] or "{}")
        text = hints.get(payload.level)
        if not text:
            raise NotFoundError("hint content is unavailable")
        return {"level": payload.level, "text": text, "highest_hint": payload.level}


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


def _record_attempt_legacy(
    payload: AttemptCreate,
    db_path: Path,
    legacy: tuple[Path, Path, Path, Path],
) -> dict:
    request_id = payload.event_id or str(uuid.uuid4())
    with transaction(db_path) as connection:
        existing = connection.execute(
            "SELECT status FROM request_log WHERE request_id=?", (request_id,)
        ).fetchone()
        if existing:
            return bootstrap(connection)
        connection.execute(
            "INSERT INTO request_log(request_id, status, created_at) VALUES(?, 'pending', ?)",
            (request_id, _now().isoformat()),
        )

    extra = [
        "--accepted" if payload.accepted else "--no-accepted",
        "--independent" if payload.independent else "--no-independent",
        "--failure-tag",
        payload.failure_tag,
    ]
    if payload.duration_minutes is not None:
        extra.extend(["--duration-minutes", str(payload.duration_minutes)])
    if payload.explanation_score is not None:
        extra.extend(["--explanation-score", str(payload.explanation_score)])
    action = {"green": "g", "yellow": "y", "red": "r", "skipped": "skip"}[payload.result]
    try:
        _run_legacy_action(action, legacy, extra)
        _sync_legacy(db_path, legacy)
    except Exception:
        with transaction(db_path) as connection:
            connection.execute("DELETE FROM request_log WHERE request_id=?", (request_id,))
        raise

    with transaction(db_path) as connection:
        connection.execute(
            "UPDATE request_log SET status='completed' WHERE request_id=?", (request_id,)
        )
        return bootstrap(connection)


def record_attempt(payload: AttemptCreate, path: Path | None = None) -> dict:
    db_path = path or database_path()
    legacy = _legacy_paths() if path is None else None
    if legacy:
        return _record_attempt_legacy(payload, db_path, legacy)

    with transaction(db_path) as connection:
        assignment = _assignment(connection, payload.assignment_id)
        event_id = payload.event_id or str(uuid.uuid4())
        existing = connection.execute(
            "SELECT id FROM attempt_events WHERE id = ?", (event_id,)
        ).fetchone()
        if existing:
            return bootstrap(connection)

        highest_hint = assignment["highest_hint"]
        result = payload.result
        independent = payload.independent
        accepted = payload.accepted
        if result == "green" and highest_hint:
            result = "yellow"
            independent = False
        if result != "green":
            independent = False
        if result == "skipped":
            accepted = False

        now = _now()
        today = now.date()
        connection.execute(
            """
            INSERT INTO attempt_events(
              id, problem_id, assignment_id, occurred_on, result, accepted, independent,
              duration_minutes, highest_hint, failure_tag, explanation_score, source,
              raw_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                assignment["problem_id"],
                assignment["id"],
                today.isoformat(),
                result,
                int(accepted),
                int(independent),
                payload.duration_minutes,
                highest_hint,
                payload.failure_tag,
                payload.explanation_score,
                "web",
                payload.model_dump_json(),
                now.isoformat(),
            ),
        )

        if result == "skipped":
            connection.execute(
                "UPDATE assignments SET status='carryover', assigned_on=? WHERE id=?",
                ((today + timedelta(days=1)).isoformat(), assignment["id"]),
            )
            return bootstrap(connection)

        previous = connection.execute(
            "SELECT * FROM memory_states WHERE problem_id = ?",
            (assignment["problem_id"],),
        ).fetchone()
        memory = schedule(
            MemoryInput(
                result=result,
                accepted=accepted,
                independent=independent,
                highest_hint=highest_hint,
                occurred_on=today,
                previous_stability=previous["stability_days"] if previous else None,
                previous_difficulty=previous["difficulty"] if previous else None,
                previous_attempt_on=date.fromisoformat(previous["last_attempt_on"])
                if previous
                else None,
                evidence_count=previous["evidence_count"] if previous else 0,
            )
        )
        connection.execute(
            """
            INSERT INTO memory_states(
              problem_id, stability_days, difficulty, retrievability, evidence_count,
              last_attempt_on, next_due, last_result
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(problem_id) DO UPDATE SET
              stability_days=excluded.stability_days,
              difficulty=excluded.difficulty,
              retrievability=excluded.retrievability,
              evidence_count=excluded.evidence_count,
              last_attempt_on=excluded.last_attempt_on,
              next_due=excluded.next_due,
              last_result=excluded.last_result
            """,
            (
                assignment["problem_id"],
                memory.stability_days,
                memory.difficulty,
                memory.retrievability,
                memory.evidence_count,
                today.isoformat(),
                memory.next_due.isoformat(),
                result,
            ),
        )
        review_id = f"adaptive:{assignment['problem_id']}"
        connection.execute(
            """
            INSERT INTO reviews(id, problem_id, due_on, status, stage, source_attempt_id)
            VALUES(?, ?, ?, 'pending', 'Adaptive retrieval', ?)
            ON CONFLICT(id) DO UPDATE SET
              due_on=excluded.due_on,
              status='pending',
              stage=excluded.stage,
              source_attempt_id=excluded.source_attempt_id,
              completed_at=NULL
            """,
            (review_id, assignment["problem_id"], memory.next_due.isoformat(), event_id),
        )

        if result == "green" and independent:
            connection.execute(
                "UPDATE assignments SET status='completed', completed_at=? WHERE id=?",
                (now.isoformat(), assignment["id"]),
            )
        else:
            connection.execute(
                """
                UPDATE assignments
                SET status='carryover',
                    assigned_on=?,
                    mode='blind reconstruction retry',
                    highest_hint=NULL
                WHERE id=?
                """,
                (memory.next_due.isoformat(), assignment["id"]),
            )
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
