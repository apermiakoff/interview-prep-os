"""Deterministic, versioned learner model and daily recommendation policy.

Everything here is a pure function of persisted rows (attempt_events, attempt_errors,
problem_skills, skill_edges, memory_states, curricula). There is no randomness and no
LLM involvement; every output cites the evidence it was derived from.

Science vs. policy:
- Exponential forgetting R(t) = exp(-t/S) and the retrieval-practice framing are the
  science-grounded parts.
- The specific thresholds (two observations for "recurring", two independent proofs
  for "independent", component weights) are explicit policy choices, versioned in
  POLICY_VERSION so historical decisions stay interpretable after tuning.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")

POLICY_VERSION = "learner-policy/1.0"
TARGET_RETENTION = 0.85

DIMENSIONS = ("recognition", "derivation", "implementation", "testing", "explanation", "retention")

# Gap (days) below which a repeat attempt is treated as same-session reconstruction
# rather than retention evidence.
RETENTION_MIN_GAP_DAYS = 3

# Observations needed before a trap counts as recurring rather than suspected.
TRAP_RECURRING_THRESHOLD = 2

# Independent observations needed before a dimension is called independent.
INDEPENDENT_THRESHOLD = 2

# Candidate-score weights. Explicit policy, not science.
SCORE_WEIGHTS = {
    "track_priority": 0.30,
    "due_urgency": 0.20,
    "weakness_error_relevance": 0.20,
    "prerequisite_readiness": 0.10,
    "transfer_value": 0.10,
    "recent_exposure_penalty": -0.15,
    "timebox_fit": 0.05,
}

# Prerequisite readiness below this gates a candidate behind ready ones.
PREREQ_GATE_THRESHOLD = 0.35

DIMENSION_WEAKNESS = {
    "fragile": 1.0,
    "blocked": 1.0,
    "decaying": 0.75,
    "developing": 0.4,
    "no_evidence": 0.25,
    "independent": 0.0,
}

READINESS_VALUE = {
    "independent": 1.0,
    "developing": 0.75,
    "decaying": 0.6,
    "no_evidence": 0.5,
    "fragile": 0.25,
    "blocked": 0.1,
}

INTERVENTIONS = {
    "recognition": "Drill recognition signals first: read the statement, name the pattern aloud, "
    "and check it against the trigger list before any code.",
    "derivation": "Write the state definition and invariant in words before coding; verify the "
    "transition on a three-element example.",
    "implementation": "Reconstruct from your own pseudocode with no reference code on screen; "
    "type the full solution once without running it.",
    "testing": "Before submitting, enumerate edge cases (empty, single, duplicate, extreme) and "
    "trace one by hand.",
    "complexity": "State time and space bounds before running; justify them from the loop "
    "structure, not intuition.",
    "communication": "Record a two-minute spoken explanation after solving; score it against "
    "the invariant, the transition, and the complexity.",
    "hint-dependence": "Run a strict no-hint window for the full timebox; if stuck, stop and "
    "log a red attempt instead of escalating to the walkthrough.",
}


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def retention(stability_days: float, elapsed_days: float) -> float:
    """Exponential forgetting: R(t) = exp(-t / S)."""
    return math.exp(-max(0.0, elapsed_days) / max(0.1, stability_days))


def due_interval_days(stability_days: float, target: float = TARGET_RETENTION) -> float:
    """Days until retrievability decays to the target: t* = S * ln(1 / target)."""
    if not 0 < target < 1:
        raise ValueError("target retention must be in (0, 1)")
    return max(0.1, stability_days) * math.log(1.0 / target)


def _today(connection_today: date | None = None) -> date:
    return connection_today or datetime.now(MOSCOW).date()


# ---------------------------------------------------------------------------
# Evidence derivation
# ---------------------------------------------------------------------------


def _attempt_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT e.*, p.title AS problem_title, p.leetcode_id
        FROM attempt_events e
        JOIN problems p ON p.id = e.problem_id
        WHERE e.result != 'skipped'
        ORDER BY e.occurred_on, e.created_at
        """
    ).fetchall()


def _attempt_errors(connection: sqlite3.Connection) -> dict[str, list[str]]:
    rows = connection.execute(
        """
        SELECT ae.attempt_id, ae.error_type_id, et.parent_id
        FROM attempt_errors ae
        JOIN error_types et ON et.id = ae.error_type_id
        """
    ).fetchall()
    by_attempt: dict[str, list[str]] = {}
    for row in rows:
        family = row["parent_id"] or row["error_type_id"]
        by_attempt.setdefault(row["attempt_id"], []).append(family)
    return by_attempt


ERROR_FAMILY_TO_DIMENSION = {
    "recognition": "recognition",
    "derivation": "derivation",
    "implementation": "implementation",
    "testing": "testing",
    "complexity": "derivation",
    "communication": "explanation",
}


