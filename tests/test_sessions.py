"""Practice sessions: ad hoc practice must never disturb scheduled commitments."""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import services as services_module
from app import sessions as sessions_module
from app.db import connect, transaction
from app.main import app
from app.repository import ensure_problem, seed_content

CURATED_HINTS = {
    "H1": "Question one",
    "H2": "Invariant two",
    "H3": "Pattern three",
    "H4": "Walkthrough four",
}


@pytest.fixture
def extra_problem(db_path):
    """A second mapped problem so ad hoc practice targets something other than
    the scheduled Critical Connections assignment."""
    with transaction(db_path) as connection:
        problem_id = ensure_problem(
            connection,
            leetcode_id=322,
            slug="coin-change",
            title="Coin Change",
            url="https://leetcode.com/problems/coin-change/",
            difficulty="Medium",
            pattern_id="dp/one-dimensional",
        )
        seed_content(connection)  # mirrors the pattern into problem_skills
    return problem_id


def _assignment_snapshot(path):
    with connect(path) as connection:
        return connection.execute("SELECT * FROM assignments WHERE id = 'assignment-1'").fetchone()


def _start_ad_hoc(client, problem_id, request_id="request-0001"):
    response = client.post(
        f"/api/problems/{problem_id}/practice-sessions", json={"request_id": request_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ad_hoc_start_is_idempotent_and_leaves_assignment_alone(db_path, extra_problem):
    before = tuple(_assignment_snapshot(db_path))
    with TestClient(app) as client:
        first = _start_ad_hoc(client, extra_problem)
        assert first["created"] is True
        session = first["session"]
        assert session["origin"] == "ad_hoc"
        assert session["assignment_id"] is None
        assert session["status"] == "active"

        # Same request id and plain re-launch both continue the open session.
        again = _start_ad_hoc(client, extra_problem)
        assert again["created"] is False
        assert again["session"]["id"] == session["id"]
        relaunch = client.post(f"/api/problems/{extra_problem}/practice-sessions", json={}).json()
        assert relaunch["session"]["id"] == session["id"]

        # The catalog 'active' status stays scheduled-only.
        catalog = client.get("/api/problems", params={"search": "coin change"}).json()
        assert catalog["items"][0]["status"] != "active"
    assert tuple(_assignment_snapshot(db_path)) == before


@pytest.mark.parametrize(
    ("result", "expect_memory"),
    [("green", True), ("yellow", True), ("red", True), ("skipped", False)],
)
def test_ad_hoc_attempt_preserves_assignment_byte_for_byte(
    db_path, extra_problem, result, expect_memory
):
    before = tuple(_assignment_snapshot(db_path))
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        response = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={
                "event_id": f"adhoc-{result}-1",
                "result": result,
                "accepted": result == "green",
                "independent": result == "green",
                "failure_tag": "none" if result == "green" else "unspecified",
                "duration_minutes": 21,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["session"]["session"]["status"] == "completed"
        # The scheduled assignment is still the active one in the bootstrap.
        assert payload["bootstrap"]["active_assignment"]["id"] == "assignment-1"

    assert tuple(_assignment_snapshot(db_path)) == before
    with connect(db_path) as connection:
        attempt = connection.execute(
            "SELECT * FROM attempt_events WHERE id = ?", (f"adhoc-{result}-1",)
        ).fetchone()
        assert attempt["session_id"] == session_id
        assert attempt["assignment_id"] is None
        assert attempt["problem_id"] == extra_problem
        memory = connection.execute(
            "SELECT COUNT(*) FROM memory_states WHERE problem_id = ?", (extra_problem,)
        ).fetchone()[0]
        review = connection.execute(
            "SELECT COUNT(*) FROM reviews WHERE problem_id = ? AND status='pending'",
            (extra_problem,),
        ).fetchone()[0]
        assert (memory == 1) is expect_memory
        assert (review == 1) is expect_memory


def test_ad_hoc_abandon_closes_only_the_session(db_path, extra_problem):
    before = tuple(_assignment_snapshot(db_path))
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        first = client.post(f"/api/practice-sessions/{session_id}/abandon")
        assert first.status_code == 200
        assert first.json()["session"]["status"] == "abandoned"
        # Abandoning twice is idempotent, not an error.
        assert client.post(f"/api/practice-sessions/{session_id}/abandon").status_code == 200
    assert tuple(_assignment_snapshot(db_path)) == before
    with connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM memory_states WHERE problem_id = ?", (extra_problem,)
            ).fetchone()[0]
            == 0
        )


def test_any_hint_normalizes_green_to_assisted_yellow(db_path, extra_problem):
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        reveal = client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        assert reveal.status_code == 200
        response = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={
                "event_id": "adhoc-hinted-green",
                "result": "green",
                "accepted": True,
                "independent": True,
                "failure_tag": "none",
            },
        )
        assert response.status_code == 200
    with connect(db_path) as connection:
        attempt = connection.execute(
            "SELECT result, independent, highest_hint FROM attempt_events WHERE id = ?",
            ("adhoc-hinted-green",),
        ).fetchone()
    assert attempt["result"] == "yellow"
    assert attempt["independent"] == 0
    assert attempt["highest_hint"] == "H1"


