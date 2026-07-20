from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MemoryInput:
    result: str
    accepted: bool
    independent: bool
    highest_hint: str | None
    occurred_on: date
    previous_stability: float | None = None
    previous_difficulty: float | None = None
    previous_attempt_on: date | None = None
    evidence_count: int = 0


@dataclass(frozen=True)
class MemoryResult:
    stability_days: float
    difficulty: float
    retrievability: float
    evidence_count: int
    next_due: date


def schedule(value: MemoryInput) -> MemoryResult:
    stability = max(1.0, value.previous_stability or 1.0)
    difficulty = min(10.0, max(1.0, value.previous_difficulty or 5.0))
    delayed_days = (
        max(0, (value.occurred_on - value.previous_attempt_on).days)
        if value.previous_attempt_on
        else 0
    )
    assisted = bool(value.highest_hint) or not value.independent

    if value.result in {"red", "skipped"} or assisted:
        stability = 1.0 if value.evidence_count == 0 else max(1.0, stability * 0.62)
        difficulty = min(10.0, difficulty + 0.55)
        interval = 1
    elif value.result == "yellow":
        stability = max(1.0, stability * 0.9)
        difficulty = min(10.0, difficulty + 0.2)
        interval = 1
    else:
        delay_bonus = 1.25 if delayed_days >= 7 else 1.1 if delayed_days >= 2 else 1.0
        stability = max(2.0, stability * 2.15 * delay_bonus)
        difficulty = max(1.0, difficulty - 0.45)
        interval = max(2, min(60, round(stability)))

    return MemoryResult(
        stability_days=round(stability, 3),
        difficulty=round(difficulty, 3),
        retrievability=1.0,
        evidence_count=value.evidence_count + 1,
        next_due=value.occurred_on + timedelta(days=interval),
    )


def retrievability(stability_days: float, elapsed_days: int) -> float:
    return round(math.exp(-max(0, elapsed_days) / max(0.1, stability_days)), 4)
