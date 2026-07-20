from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def backup(source: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"interview-prep-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m app.backup SOURCE_DB BACKUP_DIR")
    print(backup(Path(sys.argv[1]), Path(sys.argv[2])))
