from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai.ai_db import connect as ai_connect
from app.ai.ai_db import migrate
from app.ai.config import AIConfig, AIConfigError, validate_base_url
from app.ai.context import learning_snapshot, problem_snapshot, session_snapshot
from app.ai.domain import DiagnosisArtifact, VisualizationArtifact
from app.ai.gateway import ProviderChunk, ProviderResult
from app.ai.worker import Worker
from app.db import connect
from app.main import app
from app.schemas import SessionStart
from app.sessions import start_scheduled_session


class FakeGateway:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.calls = 0

    async def complete(self, **_kwargs) -> ProviderResult:
        self.calls += 1
        return ProviderResult(self.outputs.pop(0), 11, 7, "stop")


class FakeStreamingGateway:
    def __init__(self, pieces: list[str]):
        self.pieces = pieces

    async def stream(self, **_kwargs):
        for piece in self.pieces:
            yield ProviderChunk(text=piece)
        text = "".join(self.pieces)
        yield ProviderChunk(result=ProviderResult(text, 9, 6, "stop"))


def test_ai_migration_is_idempotent(tmp_path):
    path = tmp_path / "ai.db"
    assert migrate(path) == [1, 2, 3]
    assert migrate(path) == []
    with ai_connect(path) as connection:
        names = {row["name"] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert {"runs", "artifacts", "usage_ledger", "learning_hypotheses"} <= names


def test_disabled_and_masked_config(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("INTERVIEW_PREP_AI_ENABLED", "false")
    monkeypatch.setenv("INTERVIEW_PREP_AI_API_KEY", "never-return-this")
    monkeypatch.setenv("INTERVIEW_PREP_AI_DB", str(tmp_path / "ai.db"))
    with TestClient(app) as client:
        status = client.get("/api/ai/status")
        assert status.json()["status"] == "disabled"
        assert "never-return-this" not in status.text
        assert client.post("/api/ai/problems/1/conversations", json={}).status_code == 503


def test_url_policy(monkeypatch):
    with pytest.raises(AIConfigError):
        validate_base_url("https://user:pass@example.com", provider="openai", allow_private=False)
    with pytest.raises(AIConfigError):
        validate_base_url("http://127.0.0.1:8080", provider="openai", allow_private=False)
    assert validate_base_url(
        "http://127.0.0.1:11434", provider="ollama", allow_private=False
    ).endswith("11434")


def test_context_allowlist_and_hidden_hints(db_path):
    session = start_scheduled_session("assignment-1", SessionStart(), db_path)["session"]
    with connect(db_path) as connection:
        problem = problem_snapshot(connection, session["problem_id"])
        snapshot = session_snapshot(connection, session["id"])
    serialized = json.dumps(snapshot)
    assert "raw_json" not in serialized
    assert "profile" not in serialized
    assert "Question one" not in serialized
    assert snapshot["revealed_hints"] == []
    assert len(problem["problem"]["attempt_summaries"]) <= 20


def test_artifact_validation_and_confidence_cap():
    with pytest.raises(ValidationError):
        VisualizationArtifact.model_validate(
            {
                "schema_version": "visualization@1",
                "renderer": "graph-trace@1",
                "title": "x",
                "entities": [],
                "events": [{"op": "execute-js", "targets": ["x"]}],
                "html": "<script>alert(1)</script>",
            }
        )
    diagnosis = DiagnosisArtifact.model_validate(
        {
            "schema_version": "diagnosis@1",
            "observations": ["A failed attempt exists."],
            "hypotheses": [
                {
                    "type": "stuck_point",
                    "status": "likely",
                    "statement": "Transition derivation may be fragile.",
                    "confidence": 0.99,
                    "evidence": [{"id": "attempt:a"}],
                }
            ],
            "interventions": [
                {
                    "action": "Derive one example",
                    "rationale": "Collect evidence",
                    "requires_user_action": True,
                }
            ],
        }
    ).validated_for({"attempt:a"})
    assert diagnosis.hypotheses[0].confidence == 0.65
    with pytest.raises(ValueError):
        diagnosis.validated_for(set())


def test_fake_worker_chat_session_assistance_sse_and_budget(ai_config, db_path, monkeypatch):
    session = start_scheduled_session("assignment-1", SessionStart(), db_path)["session"]
    with TestClient(app) as client:
        conversation = client.post(
            f"/api/ai/sessions/{session['id']}/conversations", json={}
        ).json()
        response = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "Where am I stuck?", "idempotency_key": "message-key-0001"},
        )
        assert response.status_code == 202
        run_id = response.json()["run"]["id"]
        duplicate = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "Where am I stuck?", "idempotency_key": "message-key-0001"},
        )
        assert duplicate.json()["created"] is False
    with connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT ai_assisted FROM practice_sessions WHERE id=?", (session["id"],)
            ).fetchone()["ai_assisted"]
            == 1
        )
    fake = FakeGateway(["Try stating the invariant before choosing a traversal."])
    asyncio.run(Worker(ai_config, fake).run_once())
    with TestClient(app) as client:
        run = client.get(f"/api/ai/runs/{run_id}").json()
        assert run["status"] == "completed"
        stream = client.get(f"/api/ai/runs/{run_id}/events", headers={"Last-Event-ID": "0"})
        assert "event: completed" in stream.text
        assert client.get("/api/ai/usage").json()["tokens_used"] == 18
    constrained = replace(ai_config, monthly_token_budget=ai_config.max_output_tokens)
    monkeypatch.setenv(
        "INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET", str(constrained.monthly_token_budget)
    )
    with TestClient(app) as client:
        rejected = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "Again", "idempotency_key": "message-key-0002"},
        )
    assert rejected.status_code == 402


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (
            "lesson",
            {
                "schema_version": "lesson@1",
                "objectives": ["Recognize bridges"],
                "recognition_signals": ["Removing an edge disconnects"],
                "sections": [
                    {"heading": "Invariant", "body": "Low-link values summarize reachability."}
                ],
                "complexity": {"time": "O(V+E)", "space": "O(V)"},
                "failures": ["Using parent vertex instead of edge"],
                "provenance_notes": ["From supplied skill metadata"],
            },
        ),
        (
            "visualization",
            {
                "schema_version": "visualization@1",
                "renderer": "graph-trace@1",
                "title": "DFS",
                "entities": [{"id": "a", "label": "A", "kind": "node"}],
                "events": [{"op": "visit", "targets": ["a"]}],
            },
        ),
        (
            "diagnosis",
            {
                "schema_version": "diagnosis@1",
                "observations": [],
                "hypotheses": [],
                "interventions": [
                    {
                        "action": "Attempt a trace",
                        "rationale": "Gather evidence",
                        "requires_user_action": True,
                    }
                ],
            },
        ),
    ],
)
def test_fake_worker_artifact_end_to_end_and_cache(ai_config, db_path, kind, payload):
    path = f"/api/ai/problems/1/{kind}"
    request = {"idempotency_key": f"artifact-{kind}-0001", "instructions": "Focus on invariant"}
    with TestClient(app) as client:
        queued = client.post(path, json=request)
        assert queued.status_code == 202, queued.text
        run_id = queued.json()["run"]["id"]
    fake = FakeGateway([json.dumps(payload)])
    asyncio.run(Worker(ai_config, fake).run_once())
    with TestClient(app) as client:
        result = client.get(f"/api/ai/runs/{run_id}").json()
        assert result["artifact"]["content"]["schema_version"].endswith("@1")
        cached = client.post(path, json={**request, "idempotency_key": f"artifact-{kind}-0002"})
        assert cached.json()["created"] is False
        history = client.get("/api/ai/problems/1/artifacts", params={"kind": kind, "limit": 1})
        latest = client.get("/api/ai/problems/1/artifacts/latest", params={"kind": kind})
        assert history.status_code == latest.status_code == 200
        assert history.json()[0]["id"] == latest.json()["id"]
        assert latest.json()["run_id"] == run_id
        assert latest.json()["context_snapshot_id"]
        assert latest.json()["prompt_version"] == "community-ai@1"
    assert fake.calls == 1