def derive_observations(connection: sqlite3.Connection) -> dict[str, dict[str, list[dict]]]:
    """Map raw attempts to conservative dimension-level observations per skill.

    Signals: 'independent' (clean unaided success), 'assisted' (success with hints or
    help), 'failed' (a recorded error or red outcome for that dimension). A dimension
    with nothing to say about an attempt gets no observation at all — absence of
    evidence is preserved, not scored.
    """
    problem_skills: dict[int, list[sqlite3.Row]] = {}
    for row in connection.execute(
        "SELECT problem_id, skill_id, role, weight, provenance FROM problem_skills"
    ):
        problem_skills.setdefault(row["problem_id"], []).append(row)

    errors_by_attempt = _attempt_errors(connection)
    observations: dict[str, dict[str, list[dict]]] = {}
    last_attempt_on: dict[int, date] = {}
    skill_problem_history: dict[str, set[int]] = {}

    for attempt in _attempt_rows(connection):
        occurred = date.fromisoformat(attempt["occurred_on"])
        problem_id = attempt["problem_id"]
        hinted = bool(attempt["highest_hint"])
        independent_success = (
            attempt["result"] == "green" and bool(attempt["independent"]) and not hinted
        )
        assisted_success = attempt["result"] in ("green", "yellow") and not independent_success
        failed = attempt["result"] == "red"
        error_families = errors_by_attempt.get(attempt["id"], [])
        failed_dimensions = {
            ERROR_FAMILY_TO_DIMENSION[family]
            for family in error_families
            if family in ERROR_FAMILY_TO_DIMENSION
        }

        previous_on = last_attempt_on.get(problem_id)
        gap_days = (occurred - previous_on).days if previous_on else None
        last_attempt_on[problem_id] = occurred

        per_dimension: dict[str, str] = {}
        if independent_success:
            for dimension in ("recognition", "derivation", "implementation"):
                per_dimension[dimension] = "independent"
            if attempt["accepted"]:
                per_dimension["testing"] = "independent"
        elif assisted_success:
            for dimension in ("recognition", "derivation", "implementation"):
                per_dimension[dimension] = "assisted"
        for dimension in failed_dimensions:
            per_dimension[dimension] = "failed"
        if failed and not failed_dimensions:
            # A red attempt with no classified error is still a failure signal, but we
            # cannot honestly attribute it to a specific dimension; record derivation
            # OR implementation only if the hint ladder tells us how far they got.
            per_dimension["derivation" if not hinted else "implementation"] = "failed"

        score = attempt["explanation_score"]
        if score is not None:
            per_dimension["explanation"] = (
                "independent" if score >= 4 else "assisted" if score >= 3 else "failed"
            )

        if gap_days is not None and gap_days >= RETENTION_MIN_GAP_DAYS:
            if independent_success:
                per_dimension["retention"] = "independent"
            elif failed:
                per_dimension["retention"] = "failed"

        for mapping in problem_skills.get(problem_id, []):
            skill_id = mapping["skill_id"]
            seen_problems = skill_problem_history.setdefault(skill_id, set())
            if problem_id in seen_problems:
                evidence_kind = "same_problem_repeat"
            elif seen_problems:
                evidence_kind = "cross_problem"
            else:
                evidence_kind = "first_exposure"
            for dimension, signal in per_dimension.items():
                observations.setdefault(skill_id, {}).setdefault(dimension, []).append(
                    {
                        "signal": signal,
                        "attempt_id": attempt["id"],
                        "problem_id": problem_id,
                        "problem_title": attempt["problem_title"],
                        "occurred_on": attempt["occurred_on"],
                        "weight": mapping["weight"],
                        "role": mapping["role"],
                        "evidence_kind": evidence_kind,
                        "mapping_provenance": mapping["provenance"],
                    }
                )
            seen_problems.add(problem_id)

    return observations


# ---------------------------------------------------------------------------
# Skill-dimension states
# ---------------------------------------------------------------------------


def _skill_stability(connection: sqlite3.Connection, skill_id: str) -> float | None:
    row = connection.execute(
        """
        SELECT MAX(m.stability_days) AS stability
        FROM memory_states m
        JOIN problem_skills ps ON ps.problem_id = m.problem_id
        WHERE ps.skill_id = ?
        """,
        (skill_id,),
    ).fetchone()
    return float(row["stability"]) if row and row["stability"] is not None else None


def _dimension_state(
    observations: list[dict],
    *,
    prerequisites_weak: list[str],
    stability_days: float | None,
    today: date,
) -> dict:
    if not observations:
        return {
            "state": "no_evidence",
            "evidence_count": 0,
            "independent_count": 0,
            "last_evidence_on": None,
            "facts": ["No observations recorded for this dimension yet."],
        }
    independent_count = sum(1 for o in observations if o["signal"] == "independent")
    failed_count = sum(1 for o in observations if o["signal"] == "failed")
    assisted_count = sum(1 for o in observations if o["signal"] == "assisted")
    last = observations[-1]
    facts = [
        f"{len(observations)} observation(s): {independent_count} independent, "
        f"{assisted_count} assisted, {failed_count} failed.",
        f"Latest: {last['signal']} on {last['occurred_on']} "
        f"({last['problem_title']}, attempt {last['attempt_id']}).",
    ]

    if independent_count >= INDEPENDENT_THRESHOLD and last["signal"] != "failed":
        state = "independent"
        if stability_days is not None:
            last_on = date.fromisoformat(last["occurred_on"])
            elapsed = (today - last_on).days
            current_retention = retention(stability_days, elapsed)
            if current_retention < TARGET_RETENTION:
                state = "decaying"
                facts.append(
                    f"Estimated retention {current_retention:.2f} fell below target "
                    f"{TARGET_RETENTION} (stability {stability_days:.1f}d, {elapsed}d elapsed)."
                )
    elif independent_count == 1:
        state = "developing"
        facts.append(
            f"One independent proof exists; {INDEPENDENT_THRESHOLD} are required "
            "before this dimension is called independent."
        )
    else:
        state = "fragile"
        if failed_count >= 2 and prerequisites_weak:
            state = "blocked"
            facts.append(
                "Repeated failures while prerequisite skill(s) lack evidence: "
                + ", ".join(prerequisites_weak)
                + "."
            )
        elif assisted_count and not failed_count:
            facts.append("Only assisted successes so far; no independent completion.")

    return {
        "state": state,
        "evidence_count": len(observations),
        "independent_count": independent_count,
        "last_evidence_on": last["occurred_on"],
        "facts": facts,
    }


