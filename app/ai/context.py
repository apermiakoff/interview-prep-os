from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.content import HINT_LEVELS, hint_ladder
from app.errors import NotFoundError

MAX_ATTEMPTS = 20
MAX_LEARNING_ITEMS = 100


def _attempts(connection: sqlite3.Connection, problem_id: int) -> list[dict]:
    rows = connection.execute(
        """SELECT id, occurred_on, result, accepted, independent, duration_minutes,
                  highest_hint, failure_tag, explanation_score, source, session_id
           FROM attempt_events WHERE problem_id=?
           ORDER BY occurred_on DESC, created_at DESC LIMIT ?""",
        (problem_id, MAX_ATTEMPTS),
    ).fetchall()
    return [
        {
            "evidence_id": f"attempt:{row['id']}",
            "occurred_on": row["occurred_on"],
            "result": row["result"],
            "accepted": bool(row["accepted"]),
            "independent": bool(row["independent"]),
            "duration_minutes": row["duration_minutes"],
            "highest_hint": row["highest_hint"],
            "failure_tag": row["failure_tag"],
            "explanation_score": row["explanation_score"],
            "source": row["source"],
            "session_id": row["session_id"],
        }
        for row in rows
    ]


def _problem(connection: sqlite3.Connection, problem_id: int) -> dict:
    row = connection.execute(
        """SELECT p.id,p.leetcode_id,p.slug,p.title,p.url,p.difficulty,p.pattern_id,
                  pt.title pattern_title,pt.description pattern_description
           FROM problems p LEFT JOIN patterns pt ON pt.id=p.pattern_id WHERE p.id=?""",
        (problem_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("problem not found")
    skills = connection.execute(
        """SELECT s.id,s.title,s.kind,ps.role,ps.provenance FROM problem_skills ps
           JOIN skills s ON s.id=ps.skill_id WHERE ps.problem_id=? ORDER BY ps.weight DESC""",
        (problem_id,),
    ).fetchall()
    prereqs = connection.execute(
        """SELECT e.from_skill id,s.title FROM skill_edges e JOIN skills s ON s.id=e.from_skill
           WHERE e.to_skill IN (SELECT skill_id FROM problem_skills WHERE problem_id=?)
             AND e.edge_type='prerequisite'""",
        (problem_id,),
    ).fetchall()
    return {
        "identity": {
            key: row[key] for key in ("id", "leetcode_id", "slug", "title", "url", "difficulty")
        },
        "pattern": {
            "id": row["pattern_id"],
            "title": row["pattern_title"],
            "description": row["pattern_description"],
            "provenance": "curated-or-imported",
        },
        "skills": [dict(item) for item in skills],
        "prerequisites": [dict(item) for item in prereqs],
        "attempt_summaries": _attempts(connection, problem_id),
    }


def problem_snapshot(connection: sqlite3.Connection, problem_id: int) -> dict:
    return {
        "schema_version": "problem-context@1",
        "scope": "problem",
        "problem": _problem(connection, problem_id),
    }


def session_snapshot(connection: sqlite3.Connection, session_id: str) -> dict:
    session = connection.execute(
        """SELECT id,problem_id,origin,status,mode,goal,timebox_minutes,highest_hint,
                  started_at,completed_at,ai_assisted
           FROM practice_sessions WHERE id=?""",
        (session_id,),
    ).fetchone()
    if session is None:
        raise NotFoundError("practice session not found")
    hints = hint_ladder(connection, session["problem_id"]) or {}
    rank = {level: index for index, level in enumerate(HINT_LEVELS, 1)}
    revealed = rank.get(session["highest_hint"], 0)
    revealed_hints = [
        {"evidence_id": f"hint:{session_id}:{level}", "level": level, "body": hints[level]}
        for level in HINT_LEVELS[:revealed]
        if level in hints
    ]
    outcome = connection.execute(
        """SELECT id,result,accepted,independent,duration_minutes,highest_hint,failure_tag,
                  explanation_score,occurred_on FROM attempt_events WHERE session_id=?
           ORDER BY created_at DESC LIMIT 1""",
        (session_id,),
    ).fetchone()
    data = {
        key: session[key]
        for key in (
            "id",
            "origin",
            "status",
            "mode",
            "goal",
            "timebox_minutes",
            "highest_hint",
            "started_at",
            "completed_at",
        )
    }
    data["ai_assisted"] = bool(session["ai_assisted"])
    return {
        "schema_version": "session-context@1",
        "scope": "session",
        "session": data,
        "problem": _problem(connection, session["problem_id"]),
        "revealed_hints": revealed_hints,
        "outcome": (
            {
                "evidence_id": f"attempt:{outcome['id']}",
                **{key: outcome[key] for key in outcome if key != "id"},
            }
            if outcome
            else None
        ),
        "captured_at": datetime.now().isoformat(),
    }


def learning_snapshot(connection: sqlite3.Connection) -> dict:
    """Build bounded longitudinal facts without private/free-form core fields."""
    attempts = [
        {
            "evidence_id": f"attempt:{row['id']}",
            "problem_id": row["problem_id"],
            "problem_title": row["problem_title"],
            "occurred_on": row["occurred_on"],
            "result": row["result"],
            "accepted": bool(row["accepted"]),
            "independent": bool(row["independent"]),
            "duration_minutes": row["duration_minutes"],
            "highest_hint": row["highest_hint"],
            "failure_tag": row["failure_tag"],
            "explanation_score": row["explanation_score"],
            "source": row["source"],
            "session_id": row["session_id"],
        }
        for row in connection.execute(
            """SELECT e.id,e.problem_id,p.title problem_title,e.occurred_on,e.result,
                      e.accepted,e.independent,e.duration_minutes,e.highest_hint,e.failure_tag,
                      e.explanation_score,e.source,e.session_id
               FROM attempt_events e JOIN problems p ON p.id=e.problem_id
               ORDER BY e.occurred_on DESC,e.created_at DESC LIMIT ?""",
            (MAX_LEARNING_ITEMS,),
        )
    ]
    hints = [
        {
            "evidence_id": f"hint-event:{row['id']}",
            "session_id": row["session_id"],
            "problem_id": row["problem_id"],
            "level": row["level"],
            "occurred_at": row["occurred_at"],
        }
        for row in connection.execute(
            """SELECT h.id,h.session_id,s.problem_id,h.level,h.occurred_at
               FROM session_hint_events h JOIN practice_sessions s ON s.id=h.session_id
               ORDER BY h.occurred_at DESC LIMIT ?""",
            (MAX_LEARNING_ITEMS,),
        )
    ]
    sessions = [
        {
            "evidence_id": f"session:{row['id']}:{row['updated_at']}",
            "problem_id": row["problem_id"],
            "origin": row["origin"],
            "status": row["status"],
            "mode": row["mode"],
            "timebox_minutes": row["timebox_minutes"],
            "highest_hint": row["highest_hint"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "ai_assisted": bool(row["ai_assisted"]),
        }
        for row in connection.execute(
            """SELECT id,problem_id,origin,status,mode,timebox_minutes,highest_hint,
                      started_at,updated_at,completed_at,ai_assisted FROM practice_sessions
               ORDER BY started_at DESC LIMIT ?""",
            (MAX_LEARNING_ITEMS,),
        )
    ]
    skill_states = [
        {
            "evidence_id": f"skill-state:{row['skill_id']}:{row['dimension']}:{row['updated_at']}",
            **dict(row),
        }
        for row in connection.execute(
            """SELECT l.skill_id,s.title skill_title,l.dimension,l.state,l.evidence_count,
                      l.independent_count,l.last_evidence_on,l.stability_days,l.policy_version,
                      l.updated_at FROM learner_skill_states l JOIN skills s ON s.id=l.skill_id
               ORDER BY l.updated_at DESC,l.skill_id,l.dimension LIMIT ?""",
            (MAX_LEARNING_ITEMS,),
        )
    ]
    return {
        "schema_version": "learning-context@1",
        "scope": "learning",
        "attempts": attempts,
        "hint_events": hints,
        "sessions": sessions,
        "skill_states": skill_states,
        "bounds": {"per_fact_type": MAX_LEARNING_ITEMS},
    }


def evidence_ids(snapshot: dict) -> set[str]:
    result: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("evidence_id"), str):
                result.add(value["evidence_id"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(snapshot)
    return result


def canonical(snapshot: dict) -> str:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
