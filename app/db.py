from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "interview-prep.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    recognition_signals TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS problems (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leetcode_id INTEGER UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    url TEXT,
    difficulty TEXT,
    pattern_id TEXT REFERENCES patterns(id)
);
CREATE INDEX IF NOT EXISTS ix_problems_title ON problems(title);
CREATE INDEX IF NOT EXISTS ix_problems_pattern ON problems(pattern_id);
CREATE TABLE IF NOT EXISTS queue_items (
    problem_id INTEGER PRIMARY KEY REFERENCES problems(id),
    state TEXT NOT NULL DEFAULT 'backlog',
    priority INTEGER NOT NULL DEFAULT 500,
    roadmap_week INTEGER,
    roadmap_position INTEGER,
    source TEXT NOT NULL DEFAULT 'manual',
    scheduled_for TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_queue_state_priority
ON queue_items(state, priority, roadmap_week, roadmap_position);
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id),
    assigned_on TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    timebox_minutes INTEGER NOT NULL DEFAULT 35,
    goal TEXT NOT NULL,
    hints_json TEXT NOT NULL DEFAULT '{}',
    bujo_json TEXT NOT NULL DEFAULT '{}',
    highest_hint TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_assignments_status_date ON assignments(status, assigned_on);
CREATE TABLE IF NOT EXISTS attempt_events (
    id TEXT PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id),
    assignment_id TEXT REFERENCES assignments(id),
    occurred_on TEXT NOT NULL,
    result TEXT NOT NULL CHECK(result IN ('green','yellow','red','skipped')),
    accepted INTEGER NOT NULL DEFAULT 0,
    independent INTEGER NOT NULL DEFAULT 0,
    duration_minutes INTEGER,
    highest_hint TEXT,
    failure_tag TEXT,
    explanation_score REAL,
    source TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attempts_problem_date ON attempt_events(problem_id, occurred_on);
CREATE INDEX IF NOT EXISTS ix_attempts_result_date ON attempt_events(result, occurred_on);
CREATE TABLE IF NOT EXISTS memory_states (
    problem_id INTEGER PRIMARY KEY REFERENCES problems(id),
    stability_days REAL NOT NULL,
    difficulty REAL NOT NULL,
    retrievability REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    last_attempt_on TEXT NOT NULL,
    next_due TEXT NOT NULL,
    last_result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id),
    due_on TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    source_attempt_id TEXT REFERENCES attempt_events(id),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_reviews_due ON reviews(status, due_on);
CREATE TABLE IF NOT EXISTS profile_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(username, retrieved_at)
);
CREATE TABLE IF NOT EXISTS notes (
    assignment_id TEXT PRIMARY KEY REFERENCES assignments(id),
    content TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_log (
    request_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hint_events (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL REFERENCES assignments(id),
    level TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
"""


def database_path() -> Path:
    return Path(os.getenv("INTERVIEW_PREP_DB", DEFAULT_DB)).expanduser()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def init_db(path: Path | None = None) -> None:
    with connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES(1, datetime('now'))
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations(version, applied_at)
            VALUES(2, datetime('now'))
            """
        )


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
