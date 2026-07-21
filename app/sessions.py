"""Practice sessions: the execution context between a problem and its evidence.

Three entities stay distinct:

- a *scheduled assignment* is the formal daily commitment (assignments table);
- a *practice session* is one sitting at a problem — origin ``scheduled`` when it
  executes an assignment, ``ad_hoc`` when the learner just wants extra practice;
- an *attempt event* is the immutable evidence a session produces.

Ad hoc sessions may create attempt/memory/review evidence, but they never touch
an assignment row, never call the legacy coach subprocess, and never claim the
daily assignment was completed. Scheduled sessions transition their assignment
exactly as the original endpoint did (including the legacy bridge when that
environment is configured).

Hint policy: a session reveals hints strictly in order H1→H4; each reveal is
recorded idempotently and returns exactly one body. Unrevealed bodies are never
included in any GET payload.

Idempotency contract: a start request id and an attempt event id are bound to
the operation that first used them. Replaying the identical operation returns
the original session / the canonical recorded outcome; reusing the id for a
different problem, origin, session, or payload is a deterministic 409.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.attempts import (
    AttemptOutcome,
    apply_assignment_transition,
    record_attempt_evidence,
    require_same_attempt,
)
from app.content import HINT_LEVELS, hint_ladder, resolve_problem_content
from app.db import connect, database_path, transaction
from app.errors import ConflictError, NotFoundError
from app.repository import bootstrap
from app.schemas import SessionAttemptCreate, SessionStart
from app.services import (
    HINT_RANK,
    _assignment,
    _legacy_paths,
    _now,
    _sequential_rank,
    begin_claim,
    run_claimed_legacy_step,
)

DEFAULT_TIMEBOX = {"Easy": 20, "Medium": 35, "Hard": 50}
AD_HOC_MODE = "paper practice"
AD_HOC_GOAL = "Extra practice. Read on LeetCode, reason on paper, implement there."

LEGACY_ATTEMPT_ACTION = {"green": "g", "yellow": "y", "red": "r", "skipped": "skip"}


def _session_row(connection: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM practice_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("practice session not found")
    return row


def _assignment_hints(connection: sqlite3.Connection, assignment_id: str) -> dict[str, str]:
    row = connection.execute(
        "SELECT hints_json FROM assignments WHERE id = ?", (assignment_id,)
    ).fetchone()
    if row is None or not row["hints_json"]:
        return {}
    try:
        hints = json.loads(row["hints_json"])
    except json.JSONDecodeError:
        return {}
    return {level: text for level, text in hints.items() if level in HINT_LEVELS and text}


def _hint_source(
    connection: sqlite3.Connection, session: sqlite3.Row
) -> tuple[dict[str, str], dict]:
    """Bodies + resolution metadata for this session's hint ladder.

    A scheduled session with authored assignment hints uses those (curated,
    problem scope); everything else resolves through the deterministic content
    resolver, which itself prefers curated pattern content over the generated
    scaffold.
    """
    if session["origin"] == "scheduled":
        authored = _assignment_hints(connection, session["assignment_id"])
        if authored:
            return authored, {
                "availability": "available",
                "provenance": "curated",
                "scope": "problem",
                "generator": None,
                "label": "Authored assignment hints",
            }
    bodies = hint_ladder(connection, session["problem_id"]) or {}
    resolution = resolve_problem_content(connection, session["problem_id"])
    meta = (
        resolution["hints"]
        if resolution
        else {
            "availability": "unavailable",
            "provenance": "unavailable",
            "scope": None,
            "generator": None,
            "label": "No hint content",
        }
    )
    return bodies, meta


def session_envelope(connection: sqlite3.Connection, session_id: str) -> dict:
    """Session + problem + instructional availability. Never leaks a hint body
    beyond what the recorded assistance level already covers."""
    session = _session_row(connection, session_id)
    problem = connection.execute(
        """
        SELECT p.id, p.leetcode_id, p.slug, p.title, p.url, p.difficulty, p.pattern_id,
               pt.title AS pattern_title
        FROM problems p LEFT JOIN patterns pt ON pt.id = p.pattern_id
        WHERE p.id = ?
        """,
        (session["problem_id"],),
    ).fetchone()
    scheduled = None
    if session["assignment_id"]:
        assignment = connection.execute(
            "SELECT id, assigned_on, status, mode FROM assignments WHERE id = ?",
            (session["assignment_id"],),
        ).fetchone()
        if assignment is not None:
            scheduled = dict(assignment)

    bodies, meta = _hint_source(connection, session)
    consumed = HINT_RANK.get(session["highest_hint"], 0)
    levels = []
    for index, level in enumerate(HINT_LEVELS, start=1):
        if index <= consumed:
            state = "revealed"
        elif index == consumed + 1:
            state = "next"
        else:
            state = "locked"
        entry: dict = {"level": level, "state": state, "available": level in bodies}
        if state == "revealed" and level in bodies:
            entry["body"] = bodies[level]
        levels.append(entry)

    resolution = resolve_problem_content(connection, session["problem_id"])
    return {
        "session": dict(session),
        "problem": dict(problem) if problem else None,
        "scheduled": scheduled,
        "hints": {**meta, "levels": levels},
        "lesson": resolution["lesson"]
        if resolution
        else {
            "availability": "unavailable",
            "provenance": "unavailable",
            "scope": None,
            "generator": None,
            "label": "No lesson content",
        },
    }


def get_session(session_id: str, path: Path | None = None) -> dict:
    with connect(path or database_path()) as connection:
        return session_envelope(connection, session_id)


def start_ad_hoc_session(problem_id: int, payload: SessionStart, path: Path | None = None) -> dict:
    """Start (or idempotently continue) an ad hoc paper session for any problem.
    Never inspects, creates, or modifies a scheduled assignment."""
    db_path = path or database_path()
    with transaction(db_path) as connection:
        problem = connection.execute(
            "SELECT id, difficulty FROM problems WHERE id = ?", (problem_id,)
        ).fetchone()
        if problem is None:
            raise NotFoundError("problem not found")

        if payload.request_id:
            existing = connection.execute(
                "SELECT id, problem_id, origin FROM practice_sessions WHERE request_id = ?",
                (payload.request_id,),
            ).fetchone()
            if existing is not None:
                # The request id belongs to the operation that minted it: only a
                # retry of this exact ad hoc start may continue that session.
                if existing["origin"] != "ad_hoc" or existing["problem_id"] != problem_id:
                    raise ConflictError(
                        "request id was already used to start a different practice session"
                    )
                return {**session_envelope(connection, existing["id"]), "created": False}

        open_session = connection.execute(
            """
            SELECT id FROM practice_sessions
            WHERE problem_id = ? AND origin = 'ad_hoc' AND status = 'active'
            ORDER BY started_at DESC LIMIT 1
            """,
            (problem_id,),
        ).fetchone()
        if open_session is not None:
            return {**session_envelope(connection, open_session["id"]), "created": False}

        now = _now().isoformat()
        session_id = f"ps-{uuid.uuid4()}"
        timebox = payload.timebox_minutes or DEFAULT_TIMEBOX.get(problem["difficulty"] or "", 35)
        connection.execute(
            """
            INSERT INTO practice_sessions(
              id, problem_id, assignment_id, origin, status, mode, goal, timebox_minutes,
              highest_hint, request_id, started_at, updated_at
            ) VALUES(?, ?, NULL, 'ad_hoc', 'active', ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                session_id,
                problem_id,
                AD_HOC_MODE,
                payload.goal or AD_HOC_GOAL,
                timebox,
                payload.request_id,
                now,
                now,
            ),
        )
        return {**session_envelope(connection, session_id), "created": True}


