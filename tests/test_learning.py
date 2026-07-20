from __future__ import annotations

import json
import math
from datetime import date

import pytest

from app.db import connect, init_db, transaction
from app.learning import (
    POLICY_VERSION,
    SCORE_WEIGHTS,
    TARGET_RETENTION,
    compute_skill_states,
    daily_recommendation,
    derive_observations,
    detect_traps,
    due_interval_days,
    learning_profile,
    retention,
)

TODAY = date(2026, 7, 20)


@pytest.fixture
def learning_db(tmp_path):
    path = tmp_path / "learning.db"
    init_db(path)
    with transaction(path) as connection:
        connection.executescript(
            """
            INSERT INTO skills(id, title, kind, provenance, created_at)
            VALUES ('base', 'Base skill', 'technique', 'curated', '2026-07-01'),
                   ('target', 'Target skill', 'technique', 'curated', '2026-07-01'),
                   ('free', 'Free skill', 'technique', 'curated', '2026-07-01');
            INSERT INTO skill_edges(from_skill, to_skill, edge_type, weight, provenance)
            VALUES ('base', 'target', 'prerequisite', 1.0, 'curated');
            INSERT INTO problems(id, leetcode_id, slug, title, difficulty)
            VALUES (1, 101, 'target-problem', 'Target Problem', 'Medium'),
                   (2, 102, 'base-problem', 'Base Problem', 'Medium'),
                   (3, 103, 'free-problem', 'Free Problem', 'Medium'),
                   (4, 104, 'fresh-transfer', 'Fresh Transfer Problem', 'Medium');
            INSERT INTO problem_skills(problem_id, skill_id, role, weight, provenance)
            VALUES (1, 'target', 'core', 1.0, 'curated'),
                   (2, 'base', 'core', 1.0, 'curated'),
                   (3, 'free', 'core', 1.0, 'curated'),
                   (4, 'free', 'core', 1.0, 'curated');
            """
        )
    return path


def _attempt(
    connection,
    *,
    attempt_id: str,
    problem_id: int,
    occurred_on: str,
    result: str,
    independent: bool = False,
    hint: str | None = None,
    errors: tuple[str, ...] = (),
    accepted: bool = False,
):
    connection.execute(
        """
        INSERT INTO attempt_events(
          id, problem_id, occurred_on, result, accepted, independent, highest_hint,
          source, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, 'test', ? || 'T10:00:00')
        """,
        (
            attempt_id,
            problem_id,
            occurred_on,
            result,
            int(accepted),
            int(independent),
            hint,
            occurred_on,
        ),
    )
    for error in errors:
        connection.execute(
            """
            INSERT INTO attempt_errors(attempt_id, error_type_id, provenance, created_at)
            VALUES(?, ?, 'reported', '2026-07-20T10:00:00')
            """,
            (attempt_id, error),
        )


# ---------------------------------------------------------------------------
# Target-retention forgetting math
# ---------------------------------------------------------------------------


def test_due_interval_comes_from_exponential_forgetting():
    # t* = S * ln(1/R_target); with S=10 and the 0.85 default: ~1.625 days.
    assert due_interval_days(10.0) == pytest.approx(10 * math.log(1 / 0.85))
    assert retention(10.0, due_interval_days(10.0)) == pytest.approx(TARGET_RETENTION)
    # The target is explicit and adjustable, not a hidden label.
    assert due_interval_days(10.0, target=0.5) == pytest.approx(10 * math.log(2))
    with pytest.raises(ValueError):
        due_interval_days(10.0, target=1.5)


# ---------------------------------------------------------------------------
# Conservative dimension evidence
# ---------------------------------------------------------------------------


def test_assisted_success_never_counts_as_independent_evidence(learning_db):
    with transaction(learning_db) as connection:
        # Client claims independent, but a hint was used: policy says assisted.
        _attempt(
            connection,
            attempt_id="a1",
            problem_id=1,
            occurred_on="2026-07-10",
            result="green",
            independent=True,
            hint="H2",
            accepted=True,
        )
        observations = derive_observations(connection)
        states = compute_skill_states(connection, today=TODAY, persist=False)
    signals = {o["signal"] for o in observations["target"]["implementation"]}
    assert signals == {"assisted"}
    cell = states["target"]["implementation"]
    assert cell["state"] == "fragile"
    assert cell["independent_count"] == 0


def test_two_independent_proofs_reach_independent_and_retention_needs_delay(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="b1",
            problem_id=3,
            occurred_on="2026-07-01",
            result="green",
            independent=True,
            accepted=True,
        )
        _attempt(
            connection,
            attempt_id="b2",
            problem_id=3,
            occurred_on="2026-07-10",
            result="green",
            independent=True,
            accepted=True,
        )
        observations = derive_observations(connection)
        states = compute_skill_states(connection, today=date(2026, 7, 11), persist=False)
    assert states["free"]["implementation"]["state"] == "independent"
    assert states["free"]["implementation"]["independent_count"] == 2
    # The 9-day gap makes the second attempt genuine retention evidence.
    retention_signals = [o["signal"] for o in observations["free"]["retention"]]
    assert retention_signals == ["independent"]


