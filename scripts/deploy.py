#!/usr/bin/env python3
"""Verified production deployment with a mandatory pre-migration backup."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backup import backup  # noqa: E402


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def wait_for_health(url: str, attempts: int = 30) -> dict:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                payload = json.load(response)
                if response.status == 200 and payload.get("status") == "ok":
                    return payload
        except Exception as error:  # deployment may still be starting
            last_error = error
        time.sleep(1)
    raise RuntimeError(f"deployment health check failed: {last_error}")


def main() -> int:
    database = Path(os.getenv("INTERVIEW_PREP_DB", ROOT / "data" / "interview-prep.db"))
    backup_dir = Path(os.getenv("INTERVIEW_PREP_BACKUPS", ROOT / "data" / "backups"))
    health_url = os.getenv("INTERVIEW_PREP_HEALTH_URL", "http://127.0.0.1:8765/api/health")

    backup_path = backup(database, backup_dir)
    print(f"VERIFIED_PRE_MIGRATION_BACKUP={backup_path}", flush=True)
    try:
        run("docker", "compose", "build")
        run("docker", "compose", "up", "-d", "--force-recreate")
        payload = wait_for_health(health_url)
    except Exception:
        print(
            "Deployment failed. Do not start an older image against the migrated database; "
            f"restore {backup_path} first.",
            file=sys.stderr,
        )
        raise
    print(json.dumps({"health": payload, "backup": str(backup_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
