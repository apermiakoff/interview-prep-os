from fastapi.testclient import TestClient

from app.db import connect
from app.main import app


def test_bootstrap_and_hint_reveal(db_path):
    with TestClient(app) as client:
        response = client.get("/api/bootstrap")
        assert response.status_code == 200
        assert response.json()["active_assignment"]["title"] == "Critical Connections in a Network"
        hint = client.post("/api/hints", json={"assignment_id": "assignment-1", "level": "H2"})
        assert hint.status_code == 200
        assert hint.json()["text"] == "Invariant two"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
    with connect(db_path) as connection:
        assert connection.execute("SELECT highest_hint FROM assignments").fetchone()[0] == "H2"
        assert connection.execute("SELECT COUNT(*) FROM hint_events").fetchone()[0] == 1


def test_copied_accepted_stays_non_independent_and_is_idempotent(db_path):
    payload = {
        "assignment_id": "assignment-1",
        "event_id": "event-copied-1",
        "result": "red",
        "accepted": True,
        "independent": False,
        "failure_tag": "implementation",
        "duration_minutes": 33,
    }
    with TestClient(app) as client:
        first = client.post("/api/attempts", json=payload)
        second = client.post("/api/attempts", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
    with connect(db_path) as connection:
        attempt = connection.execute("SELECT * FROM attempt_events").fetchone()
        assignment = connection.execute("SELECT * FROM assignments").fetchone()
        memory = connection.execute("SELECT * FROM memory_states").fetchone()
        assert connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0] == 1
        assert attempt["accepted"] == 1
        assert attempt["independent"] == 0
        assert attempt["result"] == "red"
        assert assignment["status"] == "carryover"
        assert assignment["mode"] == "blind reconstruction retry"
        assert memory["next_due"] > memory["last_attempt_on"]


def test_green_completes_assignment(db_path):
    with TestClient(app) as client:
        response = client.post(
            "/api/attempts",
            json={
                "assignment_id": "assignment-1",
                "event_id": "event-green-1",
                "result": "green",
                "accepted": True,
                "independent": True,
                "failure_tag": "none",
                "explanation_score": 4,
            },
        )
        assert response.status_code == 200
        assert response.json()["active_assignment"] is None
    with connect(db_path) as connection:
        assert connection.execute("SELECT status FROM assignments").fetchone()[0] == "completed"


def test_skip_has_no_memory_penalty(db_path):
    with TestClient(app) as client:
        response = client.post(
            "/api/attempts",
            json={
                "assignment_id": "assignment-1",
                "event_id": "event-skip-1",
                "result": "skipped",
                "failure_tag": "unspecified",
            },
        )
        assert response.status_code == 200
    with connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_states").fetchone()[0] == 0
        assert connection.execute("SELECT status FROM assignments").fetchone()[0] == "carryover"


def test_notes_are_plain_persisted_text(db_path):
    content = "<script>alert('not html')</script>\nlow[u] invariant"
    with TestClient(app) as client:
        response = client.put("/api/assignments/assignment-1/notes", json={"content": content})
        assert response.status_code == 200
        loaded = client.get("/api/bootstrap").json()
        assert loaded["active_assignment"]["notes"] == content
