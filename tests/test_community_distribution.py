from __future__ import annotations

import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.ai_db import migrate as migrate_ai
from app.community import bootstrap_community
from app.db import connect, init_db, transaction
from app.main import app
from scripts.community_data import create_backup, restore_backup


def test_docker_context_excludes_all_secret_bearing_paths():
    rules = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "secrets/" in rules
    assert ".community-secrets/" in rules
    assert ".env" in rules
    assert ".env.*" in rules


def test_clean_community_bootstrap_has_catalog_without_evidence(tmp_path):
    database = tmp_path / "fresh.db"
    init_db(database)
    with transaction(database) as connection:
        first = bootstrap_community(connection)
        second = bootstrap_community(connection)
    assert first == second == {"problems": 20, "curriculum": "community-starter"}
    with connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM problems").fetchone()[0] == 20
        assert connection.execute("SELECT COUNT(*) FROM skills").fetchone()[0] > 20
        for table in ("attempt_events", "assignments", "reviews", "profile_snapshots"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_learner_settings_and_hostile_origins(monkeypatch):
    with TestClient(app) as client:
        payload = {
            "display_name": "Community Learner",
            "interview_target": "Backend role",
            "weekly_hours": 7,
            "timezone": "America/New_York",
            "weak_areas": ["graphs"],
            "preferred_language": "Python",
        }
        hostile = client.put(
            "/api/learner-settings", json=payload, headers={"Origin": "https://evil.example"}
        )
        assert hostile.status_code == 403
        hostile_ai = client.post(
            "/api/ai/learning/diagnosis", json={}, headers={"Origin": "https://evil.example"}
        )
        assert hostile_ai.status_code == 403
        saved = client.put("/api/learner-settings", json=payload)
        assert saved.status_code == 200
        assert client.get("/api/bootstrap").json()["learner"]["display_name"] == "Community Learner"


def test_setup_noninteractive_never_exposes_key_or_writes_it_to_env(tmp_path):
    key = "test-secret-not-for-output"
    source = tmp_path / "input-key"
    source.write_text(key)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/community_setup.py",
            "--non-interactive",
            "--enable-ai",
            "--provider",
            "openai",
            "--model",
            "gpt-test",
            "--api-key-file",
            str(source),
            "--root",
            str(tmp_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    env = (tmp_path / ".env.community").read_text()
    secret = tmp_path / ".community-secrets" / "ai_api_key"
    assert key not in env and key not in result.stdout and key not in result.stderr
    assert key not in " ".join(result.args)
    assert secret.read_text() == key
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert "--profile ai" in result.stdout


def test_setup_preserves_existing_key_when_ai_is_disabled(tmp_path):
    source = tmp_path / "input-key"
    source.write_text("keep-this-key\n")
    enabled = [
        sys.executable,
        "scripts/community_setup.py",
        "--non-interactive",
        "--enable-ai",
        "--provider",
        "openai",
        "--model",
        "gpt-test",
        "--api-key-file",
        str(source),
        "--root",
        str(tmp_path),
    ]
    subprocess.run(enabled, check=True, capture_output=True, text=True)
    subprocess.run(
        [
            sys.executable,
            "scripts/community_setup.py",
            "--non-interactive",
            "--root",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    secret = tmp_path / ".community-secrets" / "ai_api_key"
    assert secret.read_text() == "keep-this-key"
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "field,value",
    [
        ("--model", "model\nINJECTED=true"),
        ("--base-url", "https://example.test/v1\nINJECTED=true"),
    ],
)
def test_setup_rejects_multiline_env_values(tmp_path, field, value):
    arguments = [
        sys.executable,
        "scripts/community_setup.py",
        "--non-interactive",
        "--enable-ai",
        "--provider",
        "ollama",
        "--model",
        "safe-model",
        "--root",
        str(tmp_path),
        field,
        value,
    ]
    result = subprocess.run(arguments, capture_output=True, text=True)
    assert result.returncode != 0
    assert not (tmp_path / ".env.community").exists()


def test_setup_rejects_secret_symlink(tmp_path):
    secret_dir = tmp_path / ".community-secrets"
    secret_dir.mkdir()
    target = tmp_path / "must-not-change"
    target.write_text("sentinel")
    (secret_dir / "ai_api_key").symlink_to(target)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/community_setup.py",
            "--non-interactive",
            "--root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert target.read_text() == "sentinel"


def test_backup_restore_both_databases_and_refuses_overwrite(tmp_path):
    core, ai = tmp_path / "core.db", tmp_path / "ai.db"
    init_db(core)
    migrate_ai(ai)
    archive = create_backup(core, ai, tmp_path / "export.zip")
    with zipfile.ZipFile(archive) as value:
        manifest = json.loads(value.read("manifest.json"))
        assert set(value.namelist()) == {"manifest.json", "core.sqlite3", "ai.sqlite3"}
        assert manifest["contains_secrets"] is False
    restored_core, restored_ai = tmp_path / "restored-core.db", tmp_path / "restored-ai.db"
    restore_backup(archive, restored_core, restored_ai)
    assert restored_core.exists() and restored_ai.exists()
    try:
        restore_backup(archive, restored_core, restored_ai)
    except ValueError as exc:
        assert "--overwrite" in str(exc)
    else:
        raise AssertionError("restore should refuse overwrite")
