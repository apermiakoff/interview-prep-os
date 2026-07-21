from __future__ import annotations

import sqlite3

import pytest

import app.db as db_module
from app.db import (
    LATEST_VERSION,
    MIGRATIONS,
    SCHEMA,
    MigrationError,
    connect,
    init_db,
)

LEARNING_TABLES = {
    "curricula",
    "curriculum_items",
    "skills",
    "skill_edges",
    "problem_skills",
    "error_types",
    "attempt_errors",
    "learner_skill_states",
    "learning_decisions",
}


def _make_legacy_db(path):
    """Reproduce a deployed pre-upgrade database: baseline schema, versions 1-2
    stamped, and personal evidence present."""
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.executescript(
        """
        INSERT INTO schema_migrations(version, applied_at) VALUES(1, '2026-07-20 13:22:51');
        INSERT INTO schema_migrations(version, applied_at) VALUES(2, '2026-07-20 14:32:12');
        INSERT INTO patterns(id, title, description, created_at)
        VALUES('graph/low-link-bridges', 'Low-link bridges', 'desc', '2026-07-20');
        INSERT INTO problems(id, leetcode_id, slug, title, pattern_id)
        VALUES(1, 1192, 'critical-connections-in-a-network', 'Critical Connections in a Network',
               'graph/low-link-bridges');
        INSERT INTO attempt_events(
          id, problem_id, occurred_on, result, accepted, independent, highest_hint,
          failure_tag, source, created_at
        ) VALUES('legacy-attempt-1', 1, '2026-07-18', 'red', 0, 0, 'H4', 'derivation',
                 'telegram_button', '2026-07-18T10:00:00');
        INSERT INTO memory_states(
          problem_id, stability_days, difficulty, retrievability, evidence_count,
          last_attempt_on, next_due, last_result
        ) VALUES(1, 1.0, 6.4, 1.0, 1, '2026-07-18', '2026-07-19', 'red');
        """
    )
    connection.commit()
    connection.close()


def test_upgrade_preserves_data_and_adds_learning_schema(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_db(path)
    applied = init_db(path)
    assert applied == [version for version, _, _ in MIGRATIONS if version > 2]
    with connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables >= LEARNING_TABLES
        # Personal evidence survives untouched.
        assert connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_states").fetchone()[0] == 1
        assert connection.execute("SELECT stability_days FROM memory_states").fetchone()[0] == 1.0
        # Backfill: pattern became a skill, problem mapped, failure tag structured.
        skill = connection.execute(
            "SELECT provenance FROM skills WHERE id='graph/low-link-bridges'"
        ).fetchone()
        assert skill is not None and skill[0] == "pattern-backfill"
        mapping = connection.execute(
            "SELECT role, provenance FROM problem_skills WHERE problem_id=1"
        ).fetchone()
        assert mapping is not None and mapping[1] == "pattern-backfill"
        error = connection.execute(
            """
            SELECT error_type_id, provenance
            FROM attempt_errors
            WHERE attempt_id='legacy-attempt-1'
            """
        ).fetchone()
        assert error is not None and error[0] == "derivation" and error[1] == "backfill"


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "fresh.db"
    first = init_db(path)
    assert first == [version for version, _, _ in MIGRATIONS]
    assert init_db(path) == []
    with connect(path) as connection:
        versions = [
            row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY 1")
        ]
    assert versions == [version for version, _, _ in MIGRATIONS]
    assert versions[-1] == LATEST_VERSION


def test_session_migration_adds_tables_and_leaves_evidence_untouched(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_db(path)
    init_db(path)
    with connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"practice_sessions", "session_hint_events"} <= tables
        # Historical evidence survives and predates sessions: session_id is NULL.
        attempt = connection.execute(
            "SELECT session_id, result FROM attempt_events WHERE id='legacy-attempt-1'"
        ).fetchone()
        assert attempt["result"] == "red" and attempt["session_id"] is None
        # Origin/assignment consistency is enforced by the schema itself.
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO practice_sessions(
                  id, problem_id, origin, status, started_at, updated_at
                ) VALUES('bad-session', 1, 'scheduled', 'active',
                         datetime('now'), datetime('now'))
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO practice_sessions(
                  id, problem_id, assignment_id, origin, status, started_at, updated_at
                ) VALUES('bad-session-2', 1, 'missing-assignment', 'ad_hoc', 'active',
                         datetime('now'), datetime('now'))
                """
            )


def test_forward_only_guard_refuses_newer_database(tmp_path):
    path = tmp_path / "future.db"
    init_db(path)
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(99, datetime('now'))"
        )
    with pytest.raises(MigrationError, match="unknown migration versions"):
        init_db(path)


def test_failed_migration_rolls_back_schema_and_marker(tmp_path, monkeypatch):
    path = tmp_path / "failed.db"
    init_db(path)

    def fail_halfway(connection):
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE partial_migration(id INTEGER PRIMARY KEY);
            INSERT INTO table_that_does_not_exist VALUES(1);
            """
        )

    failing_version = LATEST_VERSION + 1
    monkeypatch.setattr(
        db_module,
        "MIGRATIONS",
        (*MIGRATIONS, (failing_version, "forced failure", fail_halfway)),
    )

    with pytest.raises(sqlite3.OperationalError):
        init_db(path)

    with connect(path) as connection:
        partial = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partial_migration'"
        ).fetchone()
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    assert partial is None
    assert failing_version not in versions
