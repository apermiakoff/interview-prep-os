import json
import sys

from app.db import connect
from scripts import import_legacy


def test_legacy_import_updates_rescheduled_review(tmp_path, monkeypatch):
    db_path = tmp_path / "import.db"
    state_path = tmp_path / "state.json"
    events_path = tmp_path / "events.jsonl"
    profile_path = tmp_path / "profile.json"
    plan_path = tmp_path / "plan.md"

    state = {
        "active_problem": {
            "leetcode_id": 1192,
            "title": "Critical Connections in a Network",
            "url": "https://leetcode.com/problems/critical-connections-in-a-network/",
            "review_id": "review-1",
            "assigned_on": "2026-07-21",
            "mode": "blind reconstruction retry",
        },
        "reviews": [
            {
                "id": "review-1",
                "problem_id": 1192,
                "problem": "Critical Connections in a Network",
                "due_on": "2026-07-21",
                "status": "pending",
                "stage": "R1",
            }
        ],
    }
    state_path.write_text(json.dumps(state))
    events_path.write_text("")
    profile_path.write_text(json.dumps({"profile": {"username": "test"}}))
    plan_path.write_text("")

    def run_import() -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "import_legacy.py",
                "--state",
                str(state_path),
                "--events",
                str(events_path),
                "--profile",
                str(profile_path),
                "--plan",
                str(plan_path),
                "--db",
                str(db_path),
            ],
        )
        assert import_legacy.main() == 0

    run_import()
    state["reviews"][0]["due_on"] = "2026-07-22"
    state_path.write_text(json.dumps(state))
    run_import()

    with connect(db_path) as connection:
        rows = connection.execute("SELECT id, due_on FROM reviews").fetchall()
        assert [(row["id"], row["due_on"]) for row in rows] == [("review-1", "2026-07-22")]
