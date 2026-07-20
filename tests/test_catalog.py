from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.db import transaction
from app.main import app
from app.repository import ensure_problem, problem_catalog, problem_detail
from app.roadmap import parse_roadmap


def test_roadmap_parser_extracts_named_problems_without_labels(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(
        """## Week 0 — Start
- **Critical Connections in a Network** — learn
**Output:** baseline
## Week 1 — Graphs
| Mon | **Clone Graph** — traversal |
**Exit condition:** explain it
""",
        encoding="utf-8",
    )
    entries = parse_roadmap(plan)
    assert [entry.title for entry in entries] == [
        "Critical Connections in a Network",
        "Clone Graph",
    ]
    assert entries[0].pattern_id == "graph/low-link-bridges"


def test_catalog_is_filtered_and_paginated_server_side(db_path):
    now = datetime.now().isoformat()
    with transaction(db_path) as connection:
        for number in range(250):
            problem_id = ensure_problem(
                connection,
                leetcode_id=None,
                slug=f"scale-problem-{number:03d}",
                title=f"Scale Problem {number:03d}",
                url=None,
                pattern_id="dp/one-dimensional" if number % 2 else "graph/traversal",
            )
            connection.execute(
                """
                INSERT INTO queue_items(
                  problem_id, state, priority, roadmap_week, roadmap_position,
                  source, created_at, updated_at
                ) VALUES(?, 'backlog', ?, ?, ?, 'scale-test', ?, ?)
                """,
                (problem_id, number, number // 20, number % 20, now, now),
            )

        first = problem_catalog(connection, scope="queue", page=1, page_size=25)
        eleventh = problem_catalog(connection, scope="queue", page=10, page_size=25)
        filtered = problem_catalog(
            connection,
            scope="queue",
            search="149",
            pattern="dp/one-dimensional",
            page_size=25,
        )

    assert first["total"] == 250
    assert len(first["items"]) == 25
    assert len(eleventh["items"]) == 25
    assert first["pages"] == 10
    assert first["status_counts"]["backlog"] == 250
    assert [item["title"] for item in filtered["items"]] == ["Scale Problem 149"]


def test_problem_detail_attaches_only_matching_lesson(db_path):
    with transaction(db_path) as connection:
        critical = connection.execute(
            "SELECT id FROM problems WHERE slug='critical-connections-in-a-network'"
        ).fetchone()[0]
        generic = ensure_problem(
            connection,
            leetcode_id=None,
            slug="clone-graph",
            title="Clone Graph",
            url=None,
            pattern_id="graph/traversal",
        )
        critical_detail = problem_detail(connection, critical)
        generic_detail = problem_detail(connection, generic)
        assert critical_detail is not None and critical_detail["lesson"] is not None
        assert generic_detail is not None and generic_detail["lesson"] is None


def test_queue_bulk_update_and_invalid_status(db_path):
    with transaction(db_path) as connection:
        problem_id = ensure_problem(
            connection,
            leetcode_id=None,
            slug="queue-update-target",
            title="Queue Update Target",
            url=None,
            pattern_id="graph/traversal",
        )
    with TestClient(app) as client:
        response = client.put("/api/queue", json={"problem_ids": [problem_id], "state": "blocked"})
        assert response.status_code == 200
        assert response.json()["updated"] == 1
        blocked = client.get("/api/problems", params={"status": "blocked", "scope": "queue"}).json()
        assert blocked["items"][0]["id"] == problem_id
        assert client.get("/api/problems", params={"status": "invented"}).status_code == 422
