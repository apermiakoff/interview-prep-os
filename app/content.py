"""Deterministic instructional content resolver.

Two provenance classes, never blurred:

- ``curated``: hand-authored material — today the low-link visual lesson and its
  hint ladder (:mod:`app.lessons`), plus per-assignment authored hints. Curated
  content always wins over generated content for the same problem.
- ``generated``: a problem-aware scaffold assembled at request time from stored
  metadata only — problem title, LeetCode number, difficulty, mapped skills and
  their curated descriptions, prerequisite edges, and pattern recognition
  signals. It asks targeted derivation questions; it never invents a recurrence,
  invariant, or reference code that the metadata cannot justify, and it is
  always labeled ``generator=deterministic-skill-scaffold/1.0``.

There is no LLM, network call, or randomness here: the same database rows always
produce the same text, so a GET stays a pure read. Content views write nothing —
learner evidence only ever comes from practice-session routes.
"""

from __future__ import annotations

import json
import sqlite3

from app.lessons import curated_hints_for, lesson_for

GENERATOR = "deterministic-skill-scaffold/1.0"

HINT_LEVELS = ("H1", "H2", "H3", "H4")

# Invariant/state questions per skill family. These are recognition-level
# questions grounded in what the family means — not problem-specific answers.
FAMILY_STATE_QUESTIONS = {
    "dp": "Write the state definition in one sentence: what exactly does each "
    "subproblem value mean, and over which parameters? Only after that, derive how "
    "one state is built from smaller ones.",
    "graph": "Name what must stay true for every processed node or edge (visited set, "
    "distance label, component id). What single invariant does the traversal maintain?",
    "backtracking": "Define the partial state (choices so far), the constraint that "
    "prunes it, and exactly what is restored when you backtrack.",
    "search": "State the monotone predicate: what property flips exactly once across "
    "the ordered domain, and which side of the boundary does your answer keep?",
    "stack": "State the stack invariant: what ordering does the stack maintain, and "
    "what incoming element forces a pop?",
    "greedy": "State the exchange argument: why can your locally best choice be "
    "swapped into any optimal solution without making it worse?",
    "trees": "State what a subtree call returns and why that summary is enough for "
    "the parent to decide.",
    "trie": "State what each node on the path represents and what extra data a node "
    "must carry for the query you need.",
    "strings": "Define the index state precisely: which prefixes/suffixes have been "
    "matched, and what does a mismatch transition preserve?",
    "bitwise": "Say what each bit of your mask encodes and what set operation each "
    "transition performs.",
    "heap": "Name the frontier the heap maintains and the invariant that makes the "
    "top element safe to take.",
    "mixed": "Name the operations the structure must support and the invariant that "
    "keeps each of them within its required cost.",
}

DEFAULT_STATE_QUESTION = (
    "Before any code, write one sentence stating the invariant or state definition "
    "your approach maintains — if you cannot write it, the derivation is not done."
)


def _family(skill_id: str) -> str:
    return skill_id.split("/", 1)[0]


