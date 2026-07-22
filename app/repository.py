from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.content import resolve_problem_content
from app.db import backfill_attempt_errors, backfill_pattern_skills
from app.roadmap import PATTERN_CATALOG
from app.scheduler import retrievability

MOSCOW = ZoneInfo("Europe/Moscow")


def now_iso() -> str:
    return datetime.now(MOSCOW).isoformat()


def seed_content(connection: sqlite3.Connection) -> None:
    for pattern in PATTERN_CATALOG:
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
    # Patterns may be seeded after the backfill migration ran on an empty
    # database, so keep the coarse pattern->skill mirror in sync here too.
    backfill_pattern_skills(connection)
    backfill_attempt_errors(connection)


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
    if leetcode_id is not None:
        # Canonical identity check: if another row already owns this LeetCode id,
        # reuse it rather than creating a slug-keyed duplicate.
        existing = connection.execute(
            "SELECT id, slug FROM problems WHERE leetcode_id = ?", (leetcode_id,)
        ).fetchone()
        if existing is not None and existing["slug"] != slug:
            connection.execute(
                """
                UPDATE problems SET
                  url=COALESCE(?, url),
                  difficulty=COALESCE(?, difficulty),
                  pattern_id=COALESCE(pattern_id, ?)
                WHERE id = ?
                """,
                (url, difficulty, pattern_id, existing["id"]),
            )
            return int(existing["id"])
    connection.execute(
        """
        INSERT INTO problems(leetcode_id, slug, title, url, difficulty, pattern_id)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
          leetcode_id=COALESCE(problems.leetcode_id, excluded.leetcode_id),
          title=excluded.title,
          url=COALESCE(excluded.url, problems.url),
          difficulty=COALESCE(excluded.difficulty, problems.difficulty),
          pattern_id=COALESCE(problems.pattern_id, excluded.pattern_id)
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
    # Hint bodies and authored bujo answers never ship before they are earned:
    # bootstrap exposes only which hint levels exist. Bodies come one at a time
    # through the session hint-reveal endpoint.
    hints = _json(item.pop("hints_json"), {})
    item["hint_levels"] = [level for level in ("H1", "H2", "H3", "H4") if hints.get(level)]
    item.pop("bujo_json", None)
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


CATALOG_CTE = """
WITH base AS (
  SELECT p.id, p.leetcode_id, p.slug, p.title, p.url, p.difficulty, p.pattern_id,
         pt.title AS pattern_title,
         q.state AS queue_state, q.priority, q.roadmap_week, q.roadmap_position,
         q.scheduled_for,
         EXISTS(
           SELECT 1 FROM assignments a
           WHERE a.problem_id = p.id AND a.status IN ('active', 'carryover')
         ) AS is_active,
         (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = p.id) AS evidence_count,
         (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = p.id AND e.independent = 1)
           AS independent_count,
         (SELECT MAX(e.occurred_on) FROM attempt_events e WHERE e.problem_id = p.id)
           AS last_attempt_on,
         (SELECT e.result FROM attempt_events e WHERE e.problem_id = p.id
          ORDER BY e.occurred_on DESC, e.created_at DESC LIMIT 1) AS last_result,
         (SELECT MIN(r.due_on) FROM reviews r
          WHERE r.problem_id = p.id AND r.status != 'completed') AS next_due,
         m.stability_days, m.retrievability, m.evidence_count AS memory_evidence_count
  FROM problems p
  LEFT JOIN patterns pt ON pt.id = p.pattern_id
  LEFT JOIN queue_items q ON q.problem_id = p.id
  LEFT JOIN memory_states m ON m.problem_id = p.id
), catalog AS (
  SELECT *,
    CASE
      WHEN is_active = 1 THEN 'active'
      WHEN queue_state = 'blocked' THEN 'blocked'
      WHEN queue_state = 'archived' THEN 'archived'
      WHEN next_due < :today THEN 'overdue'
      WHEN next_due = :today THEN 'due'
      WHEN next_due IS NOT NULL THEN 'upcoming'
      WHEN evidence_count > 0 AND independent_count >= 2 AND COALESCE(stability_days, 0) >= 7
        THEN 'stable'
      WHEN evidence_count > 0 THEN 'learning'
      WHEN queue_state IN ('scheduled', 'backlog') THEN 'backlog'
      ELSE 'catalog'
    END AS status
  FROM base
)
"""


def problem_catalog(
    connection: sqlite3.Connection,
    *,
    search: str = "",
    statuses: list[str] | None = None,
    pattern: str | None = None,
    difficulty: str | None = None,
    track: str | None = None,
    scope: str = "all",
    sort: str = "priority",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    page = max(1, page)
    page_size = min(100, max(10, page_size))
    params: dict[str, Any] = {"today": datetime.now(MOSCOW).date().isoformat()}
    base_filters: list[str] = []
    if search.strip():
        term = search.strip().lower()
        params["search"] = f"%{term}%"
        clauses = ["LOWER(title) LIKE :search", "LOWER(slug) LIKE :search"]
        number = term.removeprefix("#")
        if number.isdigit():
            # "1192" or "#1192" also matches the LeetCode number by prefix.
            params["search_number"] = f"{number}%"
            clauses.append("CAST(leetcode_id AS TEXT) LIKE :search_number")
        base_filters.append("(" + " OR ".join(clauses) + ")")
    if pattern:
        params["pattern"] = pattern
        base_filters.append("pattern_id = :pattern")
    if difficulty:
        params["difficulty"] = difficulty
        base_filters.append("LOWER(COALESCE(difficulty, '')) = LOWER(:difficulty)")
    if track:
        params["track"] = track
        base_filters.append(
            "id IN (SELECT problem_id FROM curriculum_items "
            "WHERE curriculum_id = :track AND problem_id IS NOT NULL)"
        )
    if scope == "queue":
        base_filters.append("queue_state IS NOT NULL")
    elif scope == "reviews":
        base_filters.append("next_due IS NOT NULL AND status != 'archived'")

    status_filter = ""
    if statuses:
        placeholders = []
        for index, value in enumerate(statuses):
            key = f"status_{index}"
            params[key] = value
            placeholders.append(f":{key}")
        status_filter = f"status IN ({', '.join(placeholders)})"

    facet_where = " AND ".join(base_filters) or "1 = 1"
    list_filters = list(base_filters)
    if status_filter:
        list_filters.append(status_filter)
    elif scope == "queue":
        list_filters.append("status != 'archived'")
    list_where = " AND ".join(list_filters) or "1 = 1"
    order_map = {
        "priority": (
            "COALESCE(priority, 99999), COALESCE(roadmap_week, 999), "
            "COALESCE(roadmap_position, 999), title"
        ),
        "due": "CASE WHEN next_due IS NULL THEN 1 ELSE 0 END, next_due, title",
        "title": "title COLLATE NOCASE",
        "evidence": "evidence_count DESC, title COLLATE NOCASE",
        "recent": (
            "CASE WHEN last_attempt_on IS NULL THEN 1 ELSE 0 END, last_attempt_on DESC, title"
        ),
    }
    order_by = order_map.get(sort, order_map["priority"])
    total = int(
        connection.execute(
            f"{CATALOG_CTE} SELECT COUNT(*) FROM catalog WHERE {list_where}", params
        ).fetchone()[0]
    )
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    rows = connection.execute(
        f"""
        {CATALOG_CTE}
        SELECT * FROM catalog
        WHERE {list_where}
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
        """,
        params,
    ).fetchall()
    count_rows = connection.execute(
        f"""
        {CATALOG_CTE}
        SELECT status, COUNT(*) AS count FROM catalog
        WHERE {facet_where}
        GROUP BY status
        """,
        params,
    ).fetchall()
    track_rows = connection.execute(
        "SELECT id, title, kind, priority FROM curricula ORDER BY priority, id"
    ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "status_counts": {row["status"]: row["count"] for row in count_rows},
        "tracks": [dict(row) for row in track_rows],
    }


def problem_detail(connection: sqlite3.Connection, problem_id: int) -> dict | None:
    row = connection.execute(
        """
        SELECT p.*, pt.title AS pattern_title, pt.description AS pattern_description,
               pt.recognition_signals, q.state AS queue_state, q.priority,
               q.roadmap_week, q.roadmap_position
        FROM problems p
        LEFT JOIN patterns pt ON pt.id = p.pattern_id
        LEFT JOIN queue_items q ON q.problem_id = p.id
        WHERE p.id = ?
        """,
        (problem_id,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["recognition_signals"] = _json(item.get("recognition_signals"), [])
    event_rows = connection.execute(
        """
        SELECT * FROM attempt_events WHERE problem_id = ?
        ORDER BY occurred_on DESC, created_at DESC LIMIT 100
        """,
        (problem_id,),
    ).fetchall()
    review_rows = connection.execute(
        "SELECT * FROM reviews WHERE problem_id = ? ORDER BY due_on",
        (problem_id,),
    ).fetchall()
    memory_row = connection.execute(
        "SELECT * FROM memory_states WHERE problem_id = ?", (problem_id,)
    ).fetchone()
    assignment = active_assignment(connection)
    scheduled_here = connection.execute(
        """
        SELECT id, assigned_on, status FROM assignments
        WHERE problem_id = ? AND status IN ('active', 'carryover')
        ORDER BY assigned_on ASC, created_at ASC LIMIT 1
        """,
        (problem_id,),
    ).fetchone()
    open_practice = connection.execute(
        """
        SELECT id, origin, started_at FROM practice_sessions
        WHERE problem_id = ? AND status = 'active'
        ORDER BY started_at DESC LIMIT 1
        """,
        (problem_id,),
    ).fetchone()
    return {
        "problem": item,
        "attempts": [dict(event) for event in event_rows],
        "reviews": [dict(review) for review in review_rows],
        "memory": dict(memory_row) if memory_row else None,
        "active_assignment": assignment
        if assignment and assignment["problem_id"] == problem_id
        else None,
        # Availability and provenance only — lesson and hint bodies stay behind
        # their dedicated endpoints.
        "content": resolve_problem_content(connection, problem_id),
        "can_start_ad_hoc": True,
        "scheduled_assignment": dict(scheduled_here) if scheduled_here else None,
        "open_practice_session": dict(open_practice) if open_practice else None,
        "skills": _problem_skills_payload(connection, problem_id),
        "prerequisites": _problem_prerequisites(connection, problem_id),
        "related_problems": _related_problems(connection, problem_id),
        "placements": _problem_placements(connection, problem_id),
    }


def _skill_state_summary(connection: sqlite3.Connection, skill_id: str) -> dict:
    rows = connection.execute(
        """
        SELECT dimension, state, evidence_count, independent_count, updated_at
        FROM learner_skill_states WHERE skill_id = ?
        """,
        (skill_id,),
    ).fetchall()
    return {row["dimension"]: dict(row) for row in rows}


def _problem_skills_payload(connection: sqlite3.Connection, problem_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT ps.skill_id, ps.role, ps.weight, ps.provenance,
               s.title, s.kind, s.parent_id
        FROM problem_skills ps JOIN skills s ON s.id = ps.skill_id
        WHERE ps.problem_id = ?
        ORDER BY CASE ps.role WHEN 'core' THEN 0 WHEN 'supporting' THEN 1 ELSE 2 END,
                 ps.weight DESC, ps.skill_id
        """,
        (problem_id,),
    ).fetchall()
    output = []
    for row in rows:
        entry = dict(row)
        entry["states"] = _skill_state_summary(connection, row["skill_id"])
        output.append(entry)
    return output