def test_artifact_version_history_and_session_retrieval(ai_config, db_path):
    lesson = {
        "schema_version": "lesson@1",
        "objectives": ["Recognize bridges"],
        "recognition_signals": [],
        "sections": [{"heading": "Invariant", "body": "Low links."}],
        "complexity": {"time": "O(V+E)", "space": "O(V)"},
        "failures": [],
        "provenance_notes": [],
    }
    fake = FakeGateway([json.dumps(lesson), json.dumps(lesson)])
    with TestClient(app) as client:
        for index in (1, 2):
            queued = client.post(
                "/api/ai/problems/1/lesson",
                json={
                    "idempotency_key": f"version-key-{index}",
                    "instructions": f"version {index}",
                },
            )
            assert queued.status_code == 202
            asyncio.run(Worker(ai_config, fake).run_once())
        history = client.get(
            "/api/ai/problems/1/artifacts", params={"kind": "lesson", "limit": 10}
        ).json()
        assert [item["version"] for item in history] == [2, 1]

    session = start_scheduled_session("assignment-1", SessionStart(), db_path)["session"]
    diagnosis = {
        "schema_version": "diagnosis@1",
        "observations": [],
        "hypotheses": [],
        "interventions": [
            {"action": "Try a trace", "rationale": "Gather facts", "requires_user_action": True}
        ],
    }
    with TestClient(app) as client:
        queued = client.post(
            f"/api/ai/sessions/{session['id']}/diagnosis",
            json={"idempotency_key": "session-diag-1"},
        )
    asyncio.run(Worker(ai_config, FakeGateway([json.dumps(diagnosis)])).run_once())
    with TestClient(app) as client:
        latest = client.get(
            f"/api/ai/sessions/{session['id']}/artifacts/latest",
            params={"kind": "diagnosis"},
        )
        assert latest.status_code == 200
        assert latest.json()["run_id"] == queued.json()["run"]["id"]


