from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "interview-prep.db"

# Baseline schema (migrations 1-2 in already-deployed databases).
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

# Migration 3: normalized curriculum + learning schema. Everything is additive;
# nothing in migrations 1-2 is altered or dropped, so existing evidence survives.
LEARNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS curricula (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('formal', 'supplemental')),
    priority INTEGER NOT NULL DEFAULT 100,
    description TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS curriculum_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curriculum_id TEXT NOT NULL REFERENCES curricula(id),
    import_key TEXT NOT NULL UNIQUE,
    problem_id INTEGER REFERENCES problems(id),
    item_kind TEXT NOT NULL DEFAULT 'problem'
        CHECK(item_kind IN ('problem', 'reading', 'mock', 'placeholder', 'feedback')),
    section TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    week_label TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    title_raw TEXT NOT NULL,
    status_seen TEXT,
    points_seen REAL,
    source_screenshot TEXT,
    confidence TEXT NOT NULL DEFAULT 'high' CHECK(confidence IN ('high', 'medium', 'low')),
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_curriculum_items_curriculum
ON curriculum_items(curriculum_id, position);
CREATE INDEX IF NOT EXISTS ix_curriculum_items_problem ON curriculum_items(problem_id);
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'technique'
        CHECK(kind IN ('pattern', 'technique', 'concept', 'meta')),
    description TEXT NOT NULL DEFAULT '',
    parent_id TEXT REFERENCES skills(id),
    provenance TEXT NOT NULL DEFAULT 'curated',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_edges (
    from_skill TEXT NOT NULL REFERENCES skills(id),
    to_skill TEXT NOT NULL REFERENCES skills(id),
    edge_type TEXT NOT NULL CHECK(edge_type IN ('prerequisite', 'related')),
    weight REAL NOT NULL DEFAULT 1.0,
    provenance TEXT NOT NULL DEFAULT 'curated',
    PRIMARY KEY (from_skill, to_skill, edge_type)
);
CREATE TABLE IF NOT EXISTS problem_skills (
    problem_id INTEGER NOT NULL REFERENCES problems(id),
    skill_id TEXT NOT NULL REFERENCES skills(id),
    role TEXT NOT NULL DEFAULT 'core' CHECK(role IN ('core', 'supporting', 'variation')),
    weight REAL NOT NULL DEFAULT 1.0,
    provenance TEXT NOT NULL DEFAULT 'curated',
    PRIMARY KEY (problem_id, skill_id)
);
CREATE INDEX IF NOT EXISTS ix_problem_skills_skill ON problem_skills(skill_id);
CREATE TABLE IF NOT EXISTS error_types (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    parent_id TEXT REFERENCES error_types(id),
    description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS attempt_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL REFERENCES attempt_events(id),
    error_type_id TEXT NOT NULL REFERENCES error_types(id),
    detail TEXT NOT NULL DEFAULT '',
    provenance TEXT NOT NULL DEFAULT 'reported' CHECK(provenance IN ('reported', 'backfill')),
    created_at TEXT NOT NULL,
    UNIQUE (attempt_id, error_type_id)
);
CREATE TABLE IF NOT EXISTS learner_skill_states (
    skill_id TEXT NOT NULL REFERENCES skills(id),
    dimension TEXT NOT NULL CHECK(dimension IN
        ('recognition', 'derivation', 'implementation', 'testing', 'explanation', 'retention')),
    state TEXT NOT NULL CHECK(state IN
        ('no_evidence', 'fragile', 'developing', 'independent', 'decaying', 'blocked')),
    evidence_count INTEGER NOT NULL DEFAULT 0,
    independent_count INTEGER NOT NULL DEFAULT 0,
    last_evidence_on TEXT,
    stability_days REAL,
    facts_json TEXT NOT NULL DEFAULT '[]',
    policy_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (skill_id, dimension)
);
CREATE TABLE IF NOT EXISTS learning_decisions (
    id TEXT PRIMARY KEY,
    decided_on TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'daily_recommendation',
    policy_version TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    selected_problem_id INTEGER REFERENCES problems(id),
    selected_json TEXT NOT NULL DEFAULT '{}',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    rationale_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_learning_decisions_date ON learning_decisions(decided_on, kind);
"""

# Migration 5: practice sessions. A session is an execution context (scheduled or
# ad hoc paper practice); attempt_events stay the only evidence of record. Additive:
# existing attempt rows keep session_id NULL and no evidence table is rebuilt.
SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_sessions (
    id TEXT PRIMARY KEY,
    problem_id INTEGER NOT NULL REFERENCES problems(id),
    assignment_id TEXT REFERENCES assignments(id),
    origin TEXT NOT NULL CHECK(origin IN ('scheduled', 'ad_hoc')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'abandoned')),
    mode TEXT NOT NULL DEFAULT 'paper practice',
    goal TEXT NOT NULL DEFAULT '',
    timebox_minutes INTEGER NOT NULL DEFAULT 35,
    highest_hint TEXT CHECK(highest_hint IN ('H1', 'H2', 'H3', 'H4')),
    request_id TEXT UNIQUE,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK ((origin = 'scheduled') = (assignment_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS ix_practice_sessions_problem_status
ON practice_sessions(problem_id, status);
CREATE INDEX IF NOT EXISTS ix_practice_sessions_assignment ON practice_sessions(assignment_id);
CREATE TABLE IF NOT EXISTS session_hint_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES practice_sessions(id),
    level TEXT NOT NULL CHECK(level IN ('H1', 'H2', 'H3', 'H4')),
    occurred_at TEXT NOT NULL,
    UNIQUE (session_id, level)
);
ALTER TABLE attempt_events ADD COLUMN session_id TEXT REFERENCES practice_sessions(id);
CREATE INDEX IF NOT EXISTS ix_attempts_session ON attempt_events(session_id);
"""

# Migration 6: integrity guards for the session layer. Additive only: request_log
# gains nullable ownership columns (pre-upgrade rows keep NULL and stay valid), and
# the triggers constrain new writes without validating or rewriting existing rows.
# The cross-table invariant — a scheduled session executes its assignment's problem —
# cannot live in a CHECK constraint (SQLite forbids subqueries there), so triggers
# enforce it at every insert and at any rewrite of the pairing columns.
INTEGRITY_SCHEMA = """
ALTER TABLE request_log ADD COLUMN scope TEXT;
ALTER TABLE request_log ADD COLUMN fingerprint TEXT;
ALTER TABLE request_log ADD COLUMN updated_at TEXT;
CREATE TRIGGER IF NOT EXISTS trg_sessions_match_assignment_problem_insert
BEFORE INSERT ON practice_sessions
FOR EACH ROW
WHEN NEW.assignment_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'practice session problem does not match assignment problem')
    WHERE (
        SELECT problem_id FROM assignments WHERE id = NEW.assignment_id
    ) IS NOT NEW.problem_id;
END;
CREATE TRIGGER IF NOT EXISTS trg_sessions_match_assignment_problem_update
BEFORE UPDATE OF problem_id, assignment_id ON practice_sessions
FOR EACH ROW
WHEN NEW.assignment_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'practice session problem does not match assignment problem')
    WHERE (
        SELECT problem_id FROM assignments WHERE id = NEW.assignment_id
    ) IS NOT NEW.problem_id;
END;
"""


# Hierarchical error taxonomy. Top-level ids intentionally match the legacy
# failure_tag vocabulary ('bugs' maps to 'testing') so the backfill is honest.
ERROR_TYPE_SEED = [
    ("recognition", "Pattern recognition", None, "Did not identify which technique applies."),
    ("recognition/wrong-pattern", "Committed to the wrong pattern", "recognition", ""),
    ("recognition/no-signal", "Missed the recognition signal", "recognition", ""),
    ("derivation", "Derivation", None, "Could not derive state, transition, or invariant."),
    ("derivation/state-definition", "Imprecise state definition", "derivation", ""),
    ("derivation/transition", "Wrong transition or recurrence", "derivation", ""),
    ("derivation/invariant", "Invariant never stated", "derivation", ""),
    ("implementation", "Implementation", None, "Knew the idea but could not code it."),
    ("implementation/off-by-one", "Index / off-by-one", "implementation", ""),
    ("implementation/data-structure", "Wrong data structure use", "implementation", ""),
    ("implementation/recursion", "Recursion mechanics", "implementation", ""),
    ("testing", "Testing & edge cases", None, "Bug or edge case survived to submission."),
    ("testing/edge-case", "Unhandled edge case", "testing", ""),
    ("testing/no-verification", "Skipped self-verification", "testing", ""),
    ("complexity", "Complexity analysis", None, "Could not analyze or meet complexity bounds."),
    ("communication", "Explanation", None, "Could not explain the approach aloud."),
]

# Legacy attempt_events.failure_tag -> error_types.id
FAILURE_TAG_TO_ERROR = {
    "recognition": "recognition",
    "derivation": "derivation",
    "implementation": "implementation",
    "bugs": "testing",
    "complexity": "complexity",
    "communication": "communication",
}


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


def _begin_schema_migration(connection: sqlite3.Connection, script: str) -> None:
    """Run a schema script in a transaction left open for its version marker.

    sqlite3.executescript() otherwise commits an existing transaction first. Putting
    BEGIN in the script keeps DDL, seeds/backfills, and the migration marker atomic.
    """
    connection.executescript(f"BEGIN IMMEDIATE;\n{script}")


def _migrate_baseline(connection: sqlite3.Connection) -> None:
    _begin_schema_migration(connection, SCHEMA)


def _migrate_baseline_marker(connection: sqlite3.Connection) -> None:
    # Historical marker: deployed databases recorded version 2 for the
    # hint_events/request_log additions that now live in the baseline script.
    _begin_schema_migration(connection, SCHEMA)


def _migrate_learning_schema(connection: sqlite3.Connection) -> None:
    _begin_schema_migration(connection, LEARNING_SCHEMA)
    seed_error_types(connection)


def _migrate_learning_backfill(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    backfill_pattern_skills(connection)
    backfill_attempt_errors(connection)


def _migrate_sessions(connection: sqlite3.Connection) -> None:
    _begin_schema_migration(connection, SESSION_SCHEMA)


def _migrate_integrity(connection: sqlite3.Connection) -> None:
    _begin_schema_migration(connection, INTEGRITY_SCHEMA)


def seed_error_types(connection: sqlite3.Connection) -> None:
    for error_id, title, parent, description in ERROR_TYPE_SEED:
        connection.execute(
            """
            INSERT INTO error_types(id, title, parent_id, description)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title, parent_id=excluded.parent_id,
              description=excluded.description
            """,
            (error_id, title, parent, description),
        )


def backfill_pattern_skills(connection: sqlite3.Connection) -> None:
    """Coarse backfill: every legacy pattern becomes a pattern-kind skill and every
    problem classified under it gets a problem_skills row. Idempotent; never
    overwrites curated rows."""
    from datetime import datetime

    now = datetime.now().isoformat()
    patterns = connection.execute("SELECT id, title, description FROM patterns").fetchall()
    for pattern in patterns:
        connection.execute(
            """
            INSERT OR IGNORE INTO skills(id, title, kind, description, provenance, created_at)
            VALUES(?, ?, 'pattern', ?, 'pattern-backfill', ?)
            """,
            (pattern["id"], pattern["title"], pattern["description"], now),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO problem_skills(problem_id, skill_id, role, weight, provenance)
        SELECT p.id, p.pattern_id, 'core', 0.6, 'pattern-backfill'
        FROM problems p
        JOIN skills s ON s.id = p.pattern_id
        WHERE p.pattern_id IS NOT NULL
        """
    )


def backfill_attempt_errors(connection: sqlite3.Connection) -> None:
    """Map legacy attempt_events.failure_tag to structured attempt_errors rows.
    'none'/'unspecified' record no error. Idempotent via UNIQUE(attempt_id, error_type_id)."""
    from datetime import datetime

    now = datetime.now().isoformat()
    rows = connection.execute(
        "SELECT id, failure_tag FROM attempt_events WHERE failure_tag IS NOT NULL"
    ).fetchall()
    for row in rows:
        error_id = FAILURE_TAG_TO_ERROR.get(row["failure_tag"])
        if error_id is None:
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO attempt_errors(
              attempt_id, error_type_id, detail, provenance, created_at
            ) VALUES(?, ?, 'backfilled from attempt_events.failure_tag', 'backfill', ?)
            """,
            (row["id"], error_id, now),
        )


# Forward-only migration registry. Never reorder or edit an applied migration;
# add a new version instead. Versions 1-2 match already-deployed databases.
MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "baseline schema", _migrate_baseline),
    (2, "baseline marker (hint/request log)", _migrate_baseline_marker),
    (3, "curriculum + learning schema", _migrate_learning_schema),
    (4, "pattern-skill and failure-tag backfill", _migrate_learning_backfill),
    (5, "practice sessions + session hint events", _migrate_sessions),
    (6, "idempotency ownership + scheduled-session consistency guards", _migrate_integrity),
]

LATEST_VERSION = MIGRATIONS[-1][0]


class MigrationError(RuntimeError):
    pass


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def apply_migrations(connection: sqlite3.Connection) -> list[int]:
    """Apply pending migrations in version order. Returns newly applied versions.

    Forward-only: there are no down migrations, and a database stamped with a
    version newer than this code refuses to run rather than guessing.
    """
    applied = applied_versions(connection)
    unknown = applied - {version for version, _, _ in MIGRATIONS}
    if unknown:
        raise MigrationError(
            f"database contains unknown migration versions {sorted(unknown)}; "
            "refusing to run older code against a newer schema"
        )
    newly_applied: list[int] = []
    for version, _name, apply in MIGRATIONS:
        if version in applied:
            continue
        try:
            apply(connection)
            if not connection.in_transaction:
                raise MigrationError(f"migration {version} did not open a transaction")
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES(?, datetime('now'))",
                (version,),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        newly_applied.append(version)
    return newly_applied


def init_db(path: Path | None = None) -> list[int]:
    with connect(path) as connection:
        return apply_migrations(connection)


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
