from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.lessons import LOW_LINK_PATTERN, lesson_payload
from app.scheduler import retrievability

MOSCOW = ZoneInfo("Europe/Moscow")


def now_iso() -> str:
    return datetime.now(MOSCOW).isoformat()


def seed_content(connection: sqlite3.Connection) -> None:
    pattern = LOW_LINK_PATTERN
    connection.execute(
        """
        INSERT INTO patterns(id, title, description, recognition_signals, created_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          description=excluded.description,
          recognition_signals=excluded.recognition_signals
        """,
        (
            pattern["id"],
            pattern["title"],
            pattern["description"],
            json.dumps(pattern["recognition_signals"], ensure_ascii=False),
            now_iso(),
        ),
    )


def ensure_problem(
    connection: sqlite3.Connection,
    *,
    leetcode_id: int | None,
    slug: str,
    title: str,
    url: str | None,
    difficulty: str | None = None,
    pattern_id: str | None = None,
) -> int:
    connection.execute(
        """
        INSERT INTO problems(leetcode_id, slug, title, url, difficulty, pattern_id)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
          title=excluded.title,
          url=COALESCE(excluded.url, problems.url),
          difficulty=COALESCE(excluded.difficulty, problems.difficulty),
          pattern_id=COALESCE(excluded.pattern_id, problems.pattern_id)
        """,
        (leetcode_id, slug, title, url, difficulty, pattern_id),
    )
    row = connection.execute("SELECT id FROM problems WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise RuntimeError("problem upsert failed")
    return int(row["id"])


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def active_assignment(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        """
        SELECT a.*, p.leetcode_id, p.slug, p.title, p.url, p.difficulty,
               p.pattern_id, pt.title AS pattern_title, pt.description AS pattern_description,
               pt.recognition_signals, n.content AS notes
        FROM assignments a
        JOIN problems p ON p.id = a.problem_id
        LEFT JOIN patterns pt ON pt.id = p.pattern_id
        LEFT JOIN notes n ON n.assignment_id = a.id
        WHERE a.status IN ('active', 'carryover')
        ORDER BY a.assigned_on ASC, a.created_at ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["hints"] = _json(item.pop("hints_json"), {})
    item["bujo"] = _json(item.pop("bujo_json"), {})
    item["recognition_signals"] = _json(item.get("recognition_signals"), [])
    item["notes"] = item.get("notes") or ""
    return item


def attempts(connection: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = connection.execute(
        """
        SELECT e.*, p.leetcode_id, p.slug, p.title, p.pattern_id
        FROM attempt_events e
        JOIN problems p ON p.id = e.problem_id
        ORDER BY e.occurred_on DESC, e.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def reviews(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT r.*, p.leetcode_id, p.slug, p.title, p.pattern_id
        FROM reviews r
        JOIN problems p ON p.id = r.problem_id
        WHERE r.status != 'completed'
        ORDER BY r.due_on ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def memory_states(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT m.*, p.leetcode_id, p.slug, p.title, p.pattern_id
        FROM memory_states m
        JOIN problems p ON p.id = m.problem_id
        ORDER BY m.next_due ASC
        """
    ).fetchall()
    today = datetime.now(MOSCOW).date()
    output = []
    for row in rows:
        item = dict(row)
        elapsed = (today - date.fromisoformat(item["last_attempt_on"])).days
        item["retrievability"] = retrievability(item["stability_days"], elapsed)
        item["curve"] = [
            {"day": day, "value": retrievability(item["stability_days"], day)}
            for day in range(0, 31)
        ]
        output.append(item)
    return output


def profile(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute(
        "SELECT payload_json FROM profile_snapshots ORDER BY retrieved_at DESC LIMIT 1"
    ).fetchone()
    return _json(row["payload_json"], {}) if row else None


def pattern_summaries(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT p.id, p.title, p.description, p.recognition_signals,
               COUNT(e.id) AS evidence_count,
               SUM(CASE WHEN e.independent = 1 THEN 1 ELSE 0 END) AS independent_count,
               SUM(CASE WHEN e.result = 'red' THEN 1 ELSE 0 END) AS red_count
        FROM patterns p
        LEFT JOIN problems pr ON pr.pattern_id = p.id
        LEFT JOIN attempt_events e ON e.problem_id = pr.id
        GROUP BY p.id
        ORDER BY p.title
        """
    ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["recognition_signals"] = _json(item["recognition_signals"], [])
        count = int(item["evidence_count"] or 0)
        item["confidence"] = "early" if count < 6 else "developing" if count < 20 else "established"
        output.append(item)
    return output


def bootstrap(connection: sqlite3.Connection) -> dict:
    event_rows = attempts(connection)
    outcomes = Counter(row["result"] for row in event_rows)
    failures = Counter(row["failure_tag"] for row in event_rows if row.get("failure_tag"))
    today = datetime.now(MOSCOW).date().isoformat()
    active = active_assignment(connection)
    if active:
        if active["assigned_on"] > today:
            active["date_label"] = "Next session"
        elif active["assigned_on"] < today:
            active["date_label"] = "Carryover"
        else:
            active["date_label"] = "Today"
    return {
        "generated_at": now_iso(),
        "today": today,
        "timezone": "Europe/Moscow",
        "active_assignment": active,
        "attempts": event_rows,
        "reviews": reviews(connection),
        "memory": memory_states(connection),
        "patterns": pattern_summaries(connection),
        "profile": profile(connection),
        "lesson": lesson_payload(),
        "evidence": {
            "count": len(event_rows),
            "outcomes": dict(outcomes),
            "failures": dict(failures),
            "independent_count": sum(bool(row["independent"]) for row in event_rows),
            "accepted_count": sum(bool(row["accepted"]) for row in event_rows),
            "confidence": "early"
            if len(event_rows) < 6
            else "developing"
            if len(event_rows) < 20
            else "established",
        },
    }