def test_hint_staircase_is_sequential_and_idempotent(db_path, extra_problem):
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        # Skipping ahead is refused.
        out_of_order = client.post(f"/api/practice-sessions/{session_id}/hints/H2/reveal")
        assert out_of_order.status_code == 409
        assert "H1" in out_of_order.json()["detail"]

        first = client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        assert first.status_code == 200
        body = first.json()
        assert body["level"] == "H1" and body["highest_hint"] == "H1"

        # Re-revealing the same level returns the same body and records nothing new.
        repeat = client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        assert repeat.status_code == 200
        assert repeat.json()["body"] == body["body"]

        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H3/reveal").status_code == 409
        )
        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H2/reveal").status_code == 200
        )
        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H9/reveal").status_code == 422
        )
    with connect(db_path) as connection:
        events = connection.execute(
            "SELECT level FROM session_hint_events WHERE session_id = ? ORDER BY level",
            (session_id,),
        ).fetchall()
    assert [row["level"] for row in events] == ["H1", "H2"]


def test_reveal_returns_exactly_one_body(db_path):
    """Scheduled Critical Connections session uses the authored ladder; a reveal
    must never include the other three bodies."""
    with TestClient(app) as client:
        started = client.post("/api/assignments/assignment-1/sessions", json={})
        assert started.status_code == 200
        session_id = started.json()["session"]["id"]
        response = client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        assert response.status_code == 200
        payload = response.json()
    assert payload["body"] == CURATED_HINTS["H1"]
    serialized = json.dumps(payload)
    for level in ("H2", "H3", "H4"):
        assert CURATED_HINTS[level] not in serialized


def test_no_unrevealed_hint_bodies_in_bootstrap_detail_or_session_get(db_path):
    with TestClient(app) as client:
        bootstrap = client.get("/api/bootstrap")
        serialized = bootstrap.text
        for body in CURATED_HINTS.values():
            assert body not in serialized
        assert bootstrap.json()["active_assignment"]["hint_levels"] == ["H1", "H2", "H3", "H4"]

        problem_id = bootstrap.json()["active_assignment"]["problem_id"]
        detail = client.get(f"/api/problems/{problem_id}")
        for body in CURATED_HINTS.values():
            assert body not in detail.text

        started = client.post("/api/assignments/assignment-1/sessions", json={})
        session_id = started.json()["session"]["id"]
        for body in CURATED_HINTS.values():
            assert body not in started.text

        client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        fetched = client.get(f"/api/practice-sessions/{session_id}")
        assert fetched.status_code == 200
        assert CURATED_HINTS["H1"] in fetched.text  # earned assistance stays visible
        for level in ("H2", "H3", "H4"):
            assert CURATED_HINTS[level] not in fetched.text
        levels = {entry["level"]: entry for entry in fetched.json()["hints"]["levels"]}
        assert levels["H1"]["state"] == "revealed"
        assert levels["H2"]["state"] == "next" and "body" not in levels["H2"]
        assert levels["H3"]["state"] == "locked" and "body" not in levels["H3"]


def test_duplicate_attempt_event_is_idempotent(db_path, extra_problem):
    payload = {
        "event_id": "adhoc-duplicate-1",
        "result": "yellow",
        "accepted": False,
        "independent": False,
        "failure_tag": "derivation",
    }
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        first = client.post(f"/api/practice-sessions/{session_id}/attempts", json=payload)
        # The retry arrives after the session already completed: still 200, no new row.
        second = client.post(f"/api/practice-sessions/{session_id}/attempts", json=payload)
        assert first.status_code == 200 and second.status_code == 200
    with connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT evidence_count FROM memory_states WHERE problem_id = ?",
                (extra_problem,),
            ).fetchone()[0]
            == 1
        )


