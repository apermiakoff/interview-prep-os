# Community AI backend

Community AI is an optional, self-hosted subsystem. The deterministic learning engine and every
non-AI endpoint continue to work with `INTERVIEW_PREP_AI_ENABLED=false` (the default).

## Trust and process boundary

The web process reads the core SQLite database only to construct an explicit, bounded context
snapshot and writes AI state to a separate AI SQLite database. The worker receives immutable
request and snapshot rows from AI SQLite. Its import graph is restricted to `app.ai`; its Compose
service mounts only `ai-data` and the configured provider secret file. It cannot read core data,
repository content, legacy state, or application source-mounted data.

Core stores one provider-independent fact for session coaching: `practice_sessions.ai_assisted`.
Posting session chat marks this before its run is accepted. Attempt recording then forces
`independent=false`, even if a client submits true. Provider text and configuration never enter the
core database.

## Data model

`ai_schema_migrations` owns a separate forward migration history. AI DB records masked provider
profile metadata, allowlisted context snapshots, scoped conversations/messages, durable leased
runs and coalesced events, cache keys, token/cost usage, immutable versioned artifacts, and
hypotheses with snapshot evidence references. There are intentionally no cross-database foreign
keys.

Snapshots include problem identity, skills/prerequisites and provenance, and at most 20 canonical
attempt summaries. Session snapshots add goal/origin/timebox, assistance state, completed outcome,
and only already-revealed hint levels and bodies. Longitudinal learning snapshots independently cap
attempt, hint-event, session, and skill-state facts at 100 each; every fact has an immutable
`evidence_id`, and facts may span problems. They exclude `raw_json`, profiles, skill `facts_json`,
notes, secrets, unrelated attempts, and unrevealed hint bodies.

## Provider and safety contract

Adapters support OpenAI, Anthropic, OpenAI-compatible chat completions, and Ollama through async
`httpx`; redirects are disabled. Base URLs must be absolute HTTP(S), may not contain credentials,
and may target private addresses only for Ollama or when
`INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL=true`. API keys are read from environment or a `*_FILE`
secret and are never returned or persisted.

Structured artifacts are Pydantic-validated. Visualizations accept six versioned renderers and a
small operation allowlist; HTML, CSS, JavaScript, URLs, SVG, unknown fields/operations, oversized
envelopes, and dangling entity references fail validation. Diagnoses distinguish observations and
hypotheses, may only be candidate/likely/insufficient, must cite snapshot evidence, receive an
evidence-diversity confidence cap, and can only propose user-executed interventions.

The persisted prompt/schema/context/model provenance says the model may not take application
actions, make mastery or character/intelligence claims, reveal hidden hints/full active-attempt
solutions, or invent evidence references.

## API and execution

All endpoints are under `/api/ai`: masked status, problem/session conversations, idempotent message
submission, explicit lesson/visualization/diagnosis generation, run polling, cancellation, durable
SSE (`Last-Event-ID`, heartbeat), usage/budget, stable problem/session artifact history and latest
lookups, and explicit longitudinal `POST /learning/diagnosis` plus latest/history retrieval. Artifact
responses include immutable version and run/snapshot/prompt/provider/model provenance. GET endpoints
never call providers; existing `GET /api/problems/{id}/lesson` remains deterministic and pure.

Workers claim queued runs with expiring leases. Browser disconnect does not cancel work. Transient
provider failures retry to a configured bound. The provider contract normalizes asynchronous text
deltas; built-in OpenAI, OpenAI-compatible, Anthropic, and Ollama HTTP adapters explicitly use the
safe complete-only fallback today. Workers coalesce deltas by size/time into durable events before a
single final message/artifact transaction, so SSE reconnects replay progress without a transaction
per token. Artifact requests cache by default; chat does not. Cached artifacts bypass provider budget
checks, while accepted queued/running runs atomically reserve the full rendered-request UTF-8 byte
bound, fixed protocol overhead, and maximum output against the monthly local admission ceiling. Full
reported actual usage replaces the reservation at completion even when it exceeds the request cap;
that ceiling is intentionally not represented as an external provider billing guarantee.
