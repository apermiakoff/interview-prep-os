#!/usr/bin/env python3
"""Portable, key-free backup and guarded restore for community data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

CORE_NAME = "core.sqlite3"
AI_NAME = "ai.sqlite3"
MANIFEST_NAME = "manifest.json"


def check(path: Path, migration_table: str) -> int:
    if not path.is_file():
        raise ValueError(f"database not found: {path}")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        result = db.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"quick_check failed for {path.name}")
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (migration_table,)
        ).fetchone()
        if not table:
            raise ValueError(f"missing {migration_table} in {path.name}")
        query = f"SELECT COALESCE(MAX(version),0) FROM {migration_table}"
        return int(db.execute(query).fetchone()[0])


def snapshot(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_backup(core: Path, ai: Path, output: Path) -> Path:
    core_version = check(core, "schema_migrations")
    ai_version = check(ai, "ai_schema_migrations")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="interview-prep-export-") as raw:
        temp = Path(raw)
        core_copy, ai_copy = temp / CORE_NAME, temp / AI_NAME
        snapshot(core, core_copy)
        snapshot(ai, ai_copy)
        check(core_copy, "schema_migrations")
        check(ai_copy, "ai_schema_migrations")
        manifest = {
            "format": "interview-prep-community-backup",
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "contains_secrets": False,
            "databases": {
                "core": {
                    "file": CORE_NAME,
                    "schema_version": core_version,
                    "sha256": digest(core_copy),
                },
                "ai": {"file": AI_NAME, "schema_version": ai_version, "sha256": digest(ai_copy)},
            },
        }
        (temp / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in (MANIFEST_NAME, CORE_NAME, AI_NAME):
                archive.write(temp / name, name)
    return output


def restore_backup(archive_path: Path, core: Path, ai: Path, overwrite: bool = False) -> None:
    if (core.exists() or ai.exists()) and not overwrite:
        raise ValueError("destination exists; pass --overwrite to replace both databases")
    with tempfile.TemporaryDirectory(prefix="interview-prep-restore-") as raw:
        temp = Path(raw)
        with zipfile.ZipFile(archive_path) as archive:
            if set(archive.namelist()) != {MANIFEST_NAME, CORE_NAME, AI_NAME}:
                raise ValueError("backup contains unexpected or missing files")
            archive.extractall(temp)
        manifest = json.loads((temp / MANIFEST_NAME).read_text(encoding="utf-8"))
        if (
            manifest.get("format") != "interview-prep-community-backup"
            or manifest.get("version") != 1
        ):
            raise ValueError("unsupported backup manifest")
        databases = (
            ("core", CORE_NAME, "schema_migrations"),
            ("ai", AI_NAME, "ai_schema_migrations"),
        )
        for key, name, table in databases:
            path = temp / name
            if digest(path) != manifest["databases"][key]["sha256"]:
                raise ValueError(f"{key} checksum mismatch")
            if check(path, table) != manifest["databases"][key]["schema_version"]:
                raise ValueError(f"{key} schema mismatch")
        core.parent.mkdir(parents=True, exist_ok=True)
        ai.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(temp / CORE_NAME, core)
        shutil.copy2(temp / AI_NAME, ai)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    restore = sub.add_parser("restore")
    for command in (backup, restore):
        command.add_argument("--core", type=Path, required=True)
        command.add_argument("--ai", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = create_backup(args.core, args.ai, args.output)
            print(result)
        else:
            restore_backup(args.input, args.core, args.ai, args.overwrite)
            print("Restore complete")
    except (
        ValueError,
        OSError,
        sqlite3.Error,
        zipfile.BadZipFile,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
