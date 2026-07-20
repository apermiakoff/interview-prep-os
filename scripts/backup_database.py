#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backup import backup  # noqa: E402


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    source = Path(os.getenv("INTERVIEW_PREP_DB", root / "data" / "interview-prep.db"))
    destination = Path(os.getenv("INTERVIEW_PREP_BACKUPS", root / "data" / "backups"))
    backup(source, destination)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    for path in destination.glob("interview-prep-*.db"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        if modified < cutoff:
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
