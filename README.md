# Interview Prep OS

Private, evidence-based interview training system for daily retrieval practice, adaptive review, and deterministic algorithm visualizations.

## Stack

- FastAPI + SQLite backend
- React + TypeScript + Vite frontend
- Semantic-event SVG visualizer
- Single Docker service bound to localhost

## Working surfaces

- **Today:** one assignment, review queue, selection rationale, early diagnosis
- **Solve Room:** wall-clock timer, autosaved notes, progressive hints, normalized outcomes
- **Evidence:** immutable attempts, blockers, honest confidence, forgetting curve
- **Patterns:** retrieval-first pattern packs rather than a problem catalog
- **Visual Lab:** reusable semantic-event player and low-link DFS lesson
- **Profile:** public LeetCode context kept separate from private learning evidence

## Local development

```bash
uv sync --all-groups
npm install
npm run build
uv run python -m uvicorn app.main:app --reload --port 8765
```

In another terminal:

```bash
npm run dev
```

## Import the existing coach data

```bash
uv run python scripts/import_legacy.py \
  --state ~/.hermes/leetcode-coach/state.json \
  --events ~/.hermes/leetcode-coach/events.jsonl \
  --profile ~/.hermes/leetcode-coach/profile.json
```

The import is idempotent.

## Verification

```bash
uv run ruff check app scripts tests
uv run python -m pytest -q
npm run lint
npm test
npm run build
npx playwright test
```

## Production

```bash
docker compose up -d --build
curl http://127.0.0.1:8765/api/health
```

Access through an SSH tunnel:

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<vm-host>
```

Then open <http://127.0.0.1:8765>.

The service intentionally binds only to `127.0.0.1`; it has no public signup and stores no LeetCode credentials.

See:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/operations.md`](docs/operations.md)
- [`DESIGN.md`](DESIGN.md)
