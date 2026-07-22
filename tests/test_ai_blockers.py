from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.ai_db import connect as ai_connect
from app.ai.ai_db import transaction
from app.ai.artifacts import prompt
from app.ai.config import (
    REQUEST_PROTOCOL_OVERHEAD_TOKENS,
    AIConfigError,
    estimate_tokens,
    validate_base_url,
)
from app.ai.gateway import HTTPGateway, ProviderError, ProviderResult
from app.ai.repository import AIBudgetError, claim, enqueue, save_snapshot
from app.ai.worker import StaleClaim, Worker
from app.main import app
from app.schemas import SessionStart
from app.sessions import start_scheduled_session


def _dns(*addresses: str):
    return [
        (socket.AF_INET6 if ":" in value else socket.AF_INET, socket.SOCK_STREAM, 6, "", (value, 0))
        for value in addresses
    ]


def test_ssrf_allowlist_resolution_and_canonical_policy(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _dns("93.184.216.34"))
    assert validate_base_url(
        "https://api.openai.com/v1", provider="openai", allow_private=False
    ).endswith("/v1")
    with pytest.raises(AIConfigError, match="canonical HTTPS"):
        validate_base_url("https://example.com/v1", provider="openai", allow_private=False)
    with pytest.raises(AIConfigError, match="ALLOWED_BASE_HOSTS"):
        validate_base_url(
            "https://compatible.example/v1",
            provider="openai_compatible",
            allow_private=False,
        )
    assert validate_base_url(
        "https://compatible.example/v1",
        provider="openai_compatible",
        allow_private=False,
        allowed_hosts=frozenset({"compatible.example"}),
    ).endswith("/v1")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns("93.184.216.34", "127.0.0.1"),
    )
    with pytest.raises(AIConfigError, match="non-public"):
        validate_base_url(
            "https://compatible.example/v1",
            provider="openai_compatible",
            allow_private=False,
            allowed_hosts=frozenset({"compatible.example"}),
        )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(socket.gaierror()),
    )
    with pytest.raises(AIConfigError, match="could not be resolved"):
        validate_base_url(
            "https://compatible.example/v1",
            provider="openai_compatible",
            allow_private=False,
            allowed_hosts=frozenset({"compatible.example"}),
        )


def test_rebinding_preflight_rejects_before_credential_send(ai_config, monkeypatch):
    config = replace(
        ai_config,
        provider="openai_compatible",
        base_url="https://compatible.example/v1",
        api_key="must-not-be-sent",
        allowed_base_hosts=frozenset({"compatible.example"}),
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _dns("127.0.0.1"))
    constructed = False

    class MustNotConstruct:
        def __init__(self, **_kwargs):
            nonlocal constructed
            constructed = True

    monkeypatch.setattr("app.ai.gateway.httpx.AsyncClient", MustNotConstruct)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(HTTPGateway(config).complete(system="s", user="u", max_tokens=1))
    assert caught.value.code == "target_rejected"
    assert constructed is False


@pytest.mark.parametrize("payload", [{"message": {"content": None}}, ValueError("bad json")])
def test_provider_non_text_and_malformed_json_are_terminal(ai_config, monkeypatch, payload):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            if isinstance(payload, Exception):
                raise payload
            return payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr("app.ai.gateway.httpx.AsyncClient", Client)
    with pytest.raises(ProviderError) as caught:
        asyncio.run(HTTPGateway(ai_config).complete(system="s", user="u", max_tokens=1))
    assert caught.value.code == "invalid_response"
    assert caught.value.transient is False


def test_large_input_rejected_before_enqueue(ai_config, monkeypatch):
    monkeypatch.setenv("INTERVIEW_PREP_AI_MAX_INPUT_TOKENS", "1")
    with TestClient(app) as client:
        response = client.post(
            "/api/ai/problems/1/lesson",
            json={"idempotency_key": "oversize-input-1", "instructions": "x" * 1000},
        )
    assert response.status_code == 413
    with ai_connect(ai_config.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_concurrent_budget_reservations_are_atomic(ai_config):
    with transaction(ai_config.db_path) as connection:
        snapshot_id = save_snapshot(
            connection, "problem", "1", {"schema_version": "problem-context@1", "problem": {}}
        )
    config = replace(ai_config, max_input_tokens=10, max_output_tokens=10, monthly_token_budget=15)

    def reserve(index: int) -> str:
        try:
            with transaction(config.db_path) as connection:
                enqueue(
                    connection,
                    config,
                    kind="lesson",
                    scope="problem",
                    scope_id=str(index),
                    snapshot_id=snapshot_id,
                    request={"instructions": "x"},
                    idempotency_key=f"concurrent-{index}",
                    estimated_input_tokens=5,
                )
            return "accepted"
        except AIBudgetError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, (1, 2)))
    assert sorted(outcomes) == ["accepted", "rejected"]


