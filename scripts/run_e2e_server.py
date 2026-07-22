#!/usr/bin/env python3
"""Hermetic Playwright server: serve the new build against a disposable copy of the
live database so end-to-end runs never touch real evidence.

- Copies INTERVIEW_PREP_E2E_SOURCE (default data/interview-prep.db) to
  data/e2e/interview-prep-e2e.db, or starts empty if the source is missing.
- Applies migrations, seeds content, imports the Outtalent curriculum.
- Guarantees an active assignment so the Solve-room flows are testable.
- Strips the legacy-coach env bridge so nothing shells out to the real tracker.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PORT = int(os.getenv("INTERVIEW_PREP_E2E_PORT", "8788"))
TARGET = ROOT / "data" / "e2e" / "interview-prep-e2e.db"


def prepare_database() -> None:
    default_source = ROOT / "data" / "interview-prep.db"
    canonical_source = ROOT.parents[1] / "interview-prep-os" / "data" / "interview-prep.db"
    if not default_source.exists() and canonical_source.exists():
        default_source = canonical_source
    source = Path(os.getenv("INTERVIEW_PREP_E2E_SOURCE", default_source))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        stale = TARGET.parent / (TARGET.name + suffix)
        if stale.exists():
            stale.unlink()
    if source.exists():
        with sqlite3.connect(source) as src, sqlite3.connect(TARGET) as dst:
            src.backup(dst)

    os.environ["INTERVIEW_PREP_DB"] = str(TARGET)
    from app.curriculum import import_outtalent
    from app.db import init_db, transaction
    from app.repository import seed_content

    init_db(TARGET)
    with transaction(TARGET) as connection:
        seed_content(connection)
        import_outtalent(connection)
        ensure_active_assignment(connection)


def ensure_active_assignment(connection: sqlite3.Connection) -> None:
    active = connection.execute(
        "SELECT 1 FROM assignments WHERE status IN ('active', 'carryover') LIMIT 1"
    ).fetchone()
    if active:
        return
    problem = connection.execute("SELECT id, title FROM problems ORDER BY id LIMIT 1").fetchone()
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
