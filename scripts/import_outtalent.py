#!/usr/bin/env python3
"""Idempotent import of the Outtalent curriculum artifact + curated skill taxonomy.

Usage:
    uv run python scripts/import_outtalent.py [--db PATH] [--artifact PATH] [--skills PATH]

Safe to re-run: placements are keyed by stable import keys, problems are upserted by
canonical identity, and attempt evidence is never written."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.curriculum import OUTTALENT_ARTIFACT, SKILLS_ARTIFACT, import_outtalent
from app.db import database_path, init_db, transaction
from app.repository import seed_content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=database_path())
    parser.add_argument("--artifact", type=Path, default=OUTTALENT_ARTIFACT)
    parser.add_argument("--skills", type=Path, default=SKILLS_ARTIFACT)
    args = parser.parse_args()

    applied = init_db(args.db)
    with transaction(args.db) as connection:
        seed_content(connection)
        summary = import_outtalent(connection, args.artifact, args.skills)
    summary["db"] = str(args.db)
    summary["migrations_applied"] = applied
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
