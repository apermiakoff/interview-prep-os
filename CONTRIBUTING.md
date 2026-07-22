# Contributing

Application code and generic community metadata are licensed under AGPL-3.0-or-later. The optional Outtalent curriculum is excluded from that grant; do not publish or redistribute it without explicit permission.

Before proposing a change:

1. Create a focused branch/worktree; never use personal databases or credentials in tests.
2. Keep the product local-first, single-learner, and useful without AI. Do not add SaaS, accounts, or multitenancy without a separately approved design.
3. Use generic fixtures and unique temporary directories/volumes. Never call paid providers in tests.
4. Add migrations forward-only, preserve evidence, and test clean install plus upgrade behavior.
5. Run `uv run ruff check app scripts tests`, `uv run pytest`, `npm run lint`, `npm test`, `npm run build`, and relevant Playwright tests.
6. Render and audit `compose.community.yaml`; scan tracked files/history for secrets and images for vulnerabilities before release.
7. Use conventional commits. Explain privacy/security effects and manual verification in the change description.

Community metadata may include canonical IDs, titles, slugs, difficulty labels, and editorial mappings; do not copy third-party problem statements or solutions without permission.