class FakeGateway:
    def __init__(self, result: ProviderResult | Exception):
        self.result = result

    async def complete(self, **_kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _lesson() -> str:
    return json.dumps(
        {
            "schema_version": "lesson@1",
            "objectives": ["Recognize"],
            "recognition_signals": [],
            "sections": [{"heading": "Idea", "body": "Invariant"}],
            "complexity": {"time": "O(n)", "space": "O(n)"},
            "failures": [],
            "provenance_notes": [],
        }
    )


def test_missing_provider_usage_is_conservatively_reconciled(ai_config):
    with TestClient(app) as client:
        run_id = client.post(
            "/api/ai/problems/1/lesson", json={"idempotency_key": "missing-usage-1"}
        ).json()["run"]["id"]
    asyncio.run(Worker(ai_config, FakeGateway(ProviderResult(_lesson()))).run_once())
    with ai_connect(ai_config.db_path) as connection:
        usage = connection.execute(
            "SELECT input_tokens,output_tokens,total_tokens FROM usage_ledger WHERE run_id=?",
            (run_id,),
        ).fetchone()
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0
    assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]


def test_expired_lease_fence_prevents_stale_finalization(ai_config):
    with TestClient(app) as client:
        conversation = client.post("/api/ai/problems/1/conversations", json={}).json()
        run_id = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "help", "idempotency_key": "fence-chat-1"},
        ).json()["run"]["id"]
    with transaction(ai_config.db_path) as connection:
        stale = claim(connection, "worker-stale", 1)
        connection.execute(
            "UPDATE runs SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?", (run_id,)
        )
    with transaction(ai_config.db_path) as connection:
        current = claim(connection, "worker-current", 60)
    assert stale and current
    stale_worker = Worker(ai_config, FakeGateway(ProviderResult("unused")), owner="worker-stale")
    current_worker = Worker(
        ai_config, FakeGateway(ProviderResult("unused")), owner="worker-current"
    )
    with pytest.raises(StaleClaim):
        stale_worker._finalize(stale, ProviderResult("stale", 1, 1), "stale")
    current_worker._finalize(current, ProviderResult("current", 1, 1), "current")
    with ai_connect(ai_config.db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE run_id=? AND role='assistant'", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM usage_ledger WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[0]
            == "completed"
        )


@pytest.mark.parametrize("mode", ["null", "unexpected", "finalization"])
def test_worker_exception_boundary_never_strands_run(ai_config, monkeypatch, mode):
    with TestClient(app) as client:
        conversation = client.post("/api/ai/problems/1/conversations", json={}).json()
        run_id = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "help", "idempotency_key": f"boundary-{mode}"},
        ).json()["run"]["id"]
    result: ProviderResult | Exception
    if mode == "null":
        result = ProviderResult(None)  # type: ignore[arg-type]
    elif mode == "unexpected":
        result = RuntimeError("secret raw provider body")
    else:
        result = ProviderResult("valid")
    worker = Worker(ai_config, FakeGateway(result))
    if mode == "finalization":
        monkeypatch.setattr(
            worker,
            "_finalize",
            lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("simulated")),
        )
    asyncio.run(worker.run_once())
    with ai_connect(ai_config.db_path) as connection:
        run = connection.execute(
            "SELECT status,error_code,error_message FROM runs WHERE id=?", (run_id,)
        ).fetchone()
    assert run["status"] == "failed"
    assert run["error_code"] in {"invalid_response", "internal_error"}
    assert "secret raw provider body" not in run["error_message"]


def test_session_diagnosis_marks_attempt_non_independent(ai_config, db_path):
    session = start_scheduled_session("assignment-1", SessionStart(), db_path)["session"]
    with TestClient(app) as client:
        queued = client.post(
            f"/api/ai/sessions/{session['id']}/diagnosis",
            json={"idempotency_key": "assisted-session-diagnosis"},
        )
        assert queued.status_code == 202
        attempt = client.post(
            f"/api/practice-sessions/{session['id']}/attempts",
            json={
                "event_id": "assisted-diagnosis-attempt",
                "result": "green",
                "accepted": True,
                "independent": True,
            },
        )
    assert attempt.status_code == 200
    assert attempt.json()["attempt"]["independent"] is False


