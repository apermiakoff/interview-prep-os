# Interview Prep OS

Private, evidence-based interview training system for daily retrieval practice, adaptive review, and deterministic algorithm visualizations.

## Stack

- FastAPI + SQLite backend
- React + TypeScript + Vite frontend
- Semantic-event SVG visualizer
- Single Docker service bound to localhost

## Working surfaces

- **Today:** one evidence-ranked intervention, its rationale, current risk, and next gate
- **Brain:** ranked error patterns, cited evidence, interventions, and memory risk
- **Roadmap:** Outtalent-first curriculum tracks plus a six-dimension competency heatmap
- **Library:** filtered, sortable, paginated queue, reviews, and canonical problem catalog
- **Solve Room:** wall-clock timer, autosaved notes, progressive hints, normalized outcomes
- **Problem workspaces:** skill mappings, prerequisites, attempts, reviews, related problems, and optional authored lessons
- **Problem lessons:** semantic-event visualizers attached only to matching workspaces
- **Profile:** public LeetCode context kept separate from private learning evidence

The learning engine is deterministic and policy-versioned. It models recognition,
derivation, implementation, testing, explanation, and delayed retention separately;
assisted success never becomes independent evidence.

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
  --profile ~/.hermes/leetcode-coach/profile.json \
  --plan ~/aleksandr-interview-study-plan.md
```

The import is idempotent.

Import the normalized Outtalent curriculum and curated skill graph with:

```bash
uv run python scripts/import_outtalent.py
```

Curriculum placements are separate from canonical problems. The same problem may
appear repeatedly or in multiple tracks without duplicating its attempt evidence.

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

Preferred private access through Tailscale Serve:

```text
https://ubuntu-16gb-nbg1-1-hermes.tail1fd6b9.ts.net/
```

SSH forwarding remains available as a fallback:

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<vm-host>
```

Then open <http://127.0.0.1:8765>.

The service intentionally binds only to `127.0.0.1`; it has no public signup and stores no LeetCode credentials.

See:

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/operations.md`](docs/operations.md)
- [`DESIGN.md`](DESIGN.md)
