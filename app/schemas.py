from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator

HINTS = {"H1", "H2", "H3", "H4"}
RESULTS = {"green", "yellow", "red", "skipped"}
FAILURES = {
    "recognition",
    "derivation",
    "implementation",
    "bugs",
    "complexity",
    "communication",
    "none",
    "unspecified",
}


class AttemptCreate(BaseModel):
    assignment_id: str
    event_id: str | None = Field(default=None, min_length=8, max_length=100)
    result: str
    accepted: bool = False
    independent: bool = False
    duration_minutes: int | None = Field(default=None, ge=0, le=360)
    failure_tag: str = "unspecified"
    explanation_score: float | None = Field(default=None, ge=0, le=5)

    @field_validator("result")
    @classmethod
    def valid_result(cls, value: str) -> str:
        if value not in RESULTS:
            raise ValueError("invalid result")
        return value

    @field_validator("failure_tag")
    @classmethod
    def valid_failure(cls, value: str) -> str:
        if value not in FAILURES:
            raise ValueError("invalid failure tag")
        return value


class HintCreate(BaseModel):
    assignment_id: str
    level: str

    @field_validator("level")
    @classmethod
    def valid_hint(cls, value: str) -> str:
        if value not in HINTS:
            raise ValueError("invalid hint level")
        return value


class SessionStart(BaseModel):
    """Start (or idempotently continue) a practice session."""

    request_id: str | None = Field(default=None, min_length=8, max_length=100)
    timebox_minutes: int | None = Field(default=None, ge=10, le=240)
    goal: str | None = Field(default=None, max_length=500)


class SessionAttemptCreate(BaseModel):
    """Immutable evidence reported when a practice session ends."""

    event_id: str | None = Field(default=None, min_length=8, max_length=100)
    result: str
    accepted: bool = False
    independent: bool = False
    duration_minutes: int | None = Field(default=None, ge=0, le=360)
    failure_tag: str = "unspecified"
    explanation_score: float | None = Field(default=None, ge=0, le=5)

    @field_validator("result")
    @classmethod
    def valid_result(cls, value: str) -> str:
        if value not in RESULTS:
            raise ValueError("invalid result")
        return value

    @field_validator("failure_tag")
    @classmethod
    def valid_failure(cls, value: str) -> str:
        if value not in FAILURES:
            raise ValueError("invalid failure tag")
        return value


class NotesUpdate(BaseModel):
    content: str = Field(max_length=20_000)


class QueueBulkUpdate(BaseModel):
    problem_ids: list[int] = Field(min_length=1, max_length=100)
    state: str

    @field_validator("state")
    @classmethod
    def valid_state(cls, value: str) -> str:
        allowed = {"backlog", "scheduled", "blocked", "archived"}
        if value not in allowed:
            raise ValueError("invalid queue state")
        return value


class HealthResponse(BaseModel):
    status: str
    database: str
    today: date
