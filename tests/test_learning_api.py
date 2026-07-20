from __future__ import annotations

from fastapi.testclient import TestClient

from app.curriculum import import_outtalent
from app.db import transaction
from app.main import app


def _import(db_path):
    with transaction(db_path) as connection:
        import_outtalent(connection)


def test_learning_profile_contract(db_path):
    _import(db_path)
    with TestClient(app) as client:
        payload = client.get("/api/learning/profile").json()
    assert payload["policy_version"].startswith("learner-policy/")
    assert payload["target_retention"] == 0.85
    assert payload["confidence"] in {"early", "developing", "established"}
    assert {"attempts", "dimension_observations", "note"} <= set(payload["evidence_summary"])
    skill = payload["skills"][0]
    assert set(skill["dimensions"]) == {
        "recognition",
        "derivation",
        "implementation",
        "testing",
        "explanation",
        "retention",
    }
    for cell in skill["dimensions"].values():
        assert cell["state"] in {
            "no_evidence",
            "fragile",
            "developing",
            "independent",
            "decaying",
            "blocked",
        }
        assert "evidence_count" in cell and "facts" in cell
    assert "traps" in payload and "memory_at_risk" in payload


def test_learning_today_contract(db_path):
    _import(db_path)
    with TestClient(app) as client:
        payload = client.get("/api/learning/today").json()
    assert payload["selected"] is not None
    assert set(payload["selected"]["components"]) == {
        "track_priority",
        "due_urgency",
        "weakness_error_relevance",
        "prerequisite_readiness",
        "transfer_value",
        "recent_exposure_penalty",
        "timebox_fit",
    }
    assert payload["why"], "rationale facts must be present"
    assert payload["decision_id"].startswith("daily:")
    assert isinstance(payload["due_count"], int)
    # The active assignment fixture must win the selection.
    assert payload["active_assignment"]["assignment_id"] == "assignment-1"
    assert payload["selected"]["title"] == "Critical Connections in a Network"


def test_learning_roadmap_contract(db_path):
    _import(db_path)
    with TestClient(app) as client:
        payload = client.get("/api/learning/roadmap").json()
    assert payload["dimensions"] == [
        "recognition",
        "derivation",
        "implementation",
        "testing",
        "explanation",
        "retention",
    ]
    track_ids = [track["id"] for track in payload["tracks"]]
    assert track_ids[0] == "outtalent"  # formal track ranks first
    outtalent = payload["tracks"][0]
    assert outtalent["problem_count"] == 41
    kinds = {item["item_kind"] for item in outtalent["items"]}
    assert {"problem", "reading", "mock", "placeholder"} <= kinds
    assert payload["heatmap"], "heatmap rows required"
    row = payload["heatmap"][0]
    assert set(row["dimensions"]) == set(payload["dimensions"])


def test_skill_detail_contract_and_404(db_path):
    _import(db_path)
    with TestClient(app) as client:
        payload = client.get("/api/skills/dp/bitmask").json()
        assert payload["skill"]["id"] == "dp/bitmask"
        assert [p["id"] for p in payload["prerequisites"]] == ["dp/knapsack", "bitwise/masks"]
        assert payload["problems"], "mapped problems expected"
        assert client.get("/api/skills/not/a/skill").status_code == 404


def test_problems_track_filter_and_existing_contract(db_path):
    _import(db_path)
    with TestClient(app) as client:
        unfiltered = client.get("/api/problems").json()
        assert {"items", "total", "page", "pages", "status_counts", "tracks"} <= set(unfiltered)
        filtered = client.get("/api/problems", params={"track": "outtalent"}).json()
        assert filtered["total"] == 40
        assert [t["id"] for t in filtered["tracks"]][0] == "outtalent"
        # Pre-existing behavior is unchanged.
        assert client.get("/api/problems", params={"status": "invented"}).status_code == 422


def test_problem_detail_exposes_workspace_fields(db_path):
    _import(db_path)
    with TestClient(app) as client:
        listing = client.get("/api/problems", params={"search": "coin change"}).json()
        problem_id = listing["items"][0]["id"]
        detail = client.get(f"/api/problems/{problem_id}").json()
    assert {"skills", "prerequisites", "related_problems", "placements", "lesson_availability"} <= (
        set(detail)
    )
    assert detail["lesson_availability"]["status"] in {"authored", "none"}
    roles = {skill["role"] for skill in detail["skills"]}
    assert "core" in roles
    assert {p["curriculum_id"] for p in detail["placements"]} == {"outtalent"}
