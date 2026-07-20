from datetime import date

from app.scheduler import MemoryInput, schedule


def test_red_or_assisted_attempt_retries_tomorrow():
    result = schedule(
        MemoryInput(
            result="red",
            accepted=True,
            independent=False,
            highest_hint="H4",
            occurred_on=date(2026, 7, 20),
        )
    )
    assert result.next_due == date(2026, 7, 21)
    assert result.stability_days == 1.0


def test_delayed_independent_green_grows_stability():
    result = schedule(
        MemoryInput(
            result="green",
            accepted=True,
            independent=True,
            highest_hint=None,
            occurred_on=date(2026, 7, 20),
            previous_stability=3.0,
            previous_difficulty=5.0,
            previous_attempt_on=date(2026, 7, 10),
            evidence_count=2,
        )
    )
    assert result.stability_days > 7
    assert result.next_due > date(2026, 7, 27)
    assert result.evidence_count == 3