def _skill_edges(
    connection: sqlite3.Connection,
) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    prereqs: dict[str, list[dict]] = {}
    related: dict[str, list[dict]] = {}
    for row in connection.execute(
        "SELECT from_skill, to_skill, edge_type, weight FROM skill_edges"
    ):
        edge = dict(row)
        if row["edge_type"] == "prerequisite":
            prereqs.setdefault(row["to_skill"], []).append(edge)
        else:
            related.setdefault(row["from_skill"], []).append(edge)
            related.setdefault(row["to_skill"], []).append(
                {**edge, "from_skill": row["to_skill"], "to_skill": row["from_skill"]}
            )
    return prereqs, related


def compute_skill_states(
    connection: sqlite3.Connection, *, today: date | None = None, persist: bool = True
) -> dict[str, dict[str, dict]]:
    """Compute (and optionally persist) the state of every skill x dimension cell."""
    today = _today(today)
    observations = derive_observations(connection)
    prereq_edges, _ = _skill_edges(connection)
    skills = [row["id"] for row in connection.execute("SELECT id FROM skills ORDER BY id")]

    # First pass: naive states without blocked propagation (needs peer states).
    naive: dict[str, dict[str, dict]] = {}
    for skill_id in skills:
        stability = _skill_stability(connection, skill_id)
        naive[skill_id] = {}
        for dimension in DIMENSIONS:
            obs = observations.get(skill_id, {}).get(dimension, [])
            naive[skill_id][dimension] = _dimension_state(
                obs, prerequisites_weak=[], stability_days=stability, today=today
            )

    # Second pass: apply blocked detection now that prerequisite states are known.
    def prereq_is_weak(dimensions: dict[str, dict]) -> bool:
        core = [dimensions[d]["state"] for d in ("recognition", "derivation", "implementation")]
        return any(state in ("fragile", "blocked") for state in core) or all(
            state == "no_evidence" for state in core
        )

    states: dict[str, dict[str, dict]] = {}
    for skill_id in skills:
        stability = _skill_stability(connection, skill_id)
        states[skill_id] = {}
        weak_prereqs = [
            edge["from_skill"]
            for edge in prereq_edges.get(skill_id, [])
            if edge["from_skill"] in naive and prereq_is_weak(naive[edge["from_skill"]])
        ]
        for dimension in DIMENSIONS:
            obs = observations.get(skill_id, {}).get(dimension, [])
            states[skill_id][dimension] = _dimension_state(
                obs, prerequisites_weak=weak_prereqs, stability_days=stability, today=today
            )

    if persist:
        now = datetime.now(MOSCOW).isoformat()
        for skill_id, dimensions in states.items():
            for dimension, cell in dimensions.items():
                stability = _skill_stability(connection, skill_id)
                connection.execute(
                    """
                    INSERT INTO learner_skill_states(
                      skill_id, dimension, state, evidence_count, independent_count,
                      last_evidence_on, stability_days, facts_json, policy_version, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(skill_id, dimension) DO UPDATE SET
                      state=excluded.state, evidence_count=excluded.evidence_count,
                      independent_count=excluded.independent_count,
                      last_evidence_on=excluded.last_evidence_on,
                      stability_days=excluded.stability_days,
                      facts_json=excluded.facts_json,
                      policy_version=excluded.policy_version,
                      updated_at=excluded.updated_at
                    """,
                    (
                        skill_id,
                        dimension,
                        cell["state"],
                        cell["evidence_count"],
                        cell["independent_count"],
                        cell["last_evidence_on"],
                        stability,
                        json.dumps(cell["facts"], ensure_ascii=False),
                        POLICY_VERSION,
                        now,
                    ),
                )
    return states


def _aggregate_readiness(dimensions: dict[str, dict]) -> float:
    core = [dimensions[d]["state"] for d in ("recognition", "derivation", "implementation")]
    return sum(READINESS_VALUE[state] for state in core) / len(core)


def _aggregate_weakness(dimensions: dict[str, dict]) -> float:
    return sum(DIMENSION_WEAKNESS[cell["state"]] for cell in dimensions.values()) / len(dimensions)


# ---------------------------------------------------------------------------
# Trap detection
# ---------------------------------------------------------------------------