def test_unknown_and_completed_conflicts(db_path, extra_problem):
    with TestClient(app) as client:
        assert client.get("/api/practice-sessions/ps-missing").status_code == 404
        assert client.post("/api/problems/999999/practice-sessions", json={}).status_code == 404
        assert client.post("/api/assignments/nope/sessions", json={}).status_code == 404

        started = _start_ad_hoc(client, extra_problem)
        session_id = started["session"]["id"]
        done = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={"event_id": "adhoc-close-1", "result": "red", "failure_tag": "derivation"},
        )
        assert done.status_code == 200
        # A closed session refuses new work.
        assert (
            client.post(
                f"/api/practice-sessions/{session_id}/attempts",
                json={"event_id": "adhoc-close-2", "result": "red", "failure_tag": "derivation"},
            ).status_code
            == 409
        )
        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal").status_code == 409
        )
        assert client.post(f"/api/practice-sessions/{session_id}/abandon").status_code == 409

        # Completing the scheduled assignment makes its session route conflict.
        client.post(
            "/api/attempts",
            json={
                "assignment_id": "assignment-1",
                "event_id": "finish-assignment",
                "result": "green",
                "accepted": True,
                "independent": True,
                "failure_tag": "none",
            },
        )
        assert client.post("/api/assignments/assignment-1/sessions", json={}).status_code == 409


def test_hint_unavailable_when_problem_has_no_mapping(db_path):
    with transaction(db_path) as connection:
        bare = ensure_problem(
            connection,
            leetcode_id=None,
            slug="unmapped-problem",
            title="Unmapped Problem",
            url=None,
        )
    with TestClient(app) as client:
        started = _start_ad_hoc(client, bare, request_id="request-bare-1")
        assert started["hints"]["availability"] == "unavailable"
        assert started["hints"]["provenance"] == "unavailable"
        session_id = started["session"]["id"]
        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal").status_code == 404
        )
        lesson = client.get(f"/api/problems/{bare}/lesson").json()
        assert lesson["availability"] == "unavailable"
        assert lesson["lesson"] is None and lesson["scaffold"] is None