def start_scheduled_session(
    assignment_id: str, payload: SessionStart, path: Path | None = None
) -> dict:
    """Start or continue the session that executes a scheduled assignment."""
    db_path = path or database_path()
    with transaction(db_path) as connection:
        if payload.request_id:
            existing = connection.execute(
                "SELECT id, assignment_id, origin FROM practice_sessions WHERE request_id = ?",
                (payload.request_id,),
            ).fetchone()
            if existing is not None:
                # Checked before assignment state on purpose: a retry of the
                # start that created this session must return it even if the
                # assignment has completed since. Any other reuse conflicts.
                if existing["origin"] != "scheduled" or existing["assignment_id"] != assignment_id:
                    raise ConflictError(
                        "request id was already used to start a different practice session"
                    )
                return {**session_envelope(connection, existing["id"]), "created": False}

        assignment = _assignment(connection, assignment_id)

        open_session = connection.execute(
            """
            SELECT id, highest_hint FROM practice_sessions
            WHERE assignment_id = ? AND status = 'active'
            ORDER BY started_at DESC LIMIT 1
            """,
            (assignment_id,),
        ).fetchone()
        if open_session is not None:
            # The assignment may have received hints through the compatibility
            # endpoint; the session must not under-report recorded assistance.
            assignment_rank = HINT_RANK.get(assignment["highest_hint"], 0)
            if assignment_rank > HINT_RANK.get(open_session["highest_hint"], 0):
                connection.execute(
                    "UPDATE practice_sessions SET highest_hint = ?, updated_at = ? WHERE id = ?",
                    (assignment["highest_hint"], _now().isoformat(), open_session["id"]),
                )
            return {**session_envelope(connection, open_session["id"]), "created": False}

        now = _now().isoformat()
        session_id = f"ps-{uuid.uuid4()}"
        connection.execute(
            """
            INSERT INTO practice_sessions(
              id, problem_id, assignment_id, origin, status, mode, goal, timebox_minutes,
              highest_hint, request_id, started_at, updated_at
            ) VALUES(?, ?, ?, 'scheduled', 'active', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                assignment["problem_id"],
                assignment["id"],
                assignment["mode"],
                assignment["goal"],
                assignment["timebox_minutes"],
                assignment["highest_hint"],
                payload.request_id,
                now,
                now,
            ),
        )
        return {**session_envelope(connection, session_id), "created": True}


def reveal_session_hint(session_id: str, level: str, path: Path | None = None) -> dict:
    """Reveal the next allowed hint. Sequential, idempotent, one body returned.

    In legacy mode a new reveal is claimed before the external action runs, so
    concurrent identical reveals invoke the legacy action exactly once (the
    loser conflicts and retries into the idempotent answer).
    """
    db_path = path or database_path()
    legacy = _legacy_paths() if path is None else None
    claim_id = f"session-hint:{session_id}:{level}"

    with transaction(db_path) as connection:
        session = _session_row(connection, session_id)
        if session["status"] != "active":
            raise ConflictError("practice session is not active")
        bodies, _meta = _hint_source(connection, session)
        body = bodies.get(level)
        if not body:
            raise NotFoundError("hint content is unavailable")
        _, is_new = _sequential_rank(session["highest_hint"], level)
        use_legacy = bool(legacy and session["origin"] == "scheduled" and is_new)
        if not use_legacy:
            _record_session_hint(connection, session, level, is_new, mirror_assignment=True)
            return _reveal_response(session, level, body, is_new)
        phase = begin_claim(connection, claim_id, f"session-hint:{session_id}", level, _now())

    # The external tracker records the escalation first (a failed legacy action
    # records nothing here); the claim guarantees the action runs once even
    # across a sync failure, and the sync mirrors assignment state back.
    assert legacy is not None
    if phase != "done":
        run_claimed_legacy_step(db_path, legacy, claim_id, phase, level.lower())

    with transaction(db_path) as connection:
        if phase != "done":
            connection.execute(
                "UPDATE request_log SET status='completed', updated_at=? WHERE request_id=?",
                (_now().isoformat(), claim_id),
            )
        _record_session_hint(connection, session, level, is_new, mirror_assignment=False)
    return _reveal_response(session, level, body, is_new)


def _record_session_hint(
    connection: sqlite3.Connection,
    session: sqlite3.Row,
    level: str,
    is_new: bool,
    *,
    mirror_assignment: bool,
) -> None:
    now = _now().isoformat()
    if is_new:
        connection.execute(
            "UPDATE practice_sessions SET highest_hint = ?, updated_at = ? WHERE id = ?",
            (level, now, session["id"]),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO session_hint_events(id, session_id, level, occurred_at)
        VALUES(?, ?, ?, ?)
        """,
        (f"shint:{session['id']}:{level}", session["id"], level, now),
    )
    if session["origin"] == "scheduled" and is_new and mirror_assignment:
        # Mirror recorded assistance onto the assignment exactly as the
        # compatibility endpoint does; in legacy mode the sync owns this.
        assignment = connection.execute(
            "SELECT highest_hint FROM assignments WHERE id = ?",
            (session["assignment_id"],),
        ).fetchone()
        if assignment is not None and HINT_RANK[level] > HINT_RANK.get(
            assignment["highest_hint"], 0
        ):
            connection.execute(
                "UPDATE assignments SET highest_hint = ? WHERE id = ?",
                (level, session["assignment_id"]),
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO hint_events(id, assignment_id, level, occurred_at)
            VALUES(?, ?, ?, ?)
            """,
            (f"hint:{session['assignment_id']}:{level}", session["assignment_id"], level, now),
        )


def _reveal_response(session: sqlite3.Row, level: str, body: str, is_new: bool) -> dict:
    highest = level if is_new else session["highest_hint"]
    revealed = HINT_LEVELS[: HINT_RANK.get(highest, 0)]
    return {"level": level, "body": body, "highest_hint": highest, "revealed": list(revealed)}


def abandon_session(session_id: str, path: Path | None = None) -> dict:
    """Close only the session. No attempt event, no memory change, no assignment
    change — abandoning extra practice must never look like completed work."""
    db_path = path or database_path()
    with transaction(db_path) as connection:
        session = _session_row(connection, session_id)
        if session["status"] == "completed":
            raise ConflictError("practice session already completed")
        if session["status"] == "active":
            now = _now().isoformat()
            connection.execute(
                """
                UPDATE practice_sessions
                SET status = 'abandoned', completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, session_id),
            )
        return session_envelope(connection, session_id)


