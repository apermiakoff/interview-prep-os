from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.db import init_db, transaction
from app.repository import ensure_problem, seed_content


@pytest.fixture(autouse=True)
def _isolated_database(tmp_path, monkeypatch):
    """Every test runs against a throwaway database, even tests that never
    request the db_path fixture: booting the FastAPI lifespan must not be able
    to migrate or seed the real data/interview-prep.db."""
    monkeypatch.setenv("INTERVIEW_PREP_DB", str(tmp_path / "isolated.db"))


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setenv("INTERVIEW_PREP_DB", str(path))
    init_db(path)
    with transaction(path) as connection:
        seed_content(connection)
        problem_id = ensure_problem(
            connection,
            leetcode_id=1192,
            slug="critical-connections-in-a-network",
            title="Critical Connections in a Network",
            url="https://leetcode.com/problems/critical-connections-in-a-network/",
            difficulty="Hard",
            pattern_id="graph/low-link-bridges",
        )
        connection.execute(
            """
            INSERT INTO assignments(
              id, problem_id, assigned_on, mode, status, timebox_minutes, goal,
              hints_json, bujo_json, created_at
            ) VALUES('assignment-1', ?, '2026-07-20', 'blind reconstruction retry',
                     'active', 35, 'Reconstruct it.', ?, '{}', ?)
            """,
            (
                problem_id,
                json.dumps(
                    {
                        "H1": "Question one",
                        "H2": "Invariant two",
                        "H3": "Pattern three",
                        "H4": "Walkthrough four",
                    }
                ),
                datetime.now().isoformat(),
            ),
        )
    return path