def test_same_day_repeat_is_not_retention_evidence(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="c1",
            problem_id=3,
            occurred_on="2026-07-10",
            result="green",
            independent=True,
        )
        _attempt(
            connection,
            attempt_id="c2",
            problem_id=3,
            occurred_on="2026-07-11",
            result="green",
            independent=True,
        )
        observations = derive_observations(connection)
    assert "retention" not in observations.get("free", {})


def test_independent_state_decays_below_target_retention(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="d1",
            problem_id=3,
            occurred_on="2026-06-20",
            result="green",
            independent=True,
        )
        _attempt(
            connection,
            attempt_id="d2",
            problem_id=3,
            occurred_on="2026-07-01",
            result="green",
            independent=True,
        )
        connection.execute(
            """
            INSERT INTO memory_states(
              problem_id, stability_days, difficulty, retrievability, evidence_count,
              last_attempt_on, next_due, last_result
            ) VALUES(3, 2.0, 5.0, 1.0, 2, '2026-07-01', '2026-07-03', 'green')
            """
        )
        states = compute_skill_states(connection, today=TODAY, persist=False)
    cell = states["free"]["implementation"]
    assert cell["state"] == "decaying"
    assert any("below target" in fact for fact in cell["facts"])


# ---------------------------------------------------------------------------
# Trap thresholds and sparse-evidence language
# ---------------------------------------------------------------------------


def test_trap_needs_two_observations_to_be_recurring(learning_db):
    with transaction(learning_db) as connection:
        report = detect_traps(connection)
        assert report["traps"] == []
        assert "Not enough evidence" in report["note"]

        _attempt(
            connection,
            attempt_id="t1",
            problem_id=1,
            occurred_on="2026-07-10",
            result="red",
            errors=("derivation",),
        )
        report = detect_traps(connection)
        assert [t["status"] for t in report["traps"]] == ["suspected"]
        assert report["note"] is not None and "suspected" in report["note"]

        _attempt(
            connection,
            attempt_id="t2",
            problem_id=2,
            occurred_on="2026-07-12",
            result="red",
            errors=("derivation",),
        )
        report = detect_traps(connection)
        trap = next(t for t in report["traps"] if t["id"] == "error/derivation")
        assert trap["status"] == "recurring"
        assert trap["observation_count"] == 2
        assert len(trap["evidence"]) == 2
        assert report["note"] is None


def test_child_error_types_roll_up_to_family_traps(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="u1",
            problem_id=1,
            occurred_on="2026-07-10",
            result="red",
            errors=("implementation/off-by-one",),
        )
        _attempt(
            connection,
            attempt_id="u2",
            problem_id=2,
            occurred_on="2026-07-12",
            result="red",
            errors=("implementation/recursion",),
        )
        report = detect_traps(connection)
    trap = next(t for t in report["traps"] if t["id"] == "error/implementation")
    assert trap["status"] == "recurring"


def test_profile_language_stays_honest_with_sparse_evidence(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="s1",
            problem_id=1,
            occurred_on="2026-07-19",
            result="red",
            hint="H4",
            errors=("derivation",),
        )
        profile = learning_profile(connection, today=TODAY)
    assert profile["confidence"] == "early"
    assert all(t["status"] == "suspected" for t in profile["traps"])
    target = next(s for s in profile["skills"] if s["id"] == "target")
    assert target["dimensions"]["derivation"]["state"] == "fragile"
    assert target["dimensions"]["recognition"]["state"] == "no_evidence"
    assert "No observations recorded" in target["dimensions"]["recognition"]["facts"][0]


# ---------------------------------------------------------------------------
# Prerequisite gating, blocked state, deterministic scoring
# ---------------------------------------------------------------------------


def _weaken_base_skill(connection):
    _attempt(
        connection,
        attempt_id="w1",
        problem_id=2,
        occurred_on="2026-07-10",
        result="red",
        errors=("recognition", "derivation", "implementation"),
    )


def test_prerequisite_gap_gates_candidates(learning_db):
    with transaction(learning_db) as connection:
        _weaken_base_skill(connection)
        recommendation = daily_recommendation(connection, today=TODAY)
    inputs = {entry["problem_id"]: entry for entry in _decision_inputs(learning_db)}
    target_entry = inputs[1]
    assert target_entry["gated"] is True
    assert target_entry["components"]["prerequisite_readiness"] < 0.35
    assert any("Prerequisite gap: base" in fact for fact in target_entry["facts"])
    # A gated problem never outranks ready ones, whatever its score.
    assert recommendation["selected"]["problem_id"] != 1


