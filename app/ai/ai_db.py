from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

AI_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_schema_migrations(
 version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_profiles(
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, base_url TEXT NOT NULL,
 credential_hint TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS context_snapshots(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL, scope_id TEXT NOT NULL, schema_version TEXT NOT NULL,
 content_json TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL CHECK(scope IN ('problem','session')),
 scope_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_conversation_scope ON conversations(scope, scope_id, created_at);
CREATE TABLE IF NOT EXISTS messages(
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 idempotency_key TEXT, run_id TEXT, created_at TEXT NOT NULL,
 UNIQUE(conversation_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id), kind TEXT NOT NULL,
 scope TEXT NOT NULL, scope_id TEXT NOT NULL, status TEXT NOT NULL,
 request_json TEXT NOT NULL, context_snapshot_id TEXT NOT NULL REFERENCES context_snapshots(id),
 provider TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, schema_version TEXT,
 cache_key TEXT, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
 lease_owner TEXT, lease_until TEXT, error_code TEXT, error_message TEXT,
 reserved_tokens INTEGER NOT NULL DEFAULT 0,
 cancel_requested INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 completed_at TEXT
);
CREATE INDEX IF NOT EXISTS ai_runs_claim ON runs(status, lease_until, created_at);
CREATE TABLE IF NOT EXISTS run_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
 event_type TEXT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_events_run ON run_events(run_id, id);
CREATE TABLE IF NOT EXISTS cache_entries(
 cache_key TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_ledger(
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 total_tokens INTEGER NOT NULL, cost_micros INTEGER, occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_usage_month ON usage_ledger(occurred_at);
CREATE TABLE IF NOT EXISTS artifacts(
 id TEXT PRIMARY KEY, scope TEXT NOT NULL, scope_id TEXT NOT NULL, kind TEXT NOT NULL,
 version INTEGER NOT NULL, schema_version TEXT NOT NULL, content_json TEXT NOT NULL,
 run_id TEXT NOT NULL, context_snapshot_id TEXT NOT NULL, prompt_version TEXT NOT NULL,
 provider TEXT NOT NULL, model TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(scope, scope_id, kind, version)
);
CREATE TABLE IF NOT EXISTS learning_hypotheses(
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
 hypothesis_type TEXT NOT NULL,
 status TEXT NOT NULL, confidence REAL NOT NULL, statement TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypothesis_evidence(
 hypothesis_id TEXT NOT NULL REFERENCES learning_hypotheses(id), evidence_ref TEXT NOT NULL,
 PRIMARY KEY(hypothesis_id, evidence_ref)
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def migrate(path: Path) -> list[int]:
    applied: list[int] = []
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            # executescript issues an implicit COMMIT. Execute complete statements
            # individually so schema and migration markers are truly atomic.
            statement = ""
            for line in AI_SCHEMA.splitlines():
                statement += f"{line}\n"
                if sqlite3.complete_statement(statement):
                    connection.execute(statement)
                    statement = ""
            for version in (1, 2):
                if not connection.execute(
                    "SELECT 1 FROM ai_schema_migrations WHERE version=?", (version,)
                ).fetchone():
                    if version == 2:
                        columns = {
                            row["name"] for row in connection.execute("PRAGMA table_info(runs)")
                        }
                        if "reserved_tokens" not in columns:
                            connection.execute(
                                "ALTER TABLE runs ADD COLUMN reserved_tokens "
                                "INTEGER NOT NULL DEFAULT 0"
                            )
                    connection.execute(
                        "INSERT INTO ai_schema_migrations VALUES(?,?)", (version, now())
                    )
                    applied.append(version)
            if not connection.execute(
                "SELECT 1 FROM ai_schema_migrations WHERE version=3"
            ).fetchone():
                run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
                if "claim_generation" not in run_columns:
                    connection.execute(
                        "ALTER TABLE runs ADD COLUMN claim_generation INTEGER NOT NULL DEFAULT 0"
                    )
                if "estimated_input_tokens" not in run_columns:
                    connection.execute(
                        "ALTER TABLE runs ADD COLUMN estimated_input_tokens "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                event_columns = {
                    row["name"] for row in connection.execute("PRAGMA table_info(run_events)")
                }
                if "claim_generation" not in event_columns:
                    connection.execute(
                        "ALTER TABLE run_events ADD COLUMN claim_generation "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ai_usage_one_per_run ON usage_ledger(run_id)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ai_artifact_one_per_run ON artifacts(run_id)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ai_assistant_one_per_run "
                    "ON messages(run_id) "
                    "WHERE role='assistant'"
                )
                connection.execute("INSERT INTO ai_schema_migrations VALUES(3,?)", (now(),))
                applied.append(3)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return applied


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    with connect(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
