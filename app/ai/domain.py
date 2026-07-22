from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    content: str = Field(min_length=1, max_length=12000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ConversationCreate(StrictModel):
    title: str = Field(default="", max_length=120)


class GenerationRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    instructions: str = Field(default="", max_length=2000)


class LessonSection(StrictModel):
    heading: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)


class Complexity(StrictModel):
    time: str = Field(max_length=300)
    space: str = Field(max_length=300)


class LessonArtifact(StrictModel):
    schema_version: Literal["lesson@1"]
    objectives: list[Annotated[str, Field(max_length=300)]] = Field(min_length=1, max_length=12)
    recognition_signals: list[Annotated[str, Field(max_length=300)]] = Field(max_length=20)
    sections: list[LessonSection] = Field(min_length=1, max_length=20)
    complexity: Complexity
    failures: list[Annotated[str, Field(max_length=500)]] = Field(max_length=20)
    provenance_notes: list[Annotated[str, Field(max_length=500)]] = Field(max_length=12)


class VisualEntity(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    label: str = Field(max_length=160)
    kind: Literal["node", "edge", "cell", "item", "frame", "pointer"]
    data: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class VisualEvent(StrictModel):
    op: Literal["show", "hide", "visit", "compare", "update", "push", "pop", "move", "select"]
    targets: list[str] = Field(min_length=1, max_length=20)
    value: str | int | float | bool | None = None
    note: str = Field(default="", max_length=300)


Renderer = Literal[
    "graph-trace@1",
    "array-window@1",
    "tree-traversal@1",
    "grid-search@1",
    "dp-table@1",
    "call-stack@1",
]


class VisualizationArtifact(StrictModel):
    schema_version: Literal["visualization@1"]
    renderer: Renderer
    title: str = Field(max_length=160)
    entities: list[VisualEntity] = Field(max_length=500)
    events: list[VisualEvent] = Field(max_length=1000)

    @model_validator(mode="after")
    def references_exist(self):
        ids = {item.id for item in self.entities}
        if any(target not in ids for event in self.events for target in event.targets):
            raise ValueError("visualization event references an unknown entity")
        return self


class EvidenceRef(StrictModel):
    id: str = Field(max_length=120)
    quote: str = Field(default="", max_length=500)


class Hypothesis(StrictModel):
    type: Literal["stuck_point", "brain_trap", "learning_bottleneck"]
    status: Literal["candidate", "likely", "insufficient"]
    statement: str = Field(max_length=1000)
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceRef] = Field(max_length=30)


class Intervention(StrictModel):
    action: str = Field(min_length=1, max_length=500)
    rationale: str = Field(max_length=500)
    requires_user_action: Literal[True]


class DiagnosisArtifact(StrictModel):
    schema_version: Literal["diagnosis@1"]
    observations: list[Annotated[str, Field(max_length=700)]] = Field(max_length=30)
    hypotheses: list[Hypothesis] = Field(max_length=20)
    interventions: list[Intervention] = Field(max_length=20)

    def validated_for(self, allowed_evidence: set[str]) -> DiagnosisArtifact:
        for hypothesis in self.hypotheses:
            refs = {entry.id for entry in hypothesis.evidence}
            if not refs <= allowed_evidence:
                raise ValueError("diagnosis cites evidence absent from its context snapshot")
            kinds = {value.split(":", 1)[0] for value in refs}
            if not refs:
                cap = 0.35
            elif len(refs) == 1:
                cap = 0.65
            elif len(refs) == 2 and len(kinds) == 1:
                cap = 0.75
            else:
                cap = 0.85
            hypothesis.confidence = min(hypothesis.confidence, cap)
            if hypothesis.status == "likely" and hypothesis.confidence < 0.6:
                hypothesis.status = "candidate"
        return self


ARTIFACT_MODELS = {
    "lesson": LessonArtifact,
    "visualization": VisualizationArtifact,
    "diagnosis": DiagnosisArtifact,
}
