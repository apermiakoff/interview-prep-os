#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import database_path, init_db, transaction
from app.repository import ensure_problem, seed_content
from app.roadmap import parse_roadmap


def slug_from(url: str | None, title: str) -> str:
    if url:
        parts = [part for part in urlparse(url).path.split("/") if part]
        if parts:
            return parts[-1]
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("/home/hermes/aleksandr-interview-study-plan.md"),
    )
    parser.add_argument("--db", type=Path, default=database_path())
    args = parser.parse_args()

    state = json.loads(args.state.expanduser().read_text(encoding="utf-8"))
    events = read_events(args.events.expanduser())
    profile = json.loads(args.profile.expanduser().read_text(encoding="utf-8"))
    init_db(args.db)

    problem_ids: dict[str, int] = {}
    with transaction(args.db) as connection:
        seed_content(connection)
        for entry in parse_roadmap(args.plan.expanduser()):
            problem_id = ensure_problem(
                connection,
                leetcode_id=None,
                slug=entry.slug,
                title=entry.title,
                url=f"https://leetcode.com/problems/{entry.slug}/",
                pattern_id=entry.pattern_id,
            )
            problem_ids[entry.title] = problem_id
            connection.execute(
                """
                INSERT INTO queue_items(
                  problem_id, state, priority, roadmap_week, roadmap_position,
                  source, created_at, updated_at
                ) VALUES(?, 'backlog', ?, ?, ?, 'study-plan', ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  priority=excluded.priority,
                  roadmap_week=excluded.roadmap_week,
                  roadmap_position=excluded.roadmap_position,
                  source=excluded.source,
                  updated_at=excluded.updated_at
                """,
                (
                    problem_id,
                    entry.week * 100 + entry.position,
                    entry.week,
                    entry.position,
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                ),
            )
        connection.execute(
            "UPDATE assignments SET status='completed' WHERE status IN ('active', 'carryover')"
        )
        active = state.get("active_problem") or {}
        if active:
            title = active.get("title", "Untitled problem")
            problem_id = ensure_problem(
                connection,
                leetcode_id=int(active["leetcode_id"]) if active.get("leetcode_id") else None,
                slug=slug_from(active.get("url"), title),
                title=title,
                url=active.get("url"),
                difficulty=active.get("difficulty"),
                pattern_id=active.get("pattern") or "graph/low-link-bridges",
            )
            problem_ids[str(active.get("leetcode_id") or title)] = problem_id
            connection.execute(
                """
                INSERT INTO queue_items(problem_id, state, priority, source, created_at, updated_at)
                VALUES(?, 'scheduled', 0, 'active-assignment', ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  state='scheduled', updated_at=excluded.updated_at
                """,
                (problem_id, datetime.now().isoformat(), datetime.now().isoformat()),
            )
            assignment_id = (
                active.get("review_id") or f"active:{active.get('leetcode_id', problem_id)}"
            )
            connection.execute(
                """
                INSERT INTO assignments(
                  id, problem_id, assigned_on, mode, status, timebox_minutes, goal,
                  hints_json, bujo_json, highest_hint, created_at
                ) VALUES(?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  assigned_on=excluded.assigned_on,
                  mode=excluded.mode,
                  status='active',
                  goal=excluded.goal,
                  hints_json=excluded.hints_json,
                  bujo_json=excluded.bujo_json,
                  highest_hint=excluded.highest_hint
                """,
                (
                    assignment_id,
                    problem_id,
                    active.get("assigned_on") or datetime.now().date().isoformat(),
                    active.get("mode", "new"),
                    int(active.get("timebox_minutes") or 35),
                    active.get("goal")
                    or "Produce an independent implementation and explain it aloud.",
                    json.dumps(active.get("hint_ladder") or {}, ensure_ascii=False),
                    json.dumps(active.get("bullet_journal") or {}, ensure_ascii=False),
                    active.get("highest_hint"),
                    datetime.now().isoformat(),
                ),
            )

        for event in events:
            key = str(event.get("problem_id") or event.get("title"))
            problem_id = problem_ids.get(key)
            if not problem_id:
                title = event.get("title") or f"LeetCode {key}"
                problem_id = ensure_problem(
                    connection,
                    leetcode_id=int(event["problem_id"])
                    if str(event.get("problem_id", "")).isdigit()
                    else None,
                    slug=slug_from(event.get("url"), title),
                    title=title,
                    url=event.get("url"),
                    pattern_id=event.get("pattern"),
                )
                problem_ids[key] = problem_id
            connection.execute(
                """
                INSERT INTO queue_items(problem_id, state, priority, source, created_at, updated_at)
                VALUES(?, 'learning', 100, 'attempt-history', ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  state=CASE
                    WHEN queue_items.state IN ('blocked', 'archived', 'scheduled')
                    THEN queue_items.state ELSE 'learning' END,
                  updated_at=excluded.updated_at
                """,
                (problem_id, datetime.now().isoformat(), datetime.now().isoformat()),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO attempt_events(
                  id, problem_id, assignment_id, occurred_on, result, accepted, independent,
                  duration_minutes, highest_hint, failure_tag, explanation_score, source,
                  raw_json, created_at
                ) VALUES(?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    problem_id,
                    event.get("completed_on")
                    or event.get("occurred_on")
                    or event.get("attempted_on")
                    or datetime.now().date().isoformat(),
                    event.get("result", "red"),
                    int(bool(event.get("accepted"))),
                    int(bool(event.get("independent"))),
                    event.get("duration_minutes"),
                    event.get("highest_hint"),
                    (event.get("failure_tags") or ["unspecified"])[0],
                    event.get("explanation_score"),
                    event.get("source", "legacy"),
                    json.dumps(event, ensure_ascii=False),
                    event.get("recorded_at") or datetime.now().isoformat(),
                ),
            )

        memory_map = state.get("problem_memory") or state.get("scheduler", {}).get(
            "problem_memory", {}
        )
        for key, memory in memory_map.items():
            problem_id = problem_ids.get(str(key))
            if not problem_id:
                continue
            connection.execute(
                """
                INSERT INTO memory_states(
                  problem_id, stability_days, difficulty, retrievability, evidence_count,
                  last_attempt_on, next_due, last_result
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(problem_id) DO UPDATE SET
                  stability_days=excluded.stability_days,
                  difficulty=excluded.difficulty,
                  retrievability=excluded.retrievability,
                  evidence_count=excluded.evidence_count,
                  last_attempt_on=excluded.last_attempt_on,
                  next_due=excluded.next_due,
                  last_result=excluded.last_result
                """,
                (
                    problem_id,
                    float(memory.get("stability_days", 1)),
                    float(memory.get("difficulty", 5)),
                    float(memory.get("retrievability", 1)),
                    int(memory.get("evidence_count", 1)),
                    memory.get("last_attempt_on")
                    or memory.get("last_review")
                    or datetime.now().date().isoformat(),
                    memory.get("next_due") or datetime.now().date().isoformat(),
                    memory.get("last_result", "red"),
                ),
            )

        for review in state.get("reviews", []):
            key = str(review.get("problem_id") or review.get("leetcode_id") or "")
            problem_id = problem_ids.get(key)
            if not problem_id and active and review.get("problem") == active.get("title"):
                problem_id = problem_ids.get(str(active.get("leetcode_id") or active.get("title")))
            if not problem_id:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO reviews(
                  id, problem_id, due_on, status, stage, source_attempt_id, completed_at
                )
                VALUES(?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    review.get("id") or review.get("review_id"),
                    problem_id,
                    review.get("due_on") or review.get("assigned_for"),
                    "completed" if review.get("status") == "completed" else "pending",
                    review.get("stage", "Legacy review"),
                    review.get("completed_on"),
                ),
            )

        snapshot = profile.get("profile", profile)
        username = (
            snapshot.get("username") or profile.get("source", {}).get("username") or "unknown"
        )
        retrieved_at = profile.get("source", {}).get("retrieved_at") or datetime.now().isoformat()
        connection.execute(
            """
            INSERT OR IGNORE INTO profile_snapshots(username, retrieved_at, payload_json)
            VALUES(?, ?, ?)
            """,
            (username, retrieved_at, json.dumps(profile, ensure_ascii=False)),
        )

    print(json.dumps({"ok": True, "db": str(args.db), "events": len(events)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
