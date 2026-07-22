#!/usr/bin/env python3
"""Hermetic Playwright server backed by deterministic synthetic evidence.

- Starts empty unless INTERVIEW_PREP_E2E_SOURCE is explicitly provided.
- Applies migrations, imports repository-owned catalog metadata, and adds only
  synthetic E2E evidence.
- Guarantees a stable active assignment so Solve-room flows are testable.
- Strips the legacy-coach env bridge so nothing shells out to the real tracker.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PORT = int(os.getenv("INTERVIEW_PREP_E2E_PORT", "8788"))
TARGET = ROOT / "data" / "e2e" / "interview-prep-e2e.db"


def prepare_database() -> None:
    source_value = os.getenv("INTERVIEW_PREP_E2E_SOURCE")
    source = Path(source_value) if source_value else None
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = TARGET.parent / (TARGET.name + suffix)
        if stale.exists():
            stale.unlink()
    if source is not None and source.exists():
        with sqlite3.connect(source) as src, sqlite3.connect(TARGET) as dst:
            src.backup(dst)

    os.environ["INTERVIEW_PREP_DB"] = str(TARGET)
    from app.curriculum import import_outtalent
    from app.db import init_db, transaction
    from app.repository import ensure_problem, seed_content

    init_db(TARGET)
    with transaction(TARGET) as connection:
        seed_content(connection)
        import_outtalent(connection)
        seed_e2e_fixture(connection, ensure_problem)
        ensure_active_assignment(connection)


def seed_e2e_fixture(connection: sqlite3.Connection, ensure_problem) -> None:
    """Add canonical metadata and synthetic evidence used by browser assertions."""
    required = [
        (1, "two-sum", "Two Sum", "Easy", "mixed/design"),
        (207, "course-schedule", "Course Schedule", "Medium", "graph/modeling"),
        (
            417,
            "pacific-atlantic-water-flow",
            "Pacific Atlantic Water Flow",
            "Medium",
            "graph/traversal",
        ),
        (695, "max-area-of-island", "Max Area of Island", "Medium", "graph/traversal"),
        (
            1192,
            "critical-connections-in-a-network",
            "Critical Connections in a Network",
            "Hard",
            "graph/low-link-bridges",
        ),
        (721, "accounts-merge", "Accounts Merge", "Medium", "graph/traversal"),
        (286, "walls-and-gates", "Walls and Gates", "Medium", "graph/traversal"),
        (994, "rotting-oranges", "Rotting Oranges", "Medium", "graph/traversal"),
    ]
    problem_ids: dict[str, int] = {}
    for leetcode_id, slug, title, difficulty, pattern_id in required:
        problem_ids[slug] = ensure_problem(
            connection,
            leetcode_id=leetcode_id,
            slug=slug,
            title=title,
            url=f"https://leetcode.com/problems/{slug}/",
            difficulty=difficulty,
            pattern_id=pattern_id,
        )

    from app.attempts import record_attempt_evidence

    for index, slug in enumerate(("accounts-merge", "walls-and-gates"), start=1):
        occurred = datetime.now(UTC) - timedelta(days=4 - index)
        record_attempt_evidence(
            connection,
            problem_id=problem_ids[slug],
            event_id=f"e2e-synthetic-attempt-{index}",
            result="red",
            accepted=False,
            independent=False,
            highest_hint=None,
            duration_minutes=35,
            failure_tag="implementation",
            explanation_score=1.0,
            assignment_id=None,
            session_id=None,
            source="e2e-synthetic",
            raw_json='{"fixture":"synthetic"}',
            now=occurred,
        )


def ensure_active_assignment(connection: sqlite3.Connection) -> None:
    active = connection.execute(
        "SELECT 1 FROM assignments WHERE status IN ('active', 'carryover') LIMIT 1"
    ).fetchone()
    if active:
        return
    problem = connection.execute(
        "SELECT id, title FROM problems WHERE leetcode_id=1 LIMIT 1"
    ).fetchone()
    if problem is None:
        return
    connection.execute(
        """
        INSERT OR REPLACE INTO assignments(
          id, problem_id, assigned_on, mode, status, timebox_minutes, goal,
          hints_json, bujo_json, created_at
        ) VALUES('e2e-assignment', ?, date('now'), 'blind reconstruction retry', 'active', 35,
                 'Reconstruct the invariant before code.',
                 '{"H1": "Question hint", "H2": "Invariant hint", "H3": "Pattern hint", '
                 || '"H4": "Walkthrough hint"}',
                 '{}', datetime('now'))
        """,
        (problem["id"],),
    )


def main() -> None:
    prepare_database()
    os.environ.setdefault("INTERVIEW_PREP_STATIC", str(ROOT / "frontend" / "dist"))
    ai_target = Path(f"/tmp/interview-prep-e2e-ai-{PORT}-{os.getpid()}.db")
    if ai_target.exists():
        ai_target.unlink()
    os.environ["INTERVIEW_PREP_AI_DB"] = str(ai_target)
    os.environ["INTERVIEW_PREP_AI_ENABLED"] = "false"
    for var in (
        "INTERVIEW_PREP_LEGACY_STATE",
        "INTERVIEW_PREP_LEGACY_EVENTS",
        "INTERVIEW_PREP_LEGACY_PROFILE",
        "INTERVIEW_PREP_LEGACY_ACTION",
        "INTERVIEW_PREP_LEGACY_PLAN",
    ):
        os.environ.pop(var, None)

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