def test_longitudinal_diagnosis_cross_problem_and_sparse_evidence(ai_config, db_path):
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO problems(slug,title,difficulty) "
            "VALUES('second-problem','Second Problem','Easy')"
        )
        second_id = connection.execute(
            "SELECT id FROM problems WHERE slug='second-problem'"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO attempt_events(
                   id,problem_id,occurred_on,result,accepted,independent,source,created_at)
               VALUES('cross-a',1,'2026-07-18','red',0,1,'web','2026-07-18T10:00:00'),
                     ('cross-b',?,'2026-07-19','yellow',1,0,'web',
                      '2026-07-19T10:00:00')""",
            (second_id,),
        )
        snapshot = learning_snapshot(connection)
    assert {item["problem_id"] for item in snapshot["attempts"]} >= {1, second_id}
    serialized = json.dumps(snapshot)
    for forbidden in ("raw_json", "payload_json", "facts_json", "notes", "secret"):
        assert forbidden not in serialized
    assert all(
        "evidence_id" in item
        for key in ("attempts", "sessions", "hint_events", "skill_states")
        for item in snapshot[key]
    )

    diagnosis = {
        "schema_version": "diagnosis@1",
        "observations": ["Two attempts occurred on different problems."],
        "hypotheses": [
            {
                "type": "learning_bottleneck",
                "status": "likely",
                "statement": "Independent transfer may be fragile.",
                "confidence": 0.99,
                "evidence": [{"id": "attempt:cross-a"}, {"id": "attempt:cross-b"}],
            }
        ],
        "interventions": [
            {
                "action": "Try a third problem",
                "rationale": "Test transfer",
                "requires_user_action": True,
            }
        ],
    }
    with TestClient(app) as client:
        queued = client.post(
            "/api/ai/learning/diagnosis",
            json={"idempotency_key": "learning-diag-1"},
        )
        assert queued.status_code == 202
    asyncio.run(Worker(ai_config, FakeGateway([json.dumps(diagnosis)])).run_once())
    with TestClient(app) as client:
        latest = client.get("/api/ai/learning/diagnosis/latest")
        history = client.get("/api/ai/learning/diagnosis/history")
        assert latest.status_code == history.status_code == 200
        assert latest.json()["id"] == history.json()[0]["id"]
        assert latest.json()["content"]["hypotheses"][0]["confidence"] <= 0.85

    invented = {
        **diagnosis,
        "hypotheses": [{**diagnosis["hypotheses"][0], "evidence": [{"id": "attempt:invented"}]}],
    }
    with TestClient(app) as client:
        client.post(
            "/api/ai/learning/diagnosis",
            json={"idempotency_key": "learning-diag-2", "instructions": "new"},
        )
    asyncio.run(Worker(ai_config, FakeGateway([json.dumps(invented)])).run_once())
    with ai_connect(ai_config.db_path) as connection:
        assert (
            connection.execute(
                "SELECT status FROM runs "
                "WHERE json_extract(request_json,'$.idempotency_key')='learning-diag-2'"
            ).fetchone()["status"]
            == "failed"
        )


def test_streaming_worker_coalesces_ordered_events(ai_config):
    with TestClient(app) as client:
        conversation = client.post("/api/ai/problems/1/conversations", json={}).json()
        queued = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "stream", "idempotency_key": "stream-message-1"},
        ).json()
    pieces = ["a" * 40, "b" * 40, "c" * 10]
    asyncio.run(Worker(ai_config, FakeStreamingGateway(pieces)).run_once())
    with ai_connect(ai_config.db_path) as connection:
        events = connection.execute(
            "SELECT data_json FROM run_events WHERE run_id=? AND event_type='text' ORDER BY id",
            (queued["run"]["id"],),
        ).fetchall()
        message = connection.execute(
            "SELECT content FROM messages WHERE run_id=? AND role='assistant'",
            (queued["run"]["id"],),
        ).fetchone()
    deltas = [json.loads(row["data_json"])["text"] for row in events]
    assert 2 <= len(deltas) <= len(pieces)
    assert "".join(deltas) == "".join(pieces) == message["content"]


def test_idempotency_conflict_reservation_cache_and_assistance_rollback(
    ai_config, db_path, monkeypatch
):
    with TestClient(app) as client:
        first = client.post(
            "/api/ai/problems/1/lesson",
            json={"idempotency_key": "payload-conflict-1", "instructions": "one"},
        )
        conflict = client.post(
            "/api/ai/problems/1/lesson",
            json={"idempotency_key": "payload-conflict-1", "instructions": "two"},
        )
        assert first.status_code == 202 and conflict.status_code == 409
        usage = client.get("/api/ai/usage").json()
        assert usage["tokens_reserved"] > ai_config.max_output_tokens
        # The first queued run reserves estimated input plus the full output cap.
        monkeypatch.setenv(
            "INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET", str(ai_config.max_output_tokens)
        )
        reserved = client.post(
            "/api/ai/problems/1/visualization",
            json={"idempotency_key": "reservation-test-1"},
        )
        assert reserved.status_code == 402

    session = start_scheduled_session("assignment-1", SessionStart(), db_path)["session"]
    with TestClient(app) as client:
        conversation = client.post(
            f"/api/ai/sessions/{session['id']}/conversations", json={}
        ).json()
        rejected = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "help", "idempotency_key": "budget-chat-1"},
        )
        assert rejected.status_code == 402
    with connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT ai_assisted FROM practice_sessions WHERE id=?", (session["id"],)
            ).fetchone()["ai_assisted"]
            == 0
        )


def test_cached_artifact_bypasses_exhausted_provider_budget(ai_config, monkeypatch):
    lesson = {
        "schema_version": "lesson@1",
        "objectives": ["Recognize"],
        "recognition_signals": [],
        "sections": [{"heading": "Idea", "body": "Invariant"}],
        "complexity": {"time": "O(n)", "space": "O(n)"},
        "failures": [],
        "provenance_notes": [],
    }
    request = {"idempotency_key": "cache-budget-1", "instructions": "same"}
    with TestClient(app) as client:
        queued = client.post("/api/ai/problems/1/lesson", json=request)
        assert queued.status_code == 202
    asyncio.run(Worker(ai_config, FakeGateway([json.dumps(lesson)])).run_once())
    monkeypatch.setenv("INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET", "0")
    with TestClient(app) as client:
        cached = client.post(
            "/api/ai/problems/1/lesson",
            json={**request, "idempotency_key": "cache-budget-2"},
        )
    assert cached.status_code == 202
    assert cached.json()["created"] is False
    assert cached.json()["run"]["id"] == queued.json()["run"]["id"]


def test_hosted_provider_empty_secret_fails_closed(tmp_path, monkeypatch):
    secret = tmp_path / "empty"
    secret.write_text("")
    monkeypatch.delenv("INTERVIEW_PREP_AI_BASE_URL", raising=False)
    monkeypatch.setenv("INTERVIEW_PREP_AI_ENABLED", "true")
    monkeypatch.setenv("INTERVIEW_PREP_AI_PROVIDER", "openai")
    monkeypatch.setenv("INTERVIEW_PREP_AI_API_KEY_FILE", str(secret))
    with pytest.raises(AIConfigError, match="API key is required"):
        AIConfig.from_env()


def test_worker_import_boundary():
    import ast
    from pathlib import Path

    root = Path("app/ai")
    pending = ["app.ai.worker"]
    visited: set[str] = set()
    imported: set[str] = set()
    source = ""
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = root / (module.removeprefix("app.ai.").replace(".", "/") + ".py")
        text = path.read_text()
        source += text
        tree = ast.parse(text)
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= names
        pending.extend(name for name in names if name.startswith("app.ai.") and name not in visited)

    forbidden = (
        "app.attempts",
        "app.sessions",
        "app.learning",
        "app.services",
        "app.db",
        "app.repository",
        "app.content",
    )
    assert not any(name.startswith(forbidden) for name in imported)
    assert "INTERVIEW_PREP_DB" not in source