def test_ad_hoc_routes_never_invoke_legacy_subprocess(
    db_path, extra_problem, tmp_path, monkeypatch
):
    """Even with the legacy coach bridge fully configured, ad hoc practice must
    never shell out to it."""
    for name in ("state.json", "events.jsonl", "profile.json", "action.py"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    monkeypatch.setenv("INTERVIEW_PREP_LEGACY_STATE", str(tmp_path / "state.json"))
    monkeypatch.setenv("INTERVIEW_PREP_LEGACY_EVENTS", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("INTERVIEW_PREP_LEGACY_PROFILE", str(tmp_path / "profile.json"))
    monkeypatch.setenv("INTERVIEW_PREP_LEGACY_ACTION", str(tmp_path / "action.py"))

    def forbidden(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("legacy coach subprocess must not run for ad hoc practice")

    monkeypatch.setattr(services_module, "_run_legacy_action", forbidden)
    monkeypatch.setattr(services_module, "_sync_legacy", forbidden)

    before = tuple(_assignment_snapshot(db_path))
    with TestClient(app) as client:
        started = _start_ad_hoc(client, extra_problem, request_id="request-legacy-1")
        session_id = started["session"]["id"]
        assert (
            client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal").status_code == 200
        )
        response = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={"event_id": "adhoc-legacy-1", "result": "yellow", "failure_tag": "derivation"},
        )
        assert response.status_code == 200
        abandoned_extra = client.post(
            f"/api/problems/{extra_problem}/practice-sessions", json={}
        ).json()
        assert (
            client.post(
                f"/api/practice-sessions/{abandoned_extra['session']['id']}/abandon"
            ).status_code
            == 200
        )
    assert tuple(_assignment_snapshot(db_path)) == before


def test_scheduled_session_transitions_assignment_exactly_as_before(db_path):
    with TestClient(app) as client:
        started = client.post("/api/assignments/assignment-1/sessions", json={})
        assert started.status_code == 200
        envelope = started.json()
        assert envelope["session"]["origin"] == "scheduled"
        assert envelope["session"]["assignment_id"] == "assignment-1"
        assert envelope["scheduled"]["assigned_on"] == "2026-07-20"
        session_id = envelope["session"]["id"]

        # Continuing does not fork a second session.
        again = client.post("/api/assignments/assignment-1/sessions", json={})
        assert again.json()["session"]["id"] == session_id

        reveal = client.post(f"/api/practice-sessions/{session_id}/hints/H1/reveal")
        assert reveal.status_code == 200
        response = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={
                "event_id": "scheduled-hinted-green",
                "result": "green",
                "accepted": True,
                "independent": True,
                "failure_tag": "none",
            },
        )
        assert response.status_code == 200
        assert response.json()["session"]["session"]["status"] == "completed"

    with connect(db_path) as connection:
        assignment = connection.execute(
            "SELECT * FROM assignments WHERE id = 'assignment-1'"
        ).fetchone()
        attempt = connection.execute(
            "SELECT * FROM attempt_events WHERE id = 'scheduled-hinted-green'"
        ).fetchone()
        hint_event = connection.execute(
            "SELECT COUNT(*) FROM hint_events WHERE assignment_id = 'assignment-1'"
        ).fetchone()[0]
    # Hint-assisted green transitions exactly like the compatibility endpoint:
    # yellow evidence, carryover retry, hint ladder reset.
    assert attempt["result"] == "yellow"
    assert attempt["assignment_id"] == "assignment-1"
    assert attempt["session_id"] is not None
    assert assignment["status"] == "carryover"
    assert assignment["mode"] == "blind reconstruction retry"
    assert assignment["highest_hint"] is None
    assert hint_event == 1


def test_scheduled_session_clean_green_completes_assignment(db_path):
    with TestClient(app) as client:
        started = client.post("/api/assignments/assignment-1/sessions", json={})
        session_id = started.json()["session"]["id"]
        response = client.post(
            f"/api/practice-sessions/{session_id}/attempts",
            json={
                "event_id": "scheduled-clean-green",
                "result": "green",
                "accepted": True,
                "independent": True,
                "failure_tag": "none",
                "explanation_score": 4,
            },
        )
        assert response.status_code == 200
        assert response.json()["bootstrap"]["active_assignment"] is None
    with connect(db_path) as connection:
        assert (
            connection.execute("SELECT status FROM assignments WHERE id='assignment-1'").fetchone()[
                0
            ]
            == "completed"
        )


def test_content_views_create_no_learner_evidence(db_path, extra_problem):
    evidence_tables = (
        "attempt_events",
        "memory_states",
        "reviews",
        "hint_events",
        "session_hint_events",
        "attempt_errors",
        "practice_sessions",
    )

    def counts():
        with connect(db_path) as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
                for table in evidence_tables
            }

    with TestClient(app) as client:
        before = counts()
        assert client.get(f"/api/problems/{extra_problem}/lesson").status_code == 200
        assert client.get(f"/api/problems/{extra_problem}").status_code == 200
        assert client.get("/api/problems", params={"search": "coin"}).status_code == 200
        assert counts() == before


def test_start_request_id_cannot_cross_problem_or_origin(db_path, extra_problem):
    with TestClient(app) as client:
        first = _start_ad_hoc(client, extra_problem, request_id="shared-start-id")
        assert first["session"]["problem_id"] == extra_problem

        other_problem = client.get("/api/bootstrap").json()["active_assignment"]["problem_id"]
        cross_problem = client.post(
            f"/api/problems/{other_problem}/practice-sessions",
            json={"request_id": "shared-start-id"},
        )
        assert cross_problem.status_code == 409

        cross_origin = client.post(
            "/api/assignments/assignment-1/sessions",
            json={"request_id": "shared-start-id"},
        )
        assert cross_origin.status_code == 409


def test_attempt_event_id_is_bound_to_session_and_payload(db_path, extra_problem):
    original = {
        "event_id": "owned-attempt-id",
        "result": "yellow",
        "accepted": False,
        "independent": False,
        "failure_tag": "derivation",
    }
    with TestClient(app) as client:
        first_session = _start_ad_hoc(client, extra_problem, request_id="first-owned-session")
        first_id = first_session["session"]["id"]
        first = client.post(f"/api/practice-sessions/{first_id}/attempts", json=original)
        assert first.status_code == 200
        assert first.json()["attempt"]["result"] == "yellow"

        retry = client.post(f"/api/practice-sessions/{first_id}/attempts", json=original)
        assert retry.status_code == 200
        assert retry.json()["attempt"]["duplicate"] is True
        assert retry.json()["attempt"]["result"] == "yellow"

        changed = client.post(
            f"/api/practice-sessions/{first_id}/attempts",
            json={**original, "result": "red"},
        )
        assert changed.status_code == 409

        other_problem = client.get("/api/bootstrap").json()["active_assignment"]["problem_id"]
        second_session = _start_ad_hoc(client, other_problem, request_id="second-owned-session")
        cross_session = client.post(
            f"/api/practice-sessions/{second_session['session']['id']}/attempts",
            json=original,
        )
        assert cross_session.status_code == 409

    with connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM attempt_events WHERE id='owned-attempt-id'"
            ).fetchone()[0]
            == 1
        )