def _attempt_facts(row: sqlite3.Row, *, duplicate: bool) -> dict:
    return {
        "event_id": row["id"],
        "result": row["result"],
        "accepted": bool(row["accepted"]),
        "independent": bool(row["independent"]),
        "duplicate": duplicate,
        "next_due": None,
    }


def record_session_attempt(
    session_id: str, payload: SessionAttemptCreate, path: Path | None = None
) -> dict:
    """Record immutable evidence for this session and close it.

    Scheduled sessions transition their assignment exactly as the original
    endpoint (including the legacy bridge when configured). Ad hoc sessions
    write evidence only: the assignments table is never touched and the legacy
    subprocess is never invoked.

    The response's ``attempt`` object carries the canonical recorded facts
    (post-normalization result/independence), or None on the legacy path when
    the imported row could not be identified unambiguously.
    """
    db_path = path or database_path()
    event_id = payload.event_id or str(uuid.uuid4())

    with connect(db_path) as connection:
        session = _session_row(connection, session_id)

    if session["origin"] == "scheduled":
        legacy = _legacy_paths() if path is None else None
        if legacy:
            return _record_scheduled_legacy_attempt(db_path, legacy, session_id, event_id, payload)

    # Everything — duplicate detection, ownership validation, status check, and
    # the write itself — happens under one immediate transaction, so concurrent
    # identical retries serialize and converge on the same recorded success.
    with transaction(db_path) as connection:
        session = _session_row(connection, session_id)
        existing = connection.execute(
            "SELECT * FROM attempt_events WHERE id = ?", (event_id,)
        ).fetchone()
        if existing is not None:
            require_same_attempt(
                existing,
                problem_id=session["problem_id"],
                assignment_id=session["assignment_id"],
                session_id=session_id,
                raw_json=payload.model_dump_json(),
            )
            return {
                "session": session_envelope(connection, session_id),
                "bootstrap": bootstrap(connection),
                "attempt": _attempt_facts(existing, duplicate=True),
            }
        if session["status"] != "active":
            raise ConflictError("practice session is not active")

        now = _now()
        if session["origin"] == "scheduled":
            assignment = _assignment(connection, session["assignment_id"])
            outcome = _record_evidence(
                connection,
                payload,
                event_id=event_id,
                problem_id=assignment["problem_id"],
                highest_hint=assignment["highest_hint"],
                assignment_id=assignment["id"],
                session_id=session_id,
                now=now,
            )
            apply_assignment_transition(connection, assignment["id"], outcome, now)
        else:
            outcome = _record_evidence(
                connection,
                payload,
                event_id=event_id,
                problem_id=session["problem_id"],
                highest_hint=session["highest_hint"],
                assignment_id=None,
                session_id=session_id,
                now=now,
            )
        _complete_session(connection, session_id)
        return {
            "session": session_envelope(connection, session_id),
            "bootstrap": bootstrap(connection),
            "attempt": asdict(outcome),
        }


