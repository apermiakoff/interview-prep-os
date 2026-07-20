from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.db import backfill_pattern_skills
from app.repository import ensure_problem

CURRICULA_DIR = Path(__file__).resolve().parents[1] / "curricula"
OUTTALENT_ARTIFACT = CURRICULA_DIR / "outtalent.json"
SKILLS_ARTIFACT = CURRICULA_DIR / "skills.json"

# Outtalent placements outrank everything else in the shared queue ordering.
OUTTALENT_PRIORITY_BASE = -10_000

DEEP_CURRICULUM = {
    "id": "deep-supplemental",
    "title": "Deep supplemental roadmap",
    "kind": "supplemental",
    "priority": 100,
    "description": (
        "Personal twelve-week study plan imported from the legacy roadmap. Supplements the "
        "formal Outtalent program with breadth and transfer practice; ranked below it."
    ),
}


def _now() -> str:
    return datetime.now().isoformat()


def _upsert_curriculum(connection: sqlite3.Connection, spec: dict, provenance: dict) -> None:
    connection.execute(
        """
        INSERT INTO curricula(id, title, kind, priority, description, provenance_json, created_at)
        VALUES(?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title, kind=excluded.kind, priority=excluded.priority,
          description=excluded.description, provenance_json=excluded.provenance_json
        """,
        (
            spec["id"],
            spec["title"],
            spec["kind"],
            spec["priority"],
            spec.get("description", ""),
            json.dumps(provenance, ensure_ascii=False),
            _now(),
        ),
    )


def _upsert_skill(connection: sqlite3.Connection, skill: dict) -> None:
    connection.execute(
        """
        INSERT INTO skills(id, title, kind, description, parent_id, provenance, created_at)
        VALUES(?, ?, ?, ?, ?, 'curated', ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title, kind=excluded.kind, description=excluded.description,
          parent_id=excluded.parent_id, provenance='curated'
        """,
        (
            skill["id"],
            skill["title"],
            skill.get("kind", "technique"),
            skill.get("description", ""),
            skill.get("parent"),
            _now(),
        ),
    )


def _ensure_skill_exists(connection: sqlite3.Connection, skill_id: str) -> None:
    """Edges/mappings may reference a legacy pattern skill before patterns were
    seeded; create a minimal placeholder rather than failing the import."""
    connection.execute(
        """
        INSERT OR IGNORE INTO skills(id, title, kind, description, provenance, created_at)
        VALUES(?, ?, 'technique', '', 'curated', ?)
        """,
        (skill_id, skill_id.replace("/", " · ").replace("-", " ").title(), _now()),
    )


def import_skills(connection: sqlite3.Connection, skills_path: Path | None = None) -> dict:
    payload = json.loads((skills_path or SKILLS_ARTIFACT).read_text(encoding="utf-8"))
    for skill in payload.get("skills", []):
        if skill.get("parent"):
            _ensure_skill_exists(connection, skill["parent"])
        _upsert_skill(connection, skill)
    edges = 0
    for edge in payload.get("edges", []):
        _ensure_skill_exists(connection, edge["from"])
        _ensure_skill_exists(connection, edge["to"])
        connection.execute(
            """
            INSERT INTO skill_edges(from_skill, to_skill, edge_type, weight, provenance)
            VALUES(?, ?, ?, ?, 'curated')
            ON CONFLICT(from_skill, to_skill, edge_type) DO UPDATE SET
              weight=excluded.weight, provenance='curated'
            """,
            (edge["from"], edge["to"], edge["type"], edge.get("weight", 1.0)),
        )
        edges += 1
    return {"skills": len(payload.get("skills", [])), "edges": edges, "payload": payload}


def _map_problem_skills(
    connection: sqlite3.Connection, problem_id: int, mappings: list[dict]
) -> None:
    for mapping in mappings:
        inline = mapping.get("create")
        if inline:
            _upsert_skill(connection, {"id": mapping["skill"], **inline})
        _ensure_skill_exists(connection, mapping["skill"])
        connection.execute(
            """
            INSERT INTO problem_skills(problem_id, skill_id, role, weight, provenance)
            VALUES(?, ?, ?, ?, 'curated')
            ON CONFLICT(problem_id, skill_id) DO UPDATE SET
              role=excluded.role, weight=excluded.weight, provenance='curated'
            """,
            (problem_id, mapping["skill"], mapping.get("role", "core"), mapping.get("weight", 1.0)),
        )