def _problem_context(connection: sqlite3.Connection, problem_id: int) -> dict | None:
    problem = connection.execute(
        """
        SELECT p.id, p.leetcode_id, p.slug, p.title, p.url, p.difficulty, p.pattern_id,
               pt.title AS pattern_title, pt.description AS pattern_description,
               pt.recognition_signals
        FROM problems p LEFT JOIN patterns pt ON pt.id = p.pattern_id
        WHERE p.id = ?
        """,
        (problem_id,),
    ).fetchone()
    if problem is None:
        return None
    skills = [
        dict(row)
        for row in connection.execute(
            """
            SELECT ps.skill_id, ps.role, ps.weight, ps.provenance,
                   s.title, s.kind, s.description
            FROM problem_skills ps JOIN skills s ON s.id = ps.skill_id
            WHERE ps.problem_id = ?
            ORDER BY CASE ps.role WHEN 'core' THEN 0 WHEN 'supporting' THEN 1 ELSE 2 END,
                     ps.weight DESC, ps.skill_id
            """,
            (problem_id,),
        )
    ]
    prerequisites = [
        dict(row)
        for row in connection.execute(
            """
            SELECT DISTINCT se.from_skill AS skill_id, s.title, s.description
            FROM problem_skills ps
            JOIN skill_edges se ON se.to_skill = ps.skill_id AND se.edge_type = 'prerequisite'
            JOIN skills s ON s.id = se.from_skill
            WHERE ps.problem_id = ? AND ps.role = 'core'
            ORDER BY se.from_skill
            """,
            (problem_id,),
        )
    ]
    signals: list[str] = []
    if problem["recognition_signals"]:
        try:
            parsed = json.loads(problem["recognition_signals"])
            signals = [str(item) for item in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            signals = []
    return {
        "problem": dict(problem),
        "skills": skills,
        "core_skills": [skill for skill in skills if skill["role"] == "core"],
        "supporting_skills": [skill for skill in skills if skill["role"] != "core"],
        "prerequisites": prerequisites,
        "signals": signals,
    }


def _identity_line(problem: dict) -> str:
    parts = [problem["title"]]
    if problem["leetcode_id"]:
        parts.append(f"LeetCode #{problem['leetcode_id']}")
    if problem["difficulty"]:
        parts.append(problem["difficulty"])
    return " · ".join(parts)


def _resolution(
    availability: str,
    provenance: str,
    scope: str | None,
    generator: str | None,
    label: str,
) -> dict:
    return {
        "availability": availability,
        "provenance": provenance,
        "scope": scope,
        "generator": generator,
        "label": label,
    }


def resolve_problem_content(connection: sqlite3.Connection, problem_id: int) -> dict | None:
    """Availability and provenance metadata only — never a hint or lesson body."""
    context = _problem_context(connection, problem_id)
    if context is None:
        return None
    curated_lesson = lesson_for(context["problem"]["pattern_id"]) is not None
    curated_hints = curated_hints_for(context["problem"]["pattern_id"]) is not None
    has_skills = bool(context["skills"])

    if curated_lesson:
        lesson = _resolution("available", "curated", "pattern", None, "Curated low-link lesson")
    elif has_skills:
        lesson = _resolution(
            "available", "generated", "skill", GENERATOR, "Generated practice scaffold"
        )
    else:
        lesson = _resolution(
            "unavailable", "unavailable", None, None, "No skill mapping yet — no lesson"
        )

    if curated_hints:
        hints = _resolution("available", "curated", "pattern", None, "Curated hint ladder")
    elif has_skills:
        hints = _resolution("available", "generated", "skill", GENERATOR, "Generated hint ladder")
    else:
        hints = _resolution(
            "unavailable", "unavailable", None, None, "No skill mapping yet — no hints"
        )
    return {"problem_id": problem_id, "lesson": lesson, "hints": hints}


# ---------------------------------------------------------------------------
# Hint ladder bodies
# ---------------------------------------------------------------------------


def hint_ladder(connection: sqlite3.Connection, problem_id: int) -> dict[str, str] | None:
    """Full four-step ladder for a problem, curated ladder taking precedence."""
    context = _problem_context(connection, problem_id)
    if context is None:
        return None
    curated = curated_hints_for(context["problem"]["pattern_id"])
    if curated is not None:
        return curated
    if not context["skills"]:
        return None
    return _generated_hints(context)


def _generated_hints(context: dict) -> dict[str, str]:
    problem = context["problem"]
    core = context["core_skills"] or context["skills"]
    primary = core[0]
    core_titles = ", ".join(skill["title"] for skill in core[:2])
    supporting = context["supporting_skills"]

    if context["signals"]:
        recognition_tail = (
            f"Recognition signals for {problem['pattern_title']}: "
            + "; ".join(context["signals"][:3])
            + "."
        )
    else:
        recognition_tail = f"What this skill means: {primary['description']}"
    h1 = (
        f"Recognition — “{problem['title']}” is mapped to {core_titles}. "
        f"{recognition_tail} Which cue in the statement points there?"
    )

    h2 = (
        f"Structure — start from the brute force and name the repeated work that makes "
        f"it slow. {primary['title']}: {primary['description']} "
        f"How does that idea remove the bottleneck here?"
    )
    if supporting:
        h2 += (
            " Supporting skill(s): "
            + ", ".join(skill["title"] for skill in supporting[:2])
            + " — often the mechanism, not the idea."
        )

    state_question = FAMILY_STATE_QUESTIONS.get(
        _family(primary["skill_id"]), DEFAULT_STATE_QUESTION
    )
    h3 = f"Invariant/state — {state_question} Write it down before touching code."
    if context["prerequisites"]:
        h3 += (
            " If this stalls, the mapped prerequisite is "
            + ", ".join(prereq["title"] for prereq in context["prerequisites"][:2])
            + "."
        )

    h4 = (
        "Implement & verify — 1) turn your written invariant into pseudocode on paper; "
        f"2) choose the data structures {primary['title'].lower()} needs deliberately; "
        "3) implement on LeetCode from your paper plan; 4) before submitting, test "
        "empty/size-one/duplicate/extreme inputs and trace one small case by hand; "
        "5) state time and space bounds and justify them from the loop or recursion "
        "structure. This scaffold has no reference solution for this exact problem — "
        "the checklist is the walkthrough."
    )
    return {"H1": h1, "H2": h2, "H3": h3, "H4": h4}


# ---------------------------------------------------------------------------
# Lesson bodies
# ---------------------------------------------------------------------------


def lesson_document(connection: sqlite3.Connection, problem_id: int) -> dict | None:
    """Full lesson payload for the lazy lesson endpoint. Pure read."""
    context = _problem_context(connection, problem_id)
    if context is None:
        return None
    resolution = resolve_problem_content(connection, problem_id)
    assert resolution is not None
    payload = {
        "problem_id": problem_id,
        "problem_title": context["problem"]["title"],
        **resolution["lesson"],
        "lesson": None,
        "scaffold": None,
    }
    curated = lesson_for(context["problem"]["pattern_id"])
    if curated is not None:
        payload["lesson"] = curated
        return payload
    if not context["skills"]:
        return payload
    payload["scaffold"] = {"stages": _scaffold_stages(context)}
    return payload


def _scaffold_stages(context: dict) -> list[dict]:
    problem = context["problem"]
    core = context["core_skills"] or context["skills"]
    primary = core[0]
    supporting = context["supporting_skills"]
    prerequisites = context["prerequisites"]

    understand_prompts = [
        "Restate the task in one sentence without re-reading the statement.",
        "List the input types, their size bounds, and the exact required output.",
        "Name two edge cases the constraints allow: empty, size one, duplicates, extremes.",
    ]
    if context["signals"]:
        understand_prompts.append(
            f"Recognition signals for {problem['pattern_title']}: "
            + "; ".join(context["signals"][:3])
            + ". Which of these appears in this statement?"
        )

    derive_prompts = [
        "Write the brute force first and name the repeated work that makes it slow.",
        f"{primary['title']}: {primary['description']} How does that remove the bottleneck?",
        FAMILY_STATE_QUESTIONS.get(_family(primary["skill_id"]), DEFAULT_STATE_QUESTION),
    ]
    if len(core) > 1:
        derive_prompts.append(
            f"Second mapped skill — {core[1]['title']}: {core[1]['description']} "
            "Where do the two ideas meet?"
        )

    implement_prompts = [
        "Translate the derivation into pseudocode on paper before opening an editor.",
        f"Pick the data structures {primary['title'].lower()} needs and say why each is safe.",
        "Implement on LeetCode from your paper plan — not from memory of a reference.",
    ]
    if supporting:
        implement_prompts.append(
            "Supporting skill(s) likely to carry the mechanics: "
            + ", ".join(skill["title"] for skill in supporting[:3])
            + "."
        )

    test_prompts = [
        "Enumerate edge cases before running: empty input, size one, duplicates, extremes.",
        "Trace one small example by hand through your exact code, not your intention.",
        "State time and space bounds and justify them from the loop/recursion structure.",
    ]
    if problem["difficulty"] == "Hard":
        test_prompts.append(
            "Hard problems usually hide a second constraint — re-read the statement "
            "once before submitting."
        )

    reflect_prompts = [
        "Explain the approach aloud in under two minutes: trigger, invariant, complexity.",
        "Record the honest outcome — a hint used is an assisted attempt, not a failure.",
    ]
    if prerequisites:
        reflect_prompts.append(
            "If the derivation stalled, review the mapped prerequisite skill(s): "
            + ", ".join(prereq["title"] for prereq in prerequisites[:3])
            + "."
        )

    return [
        {
            "id": "understand",
            "title": "Understand",
            "intent": f"Pin down what {_identity_line(problem)} is actually asking.",
            "prompts": understand_prompts,
        },
        {
            "id": "derive",
            "title": "Derive",
            "intent": "Reach the idea on paper; the invariant comes before any code.",
            "prompts": derive_prompts,
        },
        {
            "id": "implement",
            "title": "Implement",
            "intent": "Code from your own derivation, on LeetCode, not in this app.",
            "prompts": implement_prompts,
        },
        {
            "id": "test",
            "title": "Test",
            "intent": "Break your own solution before the judge does.",
            "prompts": test_prompts,
        },
        {
            "id": "reflect",
            "title": "Reflect",
            "intent": "Turn the attempt into evidence you can retrieve later.",
            "prompts": reflect_prompts,
        },
    ]
