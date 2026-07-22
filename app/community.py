from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.curriculum import import_skills
from app.repository import ensure_problem, seed_content

STARTER_PATH = Path(__file__).resolve().parents[1] / "curricula" / "starter.json"


def bootstrap_community(connection: sqlite3.Connection, path: Path = STARTER_PATH) -> dict:
    """Idempotently install public metadata and skills, never learner evidence."""
    artifact = json.loads(path.read_text(encoding="utf-8"))
    seed_content(connection)
    import_skills(connection)
    now = datetime.now(UTC).isoformat()
    curriculum = artifact["curriculum"]
    connection.execute(
        """INSERT INTO curricula(id,title,kind,priority,description,provenance_json,created_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
        description=excluded.description, provenance_json=excluded.provenance_json""",
        (
            curriculum["id"],
            curriculum["title"],
            "formal",
            10,
            curriculum["description"],
            json.dumps(artifact["provenance"]),
            now,
        ),
    )
    for position, item in enumerate(artifact["problems"]):
        problem_id = ensure_problem(
            connection,
            leetcode_id=item["id"],
            slug=item["slug"],
            title=item["title"],
            url=f"https://leetcode.com/problems/{item['slug']}/",
            difficulty=item["difficulty"],
            pattern_id=item["skill"],
        )
        connection.execute(
            """INSERT OR IGNORE INTO problem_skills(problem_id,skill_id,role,weight,provenance)
            VALUES(?,?,'core',1.0,'community-starter')""",
            (problem_id, item["skill"]),
        )
        connection.execute(
            """INSERT INTO curriculum_items(curriculum_id,import_key,problem_id,item_kind,
            section,topic,position,title_raw,confidence,provenance_json,created_at)
            VALUES('community-starter',?,?,'problem','Starter catalog',?,?,?,'high','{}',?)
            ON CONFLICT(import_key) DO UPDATE SET problem_id=excluded.problem_id,
            position=excluded.position,title_raw=excluded.title_raw""",
            (f"starter:{item['slug']}", problem_id, item["skill"], position, item["title"], now),
        )
    return {"problems": len(artifact["problems"]), "curriculum": curriculum["id"]}


def get_learner_settings(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute("SELECT * FROM learner_settings WHERE id=1").fetchone()
    if row is None:
        return None
    result = dict(row)
    result["weak_areas"] = json.loads(result.pop("weak_areas_json"))
    return result


def save_learner_settings(connection: sqlite3.Connection, payload: dict) -> dict:
    connection.execute(
        """INSERT INTO learner_settings(id,display_name,interview_target,weekly_hours,timezone,
        weak_areas_json,preferred_language,updated_at) VALUES(1,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,
        interview_target=excluded.interview_target,weekly_hours=excluded.weekly_hours,
        timezone=excluded.timezone,weak_areas_json=excluded.weak_areas_json,
        preferred_language=excluded.preferred_language,updated_at=excluded.updated_at""",
        (
            payload["display_name"],
            payload["interview_target"],
            payload["weekly_hours"],
            payload["timezone"],
            json.dumps(payload["weak_areas"]),
            payload["preferred_language"],
            datetime.now(UTC).isoformat(),
        ),
    )
    return get_learner_settings(connection) or {}