def test_compose_ai_environment_is_shared_and_complete():
    text = Path("compose.yaml").read_text(encoding="utf-8")
    required = {
        "INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET",
        "INTERVIEW_PREP_AI_MAX_INPUT_TOKENS",
        "INTERVIEW_PREP_AI_MAX_OUTPUT_TOKENS",
        "INTERVIEW_PREP_AI_MAX_RETRIES",
        "INTERVIEW_PREP_AI_LEASE_SECONDS",
        "INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL",
        "INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS",
    }
    assert "&ai-environment" in text
    assert text.count("<<: *ai-environment") == 2
    assert all(name in text for name in required)


@pytest.mark.parametrize(
    ("provider", "base_url", "expected_path", "expected_host"),
    [
        ("openai", "https://api.openai.com/v1", "/v1/chat/completions", "api.openai.com"),
        ("anthropic", "https://api.anthropic.com/v1", "/v1/messages", "api.anthropic.com"),
        (
            "openai_compatible",
            "https://compatible.example:8443/v1",
            "/v1/chat/completions",
            "compatible.example:8443",
        ),
    ],
)
def test_request_is_pinned_with_original_host_and_sni(
    ai_config, monkeypatch, provider, base_url, expected_path, expected_host
):
    config = replace(
        ai_config,
        provider=provider,
        base_url=base_url,
        api_key="secret",
        allowed_base_hosts=frozenset({"compatible.example"}),
    )
    resolutions = 0

    def rebinding_dns(*_args, **_kwargs):
        nonlocal resolutions
        resolutions += 1
        return _dns("93.184.216.34" if resolutions == 1 else "127.0.0.1")

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_dns)
    seen = {}

    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen["url"] = request.url
            seen["host"] = request.headers["host"]
            seen["sni"] = request.extensions["sni_hostname"]
            payload = (
                {"content": [{"type": "text", "text": "ok"}]}
                if provider == "anthropic"
                else {"choices": [{"message": {"content": "ok"}}]}
            )
            return httpx.Response(200, json=payload, request=request)

    real_client = httpx.AsyncClient
    transport = Transport()
    monkeypatch.setattr(
        "app.ai.gateway.httpx.AsyncClient", lambda **_kwargs: real_client(transport=transport)
    )
    result = asyncio.run(HTTPGateway(config).complete(system="s", user="u", max_tokens=1))
    assert result.text == "ok"
    assert seen["url"].host == "93.184.216.34"
    assert seen["url"].path == expected_path
    assert seen["host"] == expected_host
    assert seen["sni"] == base_url.split("//", 1)[1].split(":", 1)[0].split("/", 1)[0]
    assert resolutions == 1


@pytest.mark.parametrize(
    ("provider", "base_url", "payload", "expected"),
    [
        (
            "openai",
            "https://api.openai.com/v1",
            {"choices": [{"message": {"content": "openai"}}], "usage": {}},
            "openai",
        ),
        (
            "openai_compatible",
            "https://compatible.example/v1",
            {"choices": [{"message": {"content": "compatible"}}], "usage": {}},
            "compatible",
        ),
        (
            "anthropic",
            "https://api.anthropic.com/v1",
            {"content": [{"type": "text", "text": "anthropic"}], "usage": {}},
            "anthropic",
        ),
        ("ollama", "http://127.0.0.1:11434", {"message": {"content": "ollama"}}, "ollama"),
    ],
)
def test_all_provider_protocols_parse_successfully(
    ai_config, monkeypatch, provider, base_url, payload, expected
):
    config = replace(
        ai_config,
        provider=provider,
        base_url=base_url,
        api_key="secret",
        allowed_base_hosts=frozenset({"compatible.example"}),
        allow_private_base_url=True,
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _dns("93.184.216.34"))
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )
    monkeypatch.setattr(
        "app.ai.gateway.httpx.AsyncClient", lambda **_kwargs: real_client(transport=transport)
    )
    result = asyncio.run(HTTPGateway(config).complete(system="s", user="u", max_tokens=1))
    assert result.text == expected


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("openai", {"choices": [{"message": {"content": None, "tool_calls": [{}]}}]}),
        ("anthropic", {"content": [{"type": "tool_use", "name": "x"}]}),
        ("ollama", {"message": {"content": None}}),
    ],
)
def test_null_and_tool_only_provider_responses_are_malformed(
    ai_config, monkeypatch, provider, payload
):
    hosts = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "ollama": "http://127.0.0.1:11434",
    }
    config = replace(ai_config, provider=provider, base_url=hosts[provider], api_key="secret")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: _dns("93.184.216.34"))
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )
    monkeypatch.setattr(
        "app.ai.gateway.httpx.AsyncClient", lambda **_kwargs: real_client(transport=transport)
    )
    with pytest.raises(ProviderError, match="no usable text|invalid response"):
        asyncio.run(HTTPGateway(config).complete(system="s", user="u", max_tokens=1))


