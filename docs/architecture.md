# Interview Prep OS architecture

## Goal

A private single-user training application that turns daily interview preparation into a durable retrieval loop: attempt → evidence → explanation → delayed reconstruction.

## Runtime boundary

One Docker service serves both the built React application and `/api/*`. It binds to host loopback only (`127.0.0.1:8765`) and is reached through an SSH tunnel. There is no public signup or LeetCode session credential.

## Modules

- `app/db.py`: SQLite connection, migrations, transaction helper.
- `app/repository.py`: persistence boundary and read models.
- `app/scheduler.py`: pure adaptive-memory calculations.
- `app/services.py`: attempt/hint/notes workflows.
- `app/api.py`: validated HTTP boundary.
- `app/lessons.py`: versioned pattern content and semantic visualization traces.
- `frontend/`: training cockpit.

## Persistence

SQLite uses WAL mode, foreign keys, busy timeout, and schema migrations in `schema_migrations`. Tables:

- `patterns`
- `problems`
- `assignments`
- `attempt_events` (append-only)
- `reviews`
- `memory_states`
- `profile_snapshots`
- `notes`
- `hint_events` (append-only)

Attempt events are immutable. Derived memory and review rows are updated in the same `BEGIN IMMEDIATE` transaction. The legacy importer uses deterministic source IDs and `INSERT OR IGNORE`.

## Adaptive scheduling

The scheduler treats Accepted, independent retrieval, hint level, delay, duration, and outcome as separate evidence. Assisted Accepted remains Red/Yellow evidence. Low sample sizes are labeled rather than converted into fake mastery percentages.

## Visualization

Visualizations store semantic events, not videos or arbitrary frame blobs. A trace contains operations such as `visit_node`, `tree_edge`, `back_edge`, `merge_low`, and `bridge_check`. React renderers animate these events deterministically and can attach explanations/prediction pauses.

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