def test_skip_discards_failure_tag_and_creates_no_error_evidence(db_path, extra_problem):
    with TestClient(app) as client:
        session = _start_ad_hoc(client, extra_problem, request_id="skip-error-session")
        response = client.post(
            f"/api/practice-sessions/{session['session']['id']}/attempts",
            json={
                "event_id": "skip-error-attempt",
                "result": "skipped",
                "failure_tag": "derivation",
            },
        )
        assert response.status_code == 200
        assert response.json()["attempt"]["result"] == "skipped"

    with connect(db_path) as connection:
        attempt = connection.execute(
            "SELECT failure_tag FROM attempt_events WHERE id='skip-error-attempt'"
        ).fetchone()
        assert attempt["failure_tag"] == "unspecified"
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM attempt_errors WHERE attempt_id='skip-error-attempt'"
            ).fetchone()[0]
            == 0
        )


def test_legacy_sync_retry_never_repeats_successful_action(db_path, tmp_path, monkeypatch):
    fake_paths = tuple(tmp_path / name for name in ("state", "events", "profile", "action"))
    calls = {"action": 0, "sync": 0}

    def fake_action(*args, **kwargs):
        calls["action"] += 1

    def flaky_sync(*args, **kwargs):
        calls["sync"] += 1
        if calls["sync"] == 1:
            raise services_module.ConflictError("simulated sync failure")

    monkeypatch.setattr(sessions_module, "_legacy_paths", lambda: fake_paths)
    monkeypatch.setattr(services_module, "_run_legacy_action", fake_action)
    monkeypatch.setattr(services_module, "_sync_legacy", flaky_sync)

    attempt = {
        "event_id": "legacy-sync-retry",
        "result": "yellow",
        "failure_tag": "derivation",
    }
    with TestClient(app) as client:
        started = client.post("/api/assignments/assignment-1/sessions", json={}).json()
        endpoint = f"/api/practice-sessions/{started['session']['id']}/attempts"
        assert client.post(endpoint, json=attempt).status_code == 409
        recovered = client.post(endpoint, json=attempt)
        assert recovered.status_code == 200
        assert recovered.json()["session"]["session"]["status"] == "completed"

    assert calls == {"action": 1, "sync": 2}
    with connect(db_path) as connection:
        claim = connection.execute(
            "SELECT status FROM request_log WHERE request_id='legacy-sync-retry'"
        ).fetchone()
        assert claim["status"] == "completed"


def test_database_rejects_scheduled_session_for_wrong_problem(db_path, extra_problem):
    with (
        connect(db_path) as connection,
        pytest.raises(sqlite3.IntegrityError, match="does not match assignment"),
    ):
        connection.execute(
            """
            INSERT INTO practice_sessions(
              id, problem_id, assignment_id, origin, status, mode, goal,
              timebox_minutes, started_at, updated_at)
            VALUES('wrong-problem-session', ?, 'assignment-1', 'scheduled', 'active',
                   'paper practice', '', 35, datetime('now'), datetime('now'))
            """,
            (extra_problem,),
        )


def test_preupgrade_unscoped_request_id_is_never_reused(db_path):
    with transaction(db_path) as connection:
        connection.execute(
            """
            INSERT INTO request_log(request_id, status, created_at)
            VALUES('old-unscoped-event', 'completed', datetime('now'))
            """
        )

    with (
        transaction(db_path) as connection,
        pytest.raises(services_module.ConflictError, match="pre-upgrade operation"),
    ):
        services_module.begin_claim(
            connection,
            "old-unscoped-event",
            "session-attempt:new-session",
            '{"result":"green"}',
            services_module._now(),
        )

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, scope, fingerprint FROM request_log "
            "WHERE request_id='old-unscoped-event'"
        ).fetchone()
        assert tuple(row) == ("completed", None, None)