def test_queued_cancel_is_atomic_idempotent_and_releases_reservation(ai_config):
    with TestClient(app) as client:
        queued = client.post(
            "/api/ai/problems/1/lesson", json={"idempotency_key": "queued-cancel-1"}
        ).json()["run"]
        assert client.get("/api/ai/usage").json()["tokens_reserved"] > 0
        first = client.post(f"/api/ai/runs/{queued['id']}/cancel")
        second = client.post(f"/api/ai/runs/{queued['id']}/cancel")
        assert first.json()["status"] == second.json()["status"] == "cancelled"
        assert client.get("/api/ai/usage").json()["tokens_reserved"] == 0
    with ai_connect(ai_config.db_path) as connection:
        run = connection.execute("SELECT * FROM runs WHERE id=?", (queued["id"],)).fetchone()
        events = connection.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id=? AND event_type='cancelled'",
            (queued["id"],),
        ).fetchone()[0]
    assert run["reserved_tokens"] == 0
    assert run["lease_owner"] is None and run["lease_until"] is None
    assert run["completed_at"] is not None and events == 1


def test_expired_final_attempt_is_failed_once_before_next_claim(ai_config):
    with TestClient(app) as client:
        first = client.post(
            "/api/ai/problems/1/lesson",
            json={"idempotency_key": "exhausted-final-1", "instructions": "first"},
        ).json()["run"]["id"]
        second = client.post(
            "/api/ai/problems/1/lesson",
            json={"idempotency_key": "exhausted-final-2", "instructions": "second"},
        ).json()["run"]["id"]
    with transaction(ai_config.db_path) as connection:
        connection.execute(
            "UPDATE runs SET status='running',attempts=max_attempts,lease_owner='crashed',"
            "lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
            (first,),
        )
        claimed = claim(connection, "next-worker", 60)
    assert claimed and claimed["id"] == second
    with transaction(ai_config.db_path) as connection:
        claim(connection, "other-worker", 60)
        failed = connection.execute("SELECT * FROM runs WHERE id=?", (first,)).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM run_events WHERE run_id=? AND event_type='failed'", (first,)
        ).fetchone()[0]
    assert failed["status"] == "failed" and failed["error_code"] == "attempts_exhausted"
    assert failed["reserved_tokens"] == 0 and failed["completed_at"] is not None
    assert failed["lease_owner"] is None and failed["lease_until"] is None and count == 1


def test_utf8_hard_bound_and_provider_overage_is_fully_charged(ai_config, monkeypatch):
    assert estimate_tokens("é", "🙂") == len("é🙂".encode()) + REQUEST_PROTOCOL_OVERHEAD_TOKENS
    with TestClient(app) as client:
        conversation = client.post("/api/ai/problems/1/conversations", json={}).json()
        queued = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "é🙂", "idempotency_key": "usage-overage-1"},
        ).json()["run"]
    with ai_connect(ai_config.db_path) as connection:
        reservation = connection.execute(
            "SELECT reserved_tokens,estimated_input_tokens,request_json,context_snapshot_id "
            "FROM runs WHERE id=?",
            (queued["id"],),
        ).fetchone()
        snapshot = json.loads(
            connection.execute(
                "SELECT content_json FROM context_snapshots WHERE id=?",
                (reservation["context_snapshot_id"],),
            ).fetchone()["content_json"]
        )
    system, user = prompt("chat", snapshot, json.loads(reservation["request_json"]))
    assert reservation["estimated_input_tokens"] == (
        len(system.encode()) + len(user.encode()) + REQUEST_PROTOCOL_OVERHEAD_TOKENS
    )
    reported_output = ai_config.max_output_tokens + 777
    asyncio.run(
        Worker(
            ai_config,
            FakeGateway(
                ProviderResult(
                    "full output", reservation["estimated_input_tokens"], reported_output
                )
            ),
        ).run_once()
    )
    with ai_connect(ai_config.db_path) as connection:
        usage = connection.execute(
            "SELECT * FROM usage_ledger WHERE run_id=?", (queued["id"],)
        ).fetchone()
    assert usage["output_tokens"] == reported_output
    assert usage["total_tokens"] > reservation["reserved_tokens"]
    monkeypatch.setenv(
        "INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET", str(reservation["reserved_tokens"])
    )
    with TestClient(app) as client:
        rejected = client.post(
            f"/api/ai/conversations/{conversation['id']}/messages",
            json={"content": "next", "idempotency_key": "usage-overage-2"},
        )
    assert rejected.status_code == 402