def _record_evidence(
    connection: sqlite3.Connection,
    payload: SessionAttemptCreate,
    *,
    event_id: str,
    problem_id: int,
    highest_hint: str | None,
    assignment_id: str | None,
    session_id: str,
    now: datetime,
) -> AttemptOutcome:
    return record_attempt_evidence(
        connection,
        problem_id=problem_id,
        event_id=event_id,
        result=payload.result,
        accepted=payload.accepted,
        independent=payload.independent,
        highest_hint=highest_hint,
        duration_minutes=payload.duration_minutes,
        failure_tag=payload.failure_tag,
        explanation_score=payload.explanation_score,
        assignment_id=assignment_id,
        session_id=session_id,
        source="web",
        raw_json=payload.model_dump_json(),
        now=now,
    )


def _record_scheduled_legacy_attempt(
    db_path: Path,
    legacy: tuple[Path, Path, Path, Path],
    session_id: str,
    event_id: str,
    payload: SessionAttemptCreate,
) -> dict:
    """Delegate the outcome to the external tracker, then close the session.

    The claim binds the event id to this session and payload: the legacy action
    runs at most once per claim even across a sync failure (retry syncs only),
    and a retry of the recorded event resolves idempotently after the session
    closed. If the sync lands exactly one new attempt row for this problem, that
    canonical imported row is linked to the session; with zero or several
    candidates (e.g., a concurrent Telegram action imported alongside), linkage
    is never guessed and the evidence stays unlinked.
    """
    fingerprint = json.dumps(
        payload.model_dump(exclude={"event_id"}), sort_keys=True, ensure_ascii=False
    )
    with transaction(db_path) as connection:
        session = _session_row(connection, session_id)
        claim = connection.execute(
            "SELECT 1 FROM request_log WHERE request_id = ?", (event_id,)
        ).fetchone()
        if session["status"] != "active" and claim is None:
            raise ConflictError("practice session is not active")
        phase = begin_claim(
            connection, event_id, f"session-attempt:{session_id}", fingerprint, _now()
        )
        before = {
            row["id"]
            for row in connection.execute(
                "SELECT id FROM attempt_events WHERE problem_id = ?",
                (session["problem_id"],),
            ).fetchall()
        }

    if phase != "done":
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
        run_claimed_legacy_step(
            db_path, legacy, event_id, phase, LEGACY_ATTEMPT_ACTION[payload.result], extra
        )

    with transaction(db_path) as connection:
        if phase != "done":
            connection.execute(
                "UPDATE request_log SET status='completed', updated_at=? WHERE request_id=?",
                (_now().isoformat(), event_id),
            )
        linked = _link_imported_attempt(connection, session, before)
        _complete_session(connection, session_id)
        return {
            "session": session_envelope(connection, session_id),
            "bootstrap": bootstrap(connection),
            "attempt": _attempt_facts(linked, duplicate=phase == "done") if linked else None,
        }


def _link_imported_attempt(
    connection: sqlite3.Connection, session: sqlite3.Row, before_ids: set[str]
) -> sqlite3.Row | None:
    """Identify the canonical imported attempt row for this session, linking it
    when — and only when — the identification is unambiguous."""
    already = connection.execute(
        "SELECT * FROM attempt_events WHERE session_id = ? LIMIT 2", (session["id"],)
    ).fetchall()
    if len(already) == 1:
        return already[0]
    if already:
        return None
    candidates = [
        row
        for row in connection.execute(
            "SELECT * FROM attempt_events WHERE problem_id = ? AND session_id IS NULL",
            (session["problem_id"],),
        ).fetchall()
        if row["id"] not in before_ids
    ]
    if len(candidates) != 1:
        return None
    connection.execute(
        "UPDATE attempt_events SET session_id = ? WHERE id = ?",
        (session["id"], candidates[0]["id"]),
    )
    return candidates[0]


def _complete_session(connection: sqlite3.Connection, session_id: str) -> None:
    now = _now().isoformat()
    connection.execute(
        """
        UPDATE practice_sessions
        SET status = 'completed', completed_at = ?, updated_at = ?
        WHERE id = ? AND status = 'active'
        """,
        (now, now, session_id),
    )
