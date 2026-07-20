from __future__ import annotations

import json

from app.curriculum import OUTTALENT_ARTIFACT, import_outtalent
from app.db import connect, init_db, transaction
from app.repository import seed_content


def _imported(tmp_path, runs=1):
    path = tmp_path / "import.db"
    init_db(path)
    summary = None
    for _ in range(runs):
        with transaction(path) as connection:
            seed_content(connection)
            summary = import_outtalent(connection)
    return path, summary


def test_import_is_idempotent(tmp_path):
    path, first = _imported(tmp_path, runs=1)
    with connect(path) as connection:
        counts_before = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("problems", "curriculum_items", "problem_skills", "skills", "curricula")
        }
    _, second = _imported(tmp_path, runs=2)
    with connect(path) as connection:
        counts_after = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("problems", "curriculum_items", "problem_skills", "skills", "curricula")
        }
    assert counts_before == counts_after
    assert first["unique_problems"] == second["unique_problems"] == 40
    assert first["problem_placements"] == 41


def test_repeated_placement_of_same_problem_within_track(tmp_path):
    path, _ = _imported(tmp_path)
    with connect(path) as connection:
        rows = connection.execute(
            """
            SELECT ci.import_key, ci.position FROM curriculum_items ci
            JOIN problems p ON p.id = ci.problem_id
            WHERE p.leetcode_id = 402 AND ci.curriculum_id = 'outtalent'
            ORDER BY ci.position
            """
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["import_key"] != rows[1]["import_key"]
    assert rows[0]["position"] != rows[1]["position"]


def test_same_problem_appears_in_multiple_tracks(tmp_path):
    path, _ = _imported(tmp_path)
    init_legacy_roadmap(path)
    with transaction(path) as connection:
        summary = import_outtalent(connection)
    assert summary["deep_track_items"] == 1
    with connect(path) as connection:
        tracks = [
            row[0]
            for row in connection.execute(
                """
                SELECT ci.curriculum_id FROM curriculum_items ci
                JOIN problems p ON p.id = ci.problem_id
                WHERE p.leetcode_id = 322
                ORDER BY ci.curriculum_id
                """
            )
        ]
    assert tracks == ["deep-supplemental", "outtalent"]


def init_legacy_roadmap(path):
    """Simulate the pre-existing study-plan queue entry for Coin Change."""
    from datetime import datetime

    with transaction(path) as connection:
        problem_id = connection.execute(
            "SELECT id FROM problems WHERE leetcode_id = 322"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO queue_items(
              problem_id, state, priority, roadmap_week, roadmap_position, source,
              created_at, updated_at
            ) VALUES(?, 'backlog', 501, 5, 1, 'study-plan', ?, ?)
            ON CONFLICT(problem_id) DO UPDATE SET
              roadmap_week=5, roadmap_position=1
            """,
            (problem_id, datetime.now().isoformat(), datetime.now().isoformat()),
        )


def test_outtalent_ranks_above_deep_supplemental(tmp_path):
    path, _ = _imported(tmp_path)
    with connect(path) as connection:
        priorities = dict(connection.execute("SELECT id, priority FROM curricula").fetchall())
        assert priorities["outtalent"] < priorities["deep-supplemental"]
        queue_priority = connection.execute(
            """
            SELECT q.priority FROM queue_items q JOIN problems p ON p.id = q.problem_id
            WHERE p.leetcode_id = 1489
            """
        ).fetchone()[0]
        assert queue_priority < 0  # outranks every legacy roadmap priority


def test_provenance_and_completeness_are_honest(tmp_path):
    artifact = json.loads(OUTTALENT_ARTIFACT.read_text(encoding="utf-8"))
    # Week 19 shows 16 tasks in its header; all 16 must be accounted for.
    week19 = [item for item in artifact["items"] if item["week_label"] == "Week 19"]
    assert len(week19) == 16
    # Placeholder rows carry no invented problem number.
    placeholders = [item for item in artifact["items"] if item["item_kind"] == "placeholder"]
    assert placeholders and all(item["leetcode_id"] is None for item in placeholders)

    path, summary = _imported(tmp_path)
    assert summary["non_problem_items"] == {
        "reading": 3,
        "mock": 4,
        "placeholder": 5,
        "feedback": 1,
    }
    assert summary["total_items"] == 54
    with connect(path) as connection:
        # Every imported item names its source screenshot.
        missing_source = connection.execute(
            """
            SELECT COUNT(*) FROM curriculum_items
            WHERE curriculum_id = 'outtalent' AND source_screenshot IS NULL
            """
        ).fetchone()[0]
        assert missing_source == 0
        # Cropped week selectors stay null instead of a guessed label.
        unknown_week = connection.execute(
            """
            SELECT COUNT(*) FROM curriculum_items
            WHERE curriculum_id = 'outtalent' AND week_label IS NULL
            """
        ).fetchone()[0]
        assert unknown_week == 38
        # Canonical identity was verified, not OCR-trusted.
        row = connection.execute(
            "SELECT slug, title, difficulty FROM problems WHERE leetcode_id = 1489"
        ).fetchone()
        assert row["slug"] == "find-critical-and-pseudo-critical-edges-in-minimum-spanning-tree"
        assert row["difficulty"] == "Hard"


def test_import_never_touches_attempt_evidence(tmp_path):
    path = tmp_path / "import.db"
    init_db(path)
    with transaction(path) as connection:
        seed_content(connection)
        connection.execute(
            """
            INSERT INTO problems(id, leetcode_id, slug, title) VALUES(500, 9999, 'x', 'X')
            """
        )
        connection.execute(
            """
            INSERT INTO attempt_events(id, problem_id, occurred_on, result, source, created_at)
            VALUES('evidence-1', 500, '2026-07-01', 'green', 'web', '2026-07-01T10:00:00')
            """
        )
    with transaction(path) as connection:
        import_outtalent(connection)
    with connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0] == 1