def _problem_prerequisites(connection: sqlite3.Connection, problem_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT DISTINCT se.from_skill AS skill_id, s.title, se.weight
        FROM problem_skills ps
        JOIN skill_edges se ON se.to_skill = ps.skill_id AND se.edge_type = 'prerequisite'
        JOIN skills s ON s.id = se.from_skill
        WHERE ps.problem_id = ? AND ps.role = 'core'
        ORDER BY se.from_skill
        """,
        (problem_id,),
    ).fetchall()
    output = []
    for row in rows:
        entry = dict(row)
        entry["states"] = _skill_state_summary(connection, row["skill_id"])
        output.append(entry)
    return output


def _related_problems(connection: sqlite3.Connection, problem_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT DISTINCT p.id, p.leetcode_id, p.slug, p.title, p.difficulty,
               ps2.skill_id AS shared_skill,
               (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = p.id
                  AND e.result != 'skipped') AS attempt_count
        FROM problem_skills ps1
        JOIN problem_skills ps2 ON ps2.skill_id = ps1.skill_id AND ps2.problem_id != ps1.problem_id
        JOIN problems p ON p.id = ps2.problem_id
        WHERE ps1.problem_id = ? AND ps1.role = 'core' AND ps2.role IN ('core', 'variation')
        ORDER BY p.title
        LIMIT 8
        """,
        (problem_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _problem_placements(connection: sqlite3.Connection, problem_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT ci.curriculum_id, c.title AS curriculum_title, c.kind, c.priority,
               ci.week_label, ci.section, ci.topic, ci.position, ci.confidence,
               ci.source_screenshot
        FROM curriculum_items ci JOIN curricula c ON c.id = ci.curriculum_id
        WHERE ci.problem_id = ?
        ORDER BY c.priority, ci.position
        """,
        (problem_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def bootstrap(connection: sqlite3.Connection) -> dict:
    from app.community import get_learner_settings

    event_rows = attempts(connection)
    outcomes = Counter(row["result"] for row in event_rows)
    failures = Counter(row["failure_tag"] for row in event_rows if row.get("failure_tag"))
    today = datetime.now(MOSCOW).date().isoformat()
    active = active_assignment(connection)
    queue_snapshot = problem_catalog(connection, scope="queue", page_size=10)
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
        "timezone": (get_learner_settings(connection) or {}).get("timezone", "UTC"),
        "learner": get_learner_settings(connection),
        "active_assignment": active,
        "attempts": event_rows,
        "reviews": reviews(connection),
        "memory": memory_states(connection),
        "patterns": pattern_summaries(connection),
        "profile": profile(connection),
        "workload": {
            "total": queue_snapshot["total"],
            "status_counts": queue_snapshot["status_counts"],
            "preview": queue_snapshot["items"][:5],
        },
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
