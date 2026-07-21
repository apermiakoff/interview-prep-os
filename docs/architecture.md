# Interview Prep OS architecture

## Goal

A private single-user training application that turns daily interview preparation into a durable retrieval loop: attempt → evidence → explanation → delayed reconstruction.

## Runtime boundary

One Docker service serves both the built React application and `/api/*`. It binds to host loopback only (`127.0.0.1:8765`). Tailscale Serve provides tailnet-authenticated HTTPS; SSH forwarding remains a fallback. There is no public listener, public signup, or LeetCode session credential.

## Modules

- `app/db.py`: SQLite connection, atomic forward-only migrations, transaction helper.
- `app/repository.py`: persistence boundary and read models.
- `app/scheduler.py`: pure adaptive-memory calculations.
- `app/learning.py`: deterministic skill evidence, trap detection, retention, and daily decisions.
- `app/curriculum.py`: normalized curriculum and skill-graph import.
- `app/services.py`: legacy-compatible attempt/hint/notes workflows.
- `app/attempts.py`: shared attempt-evidence service (normalization, memory, reviews, structured errors) used by both the compatibility endpoints and practice sessions.
- `app/sessions.py`: practice sessions — scheduled and ad hoc execution contexts, sequential hint reveals, abandonment.
- `app/content.py`: deterministic instructional content resolver (curated precedence, generated skill scaffold, provenance labels).
- `app/api.py`: validated HTTP boundary.
- `app/lessons.py`: versioned curated pattern content, hint ladder, and semantic visualization traces.
- `app/roadmap.py`: study-plan classification and idempotent roadmap catalog import.
- `frontend/`: training cockpit.

## Persistence

SQLite uses WAL mode, foreign keys, busy timeout, and schema migrations in `schema_migrations`. Tables:

- `patterns`
- `problems`
- `queue_items`
- `assignments`
- `attempt_events` (append-only)
- `reviews`
- `memory_states`
- `profile_snapshots`
- `notes`
- `hint_events` (append-only)
- `curricula` and `curriculum_items`
- `skills`, `skill_edges`, and `problem_skills`
- `error_types` and `attempt_errors`
- `learner_skill_states`
- `learning_decisions`
- `practice_sessions` and `session_hint_events` (execution contexts; `attempt_events.session_id` links evidence to the session that produced it)

Attempt events are immutable. Derived memory and review rows are updated in the same `BEGIN IMMEDIATE` transaction. The legacy importer uses deterministic source IDs and `INSERT OR IGNORE`. Queue state is separate from canonical problem identity, so backlog, blocked, scheduled, and archived lifecycle changes do not rewrite evidence.

## Catalog scalability

`GET /api/problems` applies search, scope, status, pattern, difficulty, sort, and pagination on the server. The UI requests 25 rows at a time. Attempts, reviews, memory, and lesson traces are loaded only from `GET /api/problems/{id}` when a problem workspace opens. A 250-item isolated fixture verifies pagination without inserting synthetic records into the personal database.

## Adaptive scheduling

The scheduler treats Accepted, independent retrieval, hint level, delay, duration, and outcome as separate evidence. Assisted Accepted remains Red/Yellow evidence. Low sample sizes are labeled rather than converted into fake mastery percentages.

The learner model derives six independent dimensions: recognition, derivation,
implementation, testing, explanation, and retention. Recommendations persist the
policy version, candidate inputs, constraints, selected problem, and factual rationale.
Thresholds and score weights are product policy rather than scientific constants.

## Practice sessions and instructional content

Three entities stay distinct: a *scheduled assignment* is the formal daily
commitment; a *practice session* is one execution context (origin `scheduled`
or `ad_hoc`); an *attempt event* is the immutable evidence a session produces.
Ad hoc sessions may create attempt/memory/review evidence but never modify an
assignment row, never invoke the legacy coach subprocess, and never mark the
daily assignment complete. The catalog status `active` remains scheduled-only.

Sessions are paper-first: the Solve room frames the attempt (goal, timebox,
Clarify/Derive/Verify prompts) and the actual reading/implementation happens on
LeetCode. Hints unlock strictly H1→H4; the first reveal requires an explicit
confirmation that the attempt records as assisted, each reveal returns exactly
one body, and unrevealed bodies never appear in bootstrap, problem detail, or
session GET payloads.

Instructional content is resolved deterministically per problem
(`app/content.py`): curated material (the low-link lesson and hint ladder,
authored assignment hints) always wins; every other mapped problem receives a
provenance-labeled generated scaffold (`deterministic-skill-scaffold/1.0`)
assembled at request time from stored metadata only — never presented as
curated, never claiming a worked solution. Content GETs are pure reads and
create no learner evidence.

## Curriculum model

Canonical problems are independent of curriculum placements. Outtalent is the formal
priority track; the deep study plan is supplemental. Repeated rows and cross-track
overlap share the same problem and evidence. Screenshot-derived rows retain source,
confidence, raw title, status, and placement metadata; unreadable rows stay explicit
placeholders rather than invented problems.

## Visualization

Visualizations store semantic events, not videos or arbitrary frame blobs. A trace contains operations such as `visit_node`, `tree_edge`, `back_edge`, `merge_low`, and `bridge_check`. React renderers animate these events deterministically and can attach explanations/prediction pauses. Lessons are resolved by pattern and attached to problem detail; there is no global visualizer destination that implies every task is Low-link DFS.

## Security

- Host binding is loopback-only.
- No LeetCode cookies or credentials.
- External problem/profile links are allowlisted HTTPS links.
- Notes are plain text and rendered by React, never injected as HTML.
- API mutation payloads are Pydantic-validated.
- SQLite and backups live in `./data`, excluded from Git.
- Container runs as a non-root user.

## Backup

Stop writes briefly or use SQLite's online backup API:

```bash
docker compose exec app python -m app.backup /data/interview-prep.db /data/backups
```