def test_repeated_failures_with_weak_prereq_become_blocked(learning_db):
    with transaction(learning_db) as connection:
        _weaken_base_skill(connection)
        _attempt(
            connection,
            attempt_id="f1",
            problem_id=1,
            occurred_on="2026-07-12",
            result="red",
            errors=("derivation",),
        )
        _attempt(
            connection,
            attempt_id="f2",
            problem_id=1,
            occurred_on="2026-07-15",
            result="red",
            errors=("derivation",),
        )
        states = compute_skill_states(connection, today=TODAY, persist=False)
    cell = states["target"]["derivation"]
    assert cell["state"] == "blocked"
    assert any("prerequisite" in fact.lower() for fact in cell["facts"])


def _decision_inputs(path):
    with connect(path) as connection:
        row = connection.execute(
            "SELECT inputs_json FROM learning_decisions ORDER BY decided_on DESC LIMIT 1"
        ).fetchone()
    return json.loads(row["inputs_json"])


def test_scoring_is_deterministic_and_rationale_is_persisted(learning_db):
    with transaction(learning_db) as connection:
        connection.execute(
            """
            INSERT INTO curricula(id, title, kind, priority, created_at)
            VALUES('outtalent', 'Outtalent', 'formal', 0, '2026-07-01')
            """
        )
        connection.execute(
            """
            INSERT INTO curriculum_items(
              curriculum_id, import_key, problem_id, item_kind, title_raw, position, created_at
            ) VALUES('outtalent', 'k1', 3, 'problem', 'Free Problem', 0, '2026-07-01')
            """
        )
    with transaction(learning_db) as connection:
        first = daily_recommendation(connection, today=TODAY)
    with transaction(learning_db) as connection:
        second = daily_recommendation(connection, today=TODAY)

    assert first["selected"]["problem_id"] == second["selected"]["problem_id"] == 3
    assert first["selected"]["components"] == second["selected"]["components"]
    assert set(first["selected"]["components"]) == set(SCORE_WEIGHTS)
    assert first["policy_version"] == POLICY_VERSION
    assert any("Outtalent" in fact for fact in first["why"])

    with connect(learning_db) as connection:
        decision = connection.execute(
            "SELECT * FROM learning_decisions WHERE id = ?", (f"daily:{TODAY.isoformat()}",)
        ).fetchone()
    assert decision is not None
    assert decision["policy_version"] == POLICY_VERSION
    assert decision["selected_problem_id"] == 3
    rationale = json.loads(decision["rationale_json"])
    assert rationale["facts"] and rationale["weights"] == SCORE_WEIGHTS
    inputs = json.loads(decision["inputs_json"])
    assert {entry["problem_id"] for entry in inputs} == {1, 2, 3, 4}
    constraints = json.loads(decision["constraints_json"])
    assert constraints["timebox_minutes"] == 35


def test_transfer_value_rewards_fresh_problem_on_evidenced_skill(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="x1",
            problem_id=3,
            occurred_on="2026-07-01",
            result="green",
            independent=True,
        )
        daily_recommendation(connection, today=TODAY)
    inputs = {entry["problem_id"]: entry for entry in _decision_inputs(learning_db)}
    # Problem 4 is untouched but exercises the already-evidenced 'free' skill.
    assert inputs[4]["components"]["transfer_value"] == 1.0
    assert inputs[3]["components"]["transfer_value"] == 0.0


def test_recent_exposure_is_penalized(learning_db):
    with transaction(learning_db) as connection:
        _attempt(
            connection,
            attempt_id="y1",
            problem_id=3,
            occurred_on=TODAY.isoformat(),
            result="green",
            independent=True,
        )
        daily_recommendation(connection, today=TODAY)
    inputs = {entry["problem_id"]: entry for entry in _decision_inputs(learning_db)}
    assert inputs[3]["components"]["recent_exposure_penalty"] == 1.0
    assert inputs[4]["components"]["recent_exposure_penalty"] == 0.0


def test_empty_database_recommends_nothing_gracefully(tmp_path):
    path = tmp_path / "empty.db"
    init_db(path)
    with transaction(path) as connection:
        recommendation = daily_recommendation(connection, today=TODAY)
    assert recommendation["selected"] is None
    assert recommendation["why"] == ["No eligible candidates."]


def test_future_active_assignment_is_described_as_scheduled(learning_db):
    with transaction(learning_db) as connection:
        connection.execute(
            """
            INSERT INTO assignments(
              id, problem_id, assigned_on, mode, status, timebox_minutes, goal,
              hints_json, bujo_json, created_at)
            VALUES('future-r1', 1, '2026-07-21', 'blind reconstruction retry',
                   'active', 35, 'Reconstruct independently.', '{}', '{}',
                   '2026-07-20T10:00:00')
            """
        )
        recommendation = daily_recommendation(connection, today=TODAY)

    assert recommendation["active_assignment"]["assigned_on"] == "2026-07-21"
    assert recommendation["why"][0] == (
        "Assignment future-r1 (blind reconstruction retry) is scheduled for 2026-07-21; "
        "it remains the next session before a new selection."
    )