def detect_traps(connection: sqlite3.Connection) -> dict:
    """Recurring brain traps. A trap needs >= TRAP_RECURRING_THRESHOLD relevant
    observations to be called recurring; one observation is only 'suspected'."""
    traps: list[dict] = []

    error_rows = connection.execute(
        """
        SELECT COALESCE(et.parent_id, et.id) AS family, et.id AS error_type_id,
               ae.attempt_id, e.occurred_on, p.title AS problem_title
        FROM attempt_errors ae
        JOIN error_types et ON et.id = ae.error_type_id
        JOIN attempt_events e ON e.id = ae.attempt_id
        JOIN problems p ON p.id = e.problem_id
        ORDER BY e.occurred_on
        """
    ).fetchall()
    by_family: dict[str, list[sqlite3.Row]] = {}
    for row in error_rows:
        by_family.setdefault(row["family"], []).append(row)
    for family, rows in sorted(by_family.items()):
        status = "recurring" if len(rows) >= TRAP_RECURRING_THRESHOLD else "suspected"
        traps.append(
            {
                "id": f"error/{family}",
                "title": f"{family.capitalize()} breakdowns",
                "status": status,
                "observation_count": len(rows),
                "evidence": [
                    {
                        "attempt_id": row["attempt_id"],
                        "occurred_on": row["occurred_on"],
                        "problem": row["problem_title"],
                        "error_type": row["error_type_id"],
                    }
                    for row in rows
                ],
                "intervention": INTERVENTIONS.get(
                    ERROR_FAMILY_TO_DIMENSION.get(family, family),
                    INTERVENTIONS.get(family, "Collect one more classified attempt."),
                ),
            }
        )

    hint_rows = connection.execute(
        """
        SELECT e.id AS attempt_id, e.occurred_on, p.title AS problem_title
        FROM attempt_events e JOIN problems p ON p.id = e.problem_id
        WHERE e.highest_hint = 'H4' AND e.result != 'skipped'
        ORDER BY e.occurred_on
        """
    ).fetchall()
    if hint_rows:
        status = "recurring" if len(hint_rows) >= TRAP_RECURRING_THRESHOLD else "suspected"
        traps.append(
            {
                "id": "process/hint-dependence",
                "title": "Escalates to the full walkthrough (H4)",
                "status": status,
                "observation_count": len(hint_rows),
                "evidence": [
                    {
                        "attempt_id": row["attempt_id"],
                        "occurred_on": row["occurred_on"],
                        "problem": row["problem_title"],
                    }
                    for row in hint_rows
                ],
                "intervention": INTERVENTIONS["hint-dependence"],
            }
        )

    traps.sort(key=lambda t: (t["status"] != "recurring", -t["observation_count"], t["id"]))
    note = None
    if not traps:
        note = "Not enough evidence to name any trap: no classified failures recorded yet."
    elif all(t["status"] == "suspected" for t in traps):
        note = (
            "All traps are only suspected: each has a single observation, and the policy "
            f"requires {TRAP_RECURRING_THRESHOLD} before calling a trap recurring."
        )
    return {"traps": traps, "note": note, "recurring_threshold": TRAP_RECURRING_THRESHOLD}


# ---------------------------------------------------------------------------
# Memory at risk
# ---------------------------------------------------------------------------


def memory_at_risk(connection: sqlite3.Connection, *, today: date | None = None) -> list[dict]:
    today = _today(today)
    rows = connection.execute(
        """
        SELECT m.*, p.title, p.leetcode_id
        FROM memory_states m JOIN problems p ON p.id = m.problem_id
        ORDER BY m.next_due
        """
    ).fetchall()
    output = []
    for row in rows:
        last_on = date.fromisoformat(row["last_attempt_on"])
        elapsed = (today - last_on).days
        current = retention(row["stability_days"], elapsed)
        interval = due_interval_days(row["stability_days"])
        target_due = last_on + timedelta(days=math.ceil(interval))
        if current < TARGET_RETENTION:
            output.append(
                {
                    "problem_id": row["problem_id"],
                    "title": row["title"],
                    "leetcode_id": row["leetcode_id"],
                    "stability_days": row["stability_days"],
                    "retention_now": round(current, 4),
                    "target_retention": TARGET_RETENTION,
                    "target_due_on": target_due.isoformat(),
                    "days_since_attempt": elapsed,
                    "evidence_count": row["evidence_count"],
                    "last_result": row["last_result"],
                }
            )
    return output


# ---------------------------------------------------------------------------
# Candidate scoring + daily recommendation
# ---------------------------------------------------------------------------


