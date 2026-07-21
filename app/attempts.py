"""Shared attempt-evidence service.

One code path turns a reported outcome into immutable evidence, whether it came
from the legacy assignment endpoint or a practice session (scheduled or ad hoc):

- any revealed hint normalizes a Green report to Yellow and clears independence;
- non-green results are never independent; skipped is never accepted;
- skipped attempts create no memory penalty and no review obligation;
- non-skipped attempts update the memory model and the adaptive review;
- a reported failure tag is inserted as a structured attempt_errors row
  (provenance 'reported') so the learner model sees it without a restart.

Assignment transitions stay separate (`apply_assignment_transition`) because only
scheduled work may ever touch an assignment row: ad hoc sessions record evidence
through `record_attempt_evidence` alone and must leave assignments byte-for-byte
unchanged.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.db import FAILURE_TAG_TO_ERROR
from app.errors import ConflictError
from app.scheduler import MemoryInput, schedule


@dataclass(frozen=True)
class AttemptOutcome:
    event_id: str
    result: str
    accepted: bool
    independent: bool
    duplicate: bool
    next_due: str | None


def _same_json(stored: str | None, submitted: str) -> bool:
    try:
        return json.loads(stored or "{}") == json.loads(submitted)
    except json.JSONDecodeError:
        return False


def require_same_attempt(
    existing: sqlite3.Row,
    *,
    problem_id: int,
    assignment_id: str | None,
    session_id: str | None,
    raw_json: str,
) -> None:
    """An attempt event id may be replayed only for the operation that created it.

    A retry of the identical operation (same problem, same execution context,
    byte-equivalent submitted facts) is idempotent; any other reuse is a
    deterministic conflict — never a silent success against unrelated evidence.
    """
    if (
        existing["problem_id"] != problem_id
        or existing["assignment_id"] != assignment_id
        or existing["session_id"] != session_id
    ):
        raise ConflictError("attempt event id is already bound to a different attempt")
    if not _same_json(existing["raw_json"], raw_json):
        raise ConflictError("attempt event id was already recorded with different facts")


def record_attempt_evidence(
    connection: sqlite3.Connection,
    *,
    problem_id: int,
    event_id: str,
    result: str,
    accepted: bool,
    independent: bool,
    highest_hint: str | None,
    duration_minutes: int | None,
    failure_tag: str,
    explanation_score: float | None,
    assignment_id: str | None,
    session_id: str | None,
    source: str,
    raw_json: str,
    now: datetime,
) -> AttemptOutcome:
    """Insert one immutable attempt event plus its derived memory/review updates.

    Idempotent on event_id: a duplicate returns without writing anything.
    Never touches the assignments table.
    """
    existing = connection.execute(
        "SELECT * FROM attempt_events WHERE id = ?", (event_id,)
    ).fetchone()
    if existing is not None:
        require_same_attempt(
            existing,
            problem_id=problem_id,
            assignment_id=assignment_id,
            session_id=session_id,
            raw_json=raw_json,
        )
        return AttemptOutcome(
            event_id=event_id,
            result=existing["result"],
            accepted=bool(existing["accepted"]),
            independent=bool(existing["independent"]),
            duplicate=True,
            next_due=None,
        )

    if result == "green" and highest_hint:
        result = "yellow"
        independent = False
    if result != "green":
        independent = False
    if result == "skipped":
        # A skip is a scheduling decision, not evidence of a failure mode: it
        # must never seed attempt_errors or downstream trap diagnoses.
        accepted = False
        failure_tag = "unspecified"

    today = now.date()
    connection.execute(
        """
        INSERT INTO attempt_events(
          id, problem_id, assignment_id, session_id, occurred_on, result, accepted,
          independent, duration_minutes, highest_hint, failure_tag, explanation_score,
          source, raw_json, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            problem_id,
            assignment_id,
            session_id,
            today.isoformat(),
            result,
            int(accepted),
            int(independent),
            duration_minutes,
            highest_hint,
            failure_tag,
            explanation_score,
            source,
            raw_json,
            now.isoformat(),
        ),
    )

    error_type = FAILURE_TAG_TO_ERROR.get(failure_tag) if result != "skipped" else None
    if error_type is not None:
        connection.execute(
            """
            INSERT OR IGNORE INTO attempt_errors(
              attempt_id, error_type_id, detail, provenance, created_at
            ) VALUES(?, ?, 'reported with the attempt', 'reported', ?)
            """,
            (event_id, error_type, now.isoformat()),
        )

    if result == "skipped":
        return AttemptOutcome(
            event_id=event_id,
            result=result,
            accepted=accepted,
            independent=independent,
            duplicate=False,
            next_due=None,
        )

    previous = connection.execute(
        "SELECT * FROM memory_states WHERE problem_id = ?", (problem_id,)
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
            problem_id,
            memory.stability_days,
            memory.difficulty,
            memory.retrievability,
            memory.evidence_count,
            today.isoformat(),
            memory.next_due.isoformat(),
            result,
        ),
    )
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
        (f"adaptive:{problem_id}", problem_id, memory.next_due.isoformat(), event_id),
    )
    return AttemptOutcome(
        event_id=event_id,
        result=result,
        accepted=accepted,
        independent=independent,
        duplicate=False,
        next_due=memory.next_due.isoformat(),
    )


def apply_assignment_transition(
    connection: sqlite3.Connection,
    assignment_id: str,
    outcome: AttemptOutcome,
    now: datetime,
) -> None:
    """The scheduled-only state machine, exactly as the original endpoint had it:
    skip carries over to tomorrow; independent green completes; anything else
    becomes a blind reconstruction retry due with the memory model."""
    if outcome.duplicate:
        return
    today = now.date()
    if outcome.result == "skipped":
        connection.execute(
            "UPDATE assignments SET status='carryover', assigned_on=? WHERE id=?",
            ((today + timedelta(days=1)).isoformat(), assignment_id),
        )
    elif outcome.result == "green" and outcome.independent:
        connection.execute(
            "UPDATE assignments SET status='completed', completed_at=? WHERE id=?",
            (now.isoformat(), assignment_id),
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
            (outcome.next_due, assignment_id),
        )
