"""Deterministic content resolver: every mapped problem gets honest support."""

from __future__ import annotations

from app.content import (
    GENERATOR,
    hint_ladder,
    lesson_document,
    resolve_problem_content,
)
from app.curriculum import import_outtalent
from app.db import connect, transaction
from app.lessons import LOW_LINK_HINTS


def _all_problem_ids(connection):
    return [row["id"] for row in connection.execute("SELECT id FROM problems ORDER BY id")]


def test_every_mapped_problem_resolves_available_lesson_and_hints(db_path):
    with transaction(db_path) as connection:
        import_outtalent(connection)
    with connect(db_path) as connection:
        mapped = [
            row["id"]
            for row in connection.execute(
                "SELECT DISTINCT problem_id AS id FROM problem_skills ORDER BY 1"
            )
        ]
        assert mapped, "fixture must map problems"
        for problem_id in mapped:
            resolution = resolve_problem_content(connection, problem_id)
            assert resolution is not None
            for key in ("lesson", "hints"):
                block = resolution[key]
                assert block["availability"] == "available", (problem_id, key)
                assert block["provenance"] in {"curated", "generated"}
                if block["provenance"] == "generated":
                    assert block["generator"] == GENERATOR
                    assert "curated" not in block["label"].lower()
                else:
                    assert block["generator"] is None
            ladder = hint_ladder(connection, problem_id)
            assert ladder is not None
            assert list(ladder) == ["H1", "H2", "H3", "H4"]
            assert all(len(body) > 40 for body in ladder.values())
            assert len(set(ladder.values())) == 4


def test_curated_low_link_content_takes_precedence(db_path):
    with connect(db_path) as connection:
        critical = connection.execute(
            "SELECT id FROM problems WHERE slug='critical-connections-in-a-network'"
        ).fetchone()["id"]
        resolution = resolve_problem_content(connection, critical)
        assert resolution["lesson"]["provenance"] == "curated"
        assert resolution["hints"]["provenance"] == "curated"
        assert hint_ladder(connection, critical) == LOW_LINK_HINTS
        document = lesson_document(connection, critical)
        assert document["provenance"] == "curated"
        assert document["lesson"] is not None and document["scaffold"] is None
        assert document["lesson"]["pattern"]["title"] == "Low-link bridges"


def test_generated_scaffold_is_problem_aware_and_staged(db_path):
    with transaction(db_path) as connection:
        import_outtalent(connection)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id, title FROM problems WHERE slug='coin-change'"
        ).fetchone()
        document = lesson_document(connection, row["id"])
        assert document["provenance"] == "generated"
        assert document["generator"] == GENERATOR
        assert document["lesson"] is None
        stages = document["scaffold"]["stages"]
        assert [stage["title"] for stage in stages] == [
            "Understand",
            "Derive",
            "Implement",
            "Test",
            "Reflect",
        ]
        assert all(stage["prompts"] for stage in stages)
        # Problem-aware: the Understand stage names the actual problem.
        assert row["title"] in stages[0]["intent"]
        # Skill-aware without fabrication: prompts reference the mapped skill,
        # and nothing claims to hold a worked solution.
        serialized = str(document)
        assert "1D dynamic programming" in serialized or "knapsack" in serialized.lower()

        ladder = hint_ladder(connection, row["id"])
        assert row["title"] in ladder["H1"]
        assert "brute force" in ladder["H2"].lower()
        assert "state" in ladder["H3"].lower() or "invariant" in ladder["H3"].lower()
        assert "checklist" in ladder["H4"].lower() or "1)" in ladder["H4"]
        assert "no reference solution" in ladder["H4"].lower()


def test_resolver_is_deterministic(db_path):
    with transaction(db_path) as connection:
        import_outtalent(connection)
    with connect(db_path) as connection:
        for problem_id in _all_problem_ids(connection)[:10]:
            first = (
                resolve_problem_content(connection, problem_id),
                hint_ladder(connection, problem_id),
                lesson_document(connection, problem_id),
            )
            second = (
                resolve_problem_content(connection, problem_id),
                hint_ladder(connection, problem_id),
                lesson_document(connection, problem_id),
            )
            assert first == second


def test_unknown_problem_resolves_none(db_path):
    with connect(db_path) as connection:
        assert resolve_problem_content(connection, 987654) is None
        assert hint_ladder(connection, 987654) is None
        assert lesson_document(connection, 987654) is None