def _candidate_rows(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT p.id, p.leetcode_id, p.slug, p.title, p.url, p.difficulty, p.pattern_id,
               q.state AS queue_state, q.priority AS queue_priority,
               m.stability_days, m.last_attempt_on, m.last_result,
               (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = p.id
                  AND e.result != 'skipped') AS attempt_count,
               (SELECT MAX(e.occurred_on) FROM attempt_events e WHERE e.problem_id = p.id
                  AND e.result != 'skipped') AS last_any_attempt_on,
               (SELECT e.result FROM attempt_events e WHERE e.problem_id = p.id
                  AND e.result != 'skipped'
                  ORDER BY e.occurred_on DESC, e.created_at DESC LIMIT 1) AS last_attempt_result
        FROM problems p
        LEFT JOIN queue_items q ON q.problem_id = p.id
        LEFT JOIN memory_states m ON m.problem_id = p.id
        WHERE COALESCE(q.state, 'catalog') NOT IN ('blocked', 'archived')
        """
    ).fetchall()
    candidates = {row["id"]: dict(row) for row in rows}
    for candidate in candidates.values():
        candidate["placements"] = []
    placement_rows = connection.execute(
        """
        SELECT ci.problem_id, ci.curriculum_id, ci.position, ci.week_label, ci.section,
               ci.topic, c.priority AS curriculum_priority, c.title AS curriculum_title,
               c.kind AS curriculum_kind
        FROM curriculum_items ci
        JOIN curricula c ON c.id = ci.curriculum_id
        WHERE ci.problem_id IS NOT NULL
        ORDER BY c.priority, ci.position
        """
    ).fetchall()
    for row in placement_rows:
        candidate = candidates.get(row["problem_id"])
        if candidate is not None:
            candidate["placements"].append(dict(row))
    return list(candidates.values())


def _score_candidate(
    candidate: dict,
    *,
    skill_states: dict[str, dict[str, dict]],
    problem_skills: dict[int, list[dict]],
    prereq_edges: dict[str, list[dict]],
    skill_problem_evidence: dict[str, set[int]],
    recurring_families: set[str],
    today: date,
    timebox_minutes: int,
) -> dict:
    facts: list[str] = []
    components: dict[str, float] = {}

    placements = candidate["placements"]
    if placements:
        best = placements[0]
        components["track_priority"] = round(1.0 / (1.0 + best["curriculum_priority"] / 100.0), 4)
        facts.append(
            f"Placed in {best['curriculum_title']} (priority {best['curriculum_priority']}, "
            f"position {best['position']}"
            + (f", {best['week_label']}" if best["week_label"] else "")
            + ")."
        )
    else:
        components["track_priority"] = 0.3
        facts.append("Not part of any curriculum track; baseline track score 0.3.")

    if candidate["stability_days"] is not None and candidate["last_attempt_on"]:
        last_on = date.fromisoformat(candidate["last_attempt_on"])
        elapsed = (today - last_on).days
        current = retention(candidate["stability_days"], elapsed)
        urgency = clamp01((TARGET_RETENTION - current) / TARGET_RETENTION)
        components["due_urgency"] = round(urgency, 4)
        interval = due_interval_days(candidate["stability_days"])
        facts.append(
            f"Memory: stability {candidate['stability_days']:.1f}d, retention now "
            f"{current:.2f} vs target {TARGET_RETENTION} (due {interval:.1f}d after last attempt)."
        )
    else:
        components["due_urgency"] = 0.0

    mappings = problem_skills.get(candidate["id"], [])
    if mappings:
        weighted = 0.0
        total_weight = 0.0
        weak_names: list[str] = []
        for mapping in mappings:
            dims = skill_states.get(mapping["skill_id"])
            if dims is None:
                continue
            weakness = _aggregate_weakness(dims)
            weighted += mapping["weight"] * weakness
            total_weight += mapping["weight"]
            if weakness >= 0.5:
                weak_names.append(mapping["skill_id"])
        base_weakness = weighted / total_weight if total_weight else 0.25
        trap_families = {
            family
            for mapping in mappings
            for family, dimension in ERROR_FAMILY_TO_DIMENSION.items()
            if family in recurring_families
            and skill_states.get(mapping["skill_id"], {}).get(dimension, {}).get("state")
            in ("fragile", "blocked")
        }
        trap_match = 1.0 if trap_families else 0.0
        components["weakness_error_relevance"] = round(
            clamp01(0.8 * base_weakness + 0.2 * trap_match), 4
        )
        if weak_names:
            facts.append("Trains weak skill(s): " + ", ".join(sorted(set(weak_names))) + ".")
        if trap_families:
            facts.append("Relevant to recurring trap(s): " + ", ".join(sorted(trap_families)) + ".")
    else:
        components["weakness_error_relevance"] = 0.25
        facts.append("No skill mapping yet; neutral weakness relevance 0.25.")

    readiness_values: list[float] = []
    gap_names: list[str] = []
    for mapping in mappings:
        if mapping["role"] != "core":
            continue
        for edge in prereq_edges.get(mapping["skill_id"], []):
            prereq_dims = skill_states.get(edge["from_skill"])
            if prereq_dims is None:
                continue
            value = _aggregate_readiness(prereq_dims)
            readiness_values.append(value)
            if value < PREREQ_GATE_THRESHOLD:
                gap_names.append(edge["from_skill"])
    components["prerequisite_readiness"] = (
        round(min(readiness_values), 4) if readiness_values else 1.0
    )
    gated = bool(gap_names)
    if gap_names:
        facts.append(
            "Prerequisite gap: "
            + ", ".join(sorted(set(gap_names)))
            + f" below readiness threshold {PREREQ_GATE_THRESHOLD}."
        )

    transfer_weight = 0.0
    total_weight = 0.0
    for mapping in mappings:
        total_weight += mapping["weight"]
        evidenced_elsewhere = any(
            problem != candidate["id"]
            for problem in skill_problem_evidence.get(mapping["skill_id"], set())
        )
        if evidenced_elsewhere:
            transfer_weight += mapping["weight"] * (1.0 if not candidate["attempt_count"] else 0.3)
    components["transfer_value"] = round(
        clamp01(transfer_weight / total_weight) if total_weight else 0.0, 4
    )
    if components["transfer_value"] > 0 and not candidate["attempt_count"]:
        facts.append(
            "Fresh problem exercising previously-evidenced skill(s): counts as transfer "
            "retrieval, stronger evidence than same-problem repetition."
        )

    penalty = 0.0
    if candidate["last_any_attempt_on"]:
        days_since = (today - date.fromisoformat(candidate["last_any_attempt_on"])).days
        if days_since <= 0:
            penalty = 1.0
            facts.append("Already attempted today; heavy recent-exposure penalty.")
        elif days_since == 1:
            penalty = 0.5 if candidate["last_attempt_result"] == "green" else 0.15
        elif days_since == 2:
            penalty = 0.2 if candidate["last_attempt_result"] == "green" else 0.05
    components["recent_exposure_penalty"] = round(penalty, 4)

    estimate = {"Easy": 20, "Medium": 35, "Hard": 50}.get(candidate["difficulty"] or "", 35)
    if candidate["last_attempt_result"] == "red":
        estimate += 10
    fit = clamp01(1.0 - abs(estimate - timebox_minutes) / timebox_minutes)
    components["timebox_fit"] = round(fit, 4)

    score = sum(SCORE_WEIGHTS[name] * value for name, value in components.items())
    return {
        "problem_id": candidate["id"],
        "leetcode_id": candidate["leetcode_id"],
        "slug": candidate["slug"],
        "title": candidate["title"],
        "difficulty": candidate["difficulty"],
        "url": candidate["url"],
        "components": components,
        "score": round(score, 4),
        "gated": gated,
        "facts": facts,
        "placements": placements,
        "estimated_minutes": estimate,
    }


def _next_gate(
    selected: dict | None,
    skill_states: dict[str, dict[str, dict]],
    problem_skills: dict[int, list[dict]],
) -> dict | None:
    if not selected:
        return None
    mappings = [m for m in problem_skills.get(selected["problem_id"], []) if m["role"] == "core"]
    if not mappings:
        return None
    ranked: list[tuple[float, str, str, dict]] = []
    for mapping in mappings:
        dims = skill_states.get(mapping["skill_id"], {})
        for dimension in ("derivation", "implementation", "recognition", "retention"):
            cell = dims.get(dimension)
            if cell is None:
                continue
            weakness = DIMENSION_WEAKNESS[cell["state"]]
            ranked.append((-weakness, mapping["skill_id"], dimension, cell))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    _, skill_id, dimension, cell = ranked[0]
    remaining = max(0, INDEPENDENT_THRESHOLD - cell["independent_count"])
    return {
        "skill_id": skill_id,
        "dimension": dimension,
        "current_state": cell["state"],
        "criterion": (
            f"{INDEPENDENT_THRESHOLD} independent {dimension} completions promote "
            f"{skill_id} from {cell['state'].replace('_', ' ')} to independent; "
            f"{cell['independent_count']} recorded, {remaining} to go."
        ),
    }


def daily_recommendation(
    connection: sqlite3.Connection,
    *,
    today: date | None = None,
    timebox_minutes: int = 35,
    persist: bool = True,
) -> dict:
    """Deterministic daily selection with fully persisted rationale."""
    today = _today(today)
    skill_states = compute_skill_states(connection, today=today, persist=persist)
    trap_report = detect_traps(connection)
    recurring_families = {
        trap["id"].removeprefix("error/")
        for trap in trap_report["traps"]
        if trap["status"] == "recurring" and trap["id"].startswith("error/")
    }

    problem_skills: dict[int, list[dict]] = {}
    for row in connection.execute("SELECT problem_id, skill_id, role, weight FROM problem_skills"):
        problem_skills.setdefault(row["problem_id"], []).append(dict(row))
    prereq_edges, _ = _skill_edges(connection)

    skill_problem_evidence: dict[str, set[int]] = {}
    for row in connection.execute(
        """
        SELECT DISTINCT ps.skill_id, e.problem_id
        FROM attempt_events e JOIN problem_skills ps ON ps.problem_id = e.problem_id
        WHERE e.result != 'skipped'
        """
    ):
        skill_problem_evidence.setdefault(row["skill_id"], set()).add(row["problem_id"])

    scored = [
        _score_candidate(
            candidate,
            skill_states=skill_states,
            problem_skills=problem_skills,
            prereq_edges=prereq_edges,
            skill_problem_evidence=skill_problem_evidence,
            recurring_families=recurring_families,
            today=today,
            timebox_minutes=timebox_minutes,
        )
        for candidate in _candidate_rows(connection)
    ]

    def curriculum_rank(entry: dict) -> tuple:
        if entry["placements"]:
            best = entry["placements"][0]
            return (best["curriculum_priority"], best["position"])
        return (9_999, 9_999)

    scored.sort(
        key=lambda entry: (
            entry["gated"],
            -entry["score"],
            *curriculum_rank(entry),
            entry["problem_id"],
        )
    )
    selected = scored[0] if scored else None

    # An in-flight assignment is a commitment, not a candidate: Today must point at
    # the same work the Solve room holds. The full scoring is still persisted so the
    # next free selection stays inspectable.
    active = connection.execute(
        """
        SELECT a.id, a.problem_id, a.assigned_on, a.mode
        FROM assignments a WHERE a.status IN ('active', 'carryover')
        ORDER BY a.assigned_on ASC, a.created_at ASC LIMIT 1
        """
    ).fetchone()
    active_constraint = None
    if active is not None:
        match = next(
            (entry for entry in scored if entry["problem_id"] == active["problem_id"]), None
        )
        if match is not None:
            if active["assigned_on"] > today.isoformat():
                commitment_fact = (
                    f"Assignment {active['id']} ({active['mode']}) is scheduled for "
                    f"{active['assigned_on']}; it remains the next session before a new selection."
                )
            else:
                commitment_fact = (
                    f"Assignment {active['id']} ({active['mode']}) is in flight since "
                    f"{active['assigned_on']}; finish or skip it before a new selection."
                )
            match["facts"] = [
                commitment_fact,
                *match["facts"],
            ]
            match["gated"] = False
            selected = match
        active_constraint = {
            "assignment_id": active["id"],
            "problem_id": active["problem_id"],
            "assigned_on": active["assigned_on"],
        }

    due_count = len(memory_at_risk(connection, today=today))
    top_trap = trap_report["traps"][0] if trap_report["traps"] else None
    gate = _next_gate(selected, skill_states, problem_skills)

    rationale = {
        "policy_version": POLICY_VERSION,
        "facts": selected["facts"] if selected else ["No eligible candidates."],
        "components": selected["components"] if selected else {},
        "weights": SCORE_WEIGHTS,
        "target_retention": TARGET_RETENTION,
    }
    decision_id = f"daily:{today.isoformat()}"
    if persist:
        connection.execute(
            """
            INSERT INTO learning_decisions(
              id, decided_on, kind, policy_version, inputs_json, selected_problem_id,
              selected_json, constraints_json, rationale_json, created_at
            ) VALUES(?, ?, 'daily_recommendation', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              policy_version=excluded.policy_version, inputs_json=excluded.inputs_json,
              selected_problem_id=excluded.selected_problem_id,
              selected_json=excluded.selected_json,
              constraints_json=excluded.constraints_json,
              rationale_json=excluded.rationale_json
            """,
            (
                decision_id,
                today.isoformat(),
                POLICY_VERSION,
                json.dumps(
                    [
                        {key: value for key, value in entry.items() if key != "placements"}
                        for entry in scored
                    ],
                    ensure_ascii=False,
                ),
                selected["problem_id"] if selected else None,
                json.dumps(selected or {}, ensure_ascii=False),
                json.dumps(
                    {
                        "timebox_minutes": timebox_minutes,
                        "date": today.isoformat(),
                        "active_assignment": active_constraint,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(rationale, ensure_ascii=False),
                datetime.now(MOSCOW).isoformat(),
            ),
        )

    return {
        "decision_id": decision_id,
        "date": today.isoformat(),
        "policy_version": POLICY_VERSION,
        "target_retention": TARGET_RETENTION,
        "selected": selected,
        "why": rationale["facts"],
        "components": rationale["components"],
        "weights": SCORE_WEIGHTS,
        "risk": top_trap,
        "traps_note": trap_report["note"],
        "due_count": due_count,
        "next_gate": gate,
        "active_assignment": active_constraint,
        "candidates_considered": len(scored),
        "runners_up": [
            {key: entry[key] for key in ("problem_id", "title", "score", "gated")}
            for entry in scored[1:4]
        ],
    }


# ---------------------------------------------------------------------------
# Read models for the API
# ---------------------------------------------------------------------------


def learning_profile(connection: sqlite3.Connection, *, today: date | None = None) -> dict:
    today = _today(today)
    states = compute_skill_states(connection, today=today, persist=True)
    trap_report = detect_traps(connection)
    skill_rows = {
        row["id"]: dict(row)
        for row in connection.execute(
            "SELECT id, title, kind, description, parent_id, provenance FROM skills"
        )
    }
    observation_total = sum(
        cell["evidence_count"] for dims in states.values() for cell in dims.values()
    )
    attempts_total = connection.execute(
        "SELECT COUNT(*) FROM attempt_events WHERE result != 'skipped'"
    ).fetchone()[0]

    skills_payload = []
    for skill_id, dims in sorted(states.items()):
        meta = skill_rows.get(skill_id, {})
        evidence_count = sum(cell["evidence_count"] for cell in dims.values())
        skills_payload.append(
            {
                "id": skill_id,
                "title": meta.get("title", skill_id),
                "kind": meta.get("kind"),
                "parent_id": meta.get("parent_id"),
                "provenance": meta.get("provenance"),
                "dimensions": dims,
                "evidence_count": evidence_count,
                "weakness": round(_aggregate_weakness(dims), 4),
                "readiness": round(_aggregate_readiness(dims), 4),
            }
        )

    confidence = (
        "early" if attempts_total < 6 else "developing" if attempts_total < 20 else "established"
    )
    return {
        "generated_at": datetime.now(MOSCOW).isoformat(),
        "policy_version": POLICY_VERSION,
        "target_retention": TARGET_RETENTION,
        "confidence": confidence,
        "evidence_summary": {
            "attempts": attempts_total,
            "dimension_observations": observation_total,
            "note": (
                "States are derived only from persisted structured attempts; public "
                "profile statistics are excluded."
            ),
        },
        "skills": skills_payload,
        "traps": trap_report["traps"],
        "traps_note": trap_report["note"],
        "memory_at_risk": memory_at_risk(connection, today=today),
    }


def learning_roadmap(connection: sqlite3.Connection, *, today: date | None = None) -> dict:
    today = _today(today)
    states = compute_skill_states(connection, today=today, persist=True)
    skill_rows = {
        row["id"]: dict(row)
        for row in connection.execute("SELECT id, title, kind, parent_id FROM skills")
    }

    tracks = []
    for curriculum in connection.execute("SELECT * FROM curricula ORDER BY priority, id"):
        items = []
        for item in connection.execute(
            """
            SELECT ci.*, p.title AS problem_title, p.leetcode_id, p.slug, p.difficulty,
                   (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = ci.problem_id
                      AND e.result != 'skipped') AS attempt_count,
                   (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = ci.problem_id
                      AND e.independent = 1) AS independent_count
            FROM curriculum_items ci
            LEFT JOIN problems p ON p.id = ci.problem_id
            WHERE ci.curriculum_id = ?
            ORDER BY ci.position
            """,
            (curriculum["id"],),
        ):
            entry = dict(item)
            entry["provenance"] = json.loads(entry.pop("provenance_json") or "{}")
            if entry["attempt_count"]:
                entry["evidence_status"] = (
                    "independent" if entry["independent_count"] else "attempted"
                )
            else:
                entry["evidence_status"] = "untouched"
            items.append(entry)
        track = dict(curriculum)
        track["provenance"] = json.loads(track.pop("provenance_json") or "{}")
        track["items"] = items
        track["problem_count"] = sum(1 for item in items if item["problem_id"] is not None)
        tracks.append(track)

    heatmap = []
    for skill_id, dims in sorted(states.items()):
        meta = skill_rows.get(skill_id, {})
        problem_count = connection.execute(
            "SELECT COUNT(*) FROM problem_skills WHERE skill_id = ?", (skill_id,)
        ).fetchone()[0]
        heatmap.append(
            {
                "skill_id": skill_id,
                "title": meta.get("title", skill_id),
                "kind": meta.get("kind"),
                "parent_id": meta.get("parent_id"),
                "problem_count": problem_count,
                "dimensions": {
                    dimension: {
                        "state": cell["state"],
                        "evidence_count": cell["evidence_count"],
                        "independent_count": cell["independent_count"],
                        "action": _cell_action(cell),
                    }
                    for dimension, cell in dims.items()
                },
            }
        )

    return {
        "generated_at": datetime.now(MOSCOW).isoformat(),
        "policy_version": POLICY_VERSION,
        "dimensions": list(DIMENSIONS),
        "tracks": tracks,
        "heatmap": heatmap,
    }


def _cell_action(cell: dict) -> str:
    state = cell["state"]
    if state == "no_evidence":
        return "Attempt a mapped problem to record first evidence."
    if state == "fragile":
        return "Retry without hints; log the blocker precisely."
    if state == "developing":
        remaining = max(0, INDEPENDENT_THRESHOLD - cell["independent_count"])
        return f"{remaining} more independent completion(s) to reach independent."
    if state == "independent":
        return "Maintain via spaced retrieval; no action due."
    if state == "decaying":
        return "Reconstruct now: retention fell below target."
    if state == "blocked":
        return "Repair the prerequisite skill before retrying this one."
    return ""


def skill_detail(
    connection: sqlite3.Connection, skill_id: str, *, today: date | None = None
) -> dict | None:
    today = _today(today)
    skill = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    if skill is None:
        return None
    states = compute_skill_states(connection, today=today, persist=False)
    dims = states.get(skill_id, {})
    prereq_edges, related_edges = _skill_edges(connection)
    observations = derive_observations(connection).get(skill_id, {})

    def skill_ref(other_id: str) -> dict:
        row = connection.execute(
            "SELECT id, title, kind FROM skills WHERE id = ?", (other_id,)
        ).fetchone()
        base = dict(row) if row else {"id": other_id, "title": other_id, "kind": None}
        other_dims = states.get(other_id)
        base["readiness"] = round(_aggregate_readiness(other_dims), 4) if other_dims else None
        return base

    problems = [
        dict(row)
        for row in connection.execute(
            """
            SELECT ps.role, ps.weight, ps.provenance, p.id, p.leetcode_id, p.slug, p.title,
                   p.difficulty,
                   (SELECT COUNT(*) FROM attempt_events e WHERE e.problem_id = p.id
                      AND e.result != 'skipped') AS attempt_count
            FROM problem_skills ps JOIN problems p ON p.id = ps.problem_id
            WHERE ps.skill_id = ?
            ORDER BY ps.role, p.title
            """,
            (skill_id,),
        )
    ]
    children = [
        dict(row)
        for row in connection.execute(
            "SELECT id, title, kind FROM skills WHERE parent_id = ? ORDER BY id", (skill_id,)
        )
    ]
    recent = sorted(
        (
            {**obs, "dimension": dimension}
            for dimension, entries in observations.items()
            for obs in entries
        ),
        key=lambda item: (item["occurred_on"], item["attempt_id"]),
        reverse=True,
    )[:20]

    return {
        "skill": dict(skill),
        "parent": skill_ref(skill["parent_id"]) if skill["parent_id"] else None,
        "children": children,
        "prerequisites": [skill_ref(edge["from_skill"]) for edge in prereq_edges.get(skill_id, [])],
        "unlocks": [
            skill_ref(to_skill)
            for to_skill, edges in sorted(prereq_edges.items())
            if any(edge["from_skill"] == skill_id for edge in edges)
        ],
        "related": [skill_ref(edge["to_skill"]) for edge in related_edges.get(skill_id, [])],
        "dimensions": dims,
        "problems": problems,
        "recent_observations": recent,
        "policy_version": POLICY_VERSION,
    }