def import_outtalent(
    connection: sqlite3.Connection,
    artifact_path: Path | None = None,
    skills_path: Path | None = None,
) -> dict:
    """Idempotent import of the Outtalent screenshot artifact plus the curated skill
    taxonomy. Re-running updates placements in place via stable import keys; it never
    duplicates rows or touches attempt evidence."""
    artifact = json.loads((artifact_path or OUTTALENT_ARTIFACT).read_text(encoding="utf-8"))
    skills_summary = import_skills(connection, skills_path)
    skill_mappings = skills_summary["payload"].get("problem_skills", {})

    curriculum = artifact["curriculum"]
    _upsert_curriculum(
        connection,
        curriculum,
        {**curriculum.get("provenance", {}), "extraction_notes": artifact.get("extraction_notes")},
    )

    now = _now()
    problems_seen: dict[int, int] = {}
    placements = 0
    non_problem = {"reading": 0, "mock": 0, "placeholder": 0, "feedback": 0}
    for position, item in enumerate(artifact["items"]):
        problem_id = None
        leetcode_id = item.get("leetcode_id")
        if item["item_kind"] == "problem" and leetcode_id is not None:
            meta = artifact["problems"][str(leetcode_id)]
            problem_id = ensure_problem(
                connection,
                leetcode_id=int(leetcode_id),
                slug=meta["slug"],
                title=meta["title"],
                url=f"https://leetcode.com/problems/{meta['slug']}/",
                difficulty=meta.get("difficulty"),
                pattern_id=meta.get("pattern_id"),
            )
            if leetcode_id not in problems_seen:
                problems_seen[int(leetcode_id)] = problem_id
                _map_problem_skills(
                    connection, problem_id, skill_mappings.get(str(leetcode_id), [])
                )
            connection.execute(
                """
                INSERT INTO queue_items(
                  problem_id, state, priority, source, created_at, updated_at
                ) VALUES(?, 'backlog', ?, 'outtalent', ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  priority=excluded.priority,
                  source='outtalent',
                  updated_at=excluded.updated_at
                """,
                (problem_id, OUTTALENT_PRIORITY_BASE + position, now, now),
            )
            placements += 1
        else:
            non_problem[item["item_kind"]] = non_problem.get(item["item_kind"], 0) + 1
        provenance = {
            "source_screenshot": item.get("source_screenshot"),
            "status_seen": item.get("status_seen"),
            "notes": item.get("notes"),
        }
        connection.execute(
            """
            INSERT INTO curriculum_items(
              curriculum_id, import_key, problem_id, item_kind, section, topic, week_label,
              position, title_raw, status_seen, points_seen, source_screenshot, confidence,
              provenance_json, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(import_key) DO UPDATE SET
              problem_id=excluded.problem_id, item_kind=excluded.item_kind,
              section=excluded.section, topic=excluded.topic, week_label=excluded.week_label,
              position=excluded.position, title_raw=excluded.title_raw,
              status_seen=excluded.status_seen, points_seen=excluded.points_seen,
              source_screenshot=excluded.source_screenshot, confidence=excluded.confidence,
              provenance_json=excluded.provenance_json
            """,
            (
                curriculum["id"],
                item["import_key"],
                problem_id,
                item["item_kind"],
                item.get("section", ""),
                item.get("topic", ""),
                item.get("week_label"),
                position,
                item["title_raw"],
                item.get("status_seen"),
                item.get("points_seen"),
                item.get("source_screenshot"),
                item.get("confidence", "high"),
                json.dumps(provenance, ensure_ascii=False),
                now,
            ),
        )

    # Newly imported problems just received pattern ids; mirror them into the
    # coarse pattern-skill mapping now so one import run fully converges.
    backfill_pattern_skills(connection)

    deep_summary = backfill_deep_track(connection)
    return {
        "curriculum": curriculum["id"],
        "unique_problems": len(problems_seen),
        "problem_placements": placements,
        "non_problem_items": non_problem,
        "total_items": len(artifact["items"]),
        "skills": skills_summary["skills"],
        "skill_edges": skills_summary["edges"],
        "deep_track_items": deep_summary["items"],
        "extraction_notes": artifact.get("extraction_notes", []),
    }


def backfill_deep_track(connection: sqlite3.Connection) -> dict:
    """Mirror the legacy study-plan roadmap into an explicit supplemental track so both
    curricula live in the same normalized tables."""
    _upsert_curriculum(
        connection,
        DEEP_CURRICULUM,
        {
            "source": "legacy import of aleksandr-interview-study-plan.md",
            "backfilled_on": _now(),
        },
    )
    rows = connection.execute(
        """
        SELECT q.problem_id, q.roadmap_week, q.roadmap_position, p.slug, p.title, p.pattern_id
        FROM queue_items q
        JOIN problems p ON p.id = q.problem_id
        WHERE q.roadmap_week IS NOT NULL OR q.source = 'study-plan'
        ORDER BY q.roadmap_week, q.roadmap_position
        """
    ).fetchall()
    now = _now()
    count = 0
    for row in rows:
        week = row["roadmap_week"]
        position = (week or 0) * 100 + (row["roadmap_position"] or 0)
        connection.execute(
            """
            INSERT INTO curriculum_items(
              curriculum_id, import_key, problem_id, item_kind, section, topic, week_label,
              position, title_raw, confidence, provenance_json, created_at
            ) VALUES('deep-supplemental', ?, ?, 'problem', 'Study plan', ?, ?, ?, ?, 'high', ?, ?)
            ON CONFLICT(import_key) DO UPDATE SET
              problem_id=excluded.problem_id, topic=excluded.topic,
              week_label=excluded.week_label, position=excluded.position,
              title_raw=excluded.title_raw
            """,
            (
                f"deep:{row['slug']}",
                row["problem_id"],
                row["pattern_id"] or "",
                f"Week {week}" if week is not None else None,
                position,
                row["title"],
                json.dumps({"source": "study-plan roadmap backfill"}, ensure_ascii=False),
                now,
            ),
        )
        count += 1
    return {"items": count}
