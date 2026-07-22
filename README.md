# Interview Prep OS — private community alpha

A local-first, single-learner interview practice system. It combines a generic starter catalog, deterministic evidence and review scheduling, a React interface, and optional bring-your-own-provider AI. There are no accounts, SaaS service, telemetry, or multi-user features.

The application code and generic community metadata are free software under **AGPL-3.0-or-later**. The optional `curricula/outtalent.json` pack is excluded from that grant, is not loaded by community bootstrap or copied into community images, and must not be published or redistributed without Outtalent's permission.

Share only a release/source archive produced by `git archive`; `.gitattributes` excludes the restricted curriculum and maintainer-only deployment files. A direct clone of the maintainer repository is not the community distribution artifact.

## Install with Docker

Requirements: Docker Engine/Desktop with Compose v2, and a currently supported browser.

```bash
python3 scripts/community_setup.py --non-interactive
docker compose --env-file .env.community -f compose.community.yaml up -d --build
```

Open <http://127.0.0.1:8765>. A new named volume receives the schema, skill graph, and 20-item metadata-only community starter catalog. It receives no attempts, assignments, reviews, mastery, evidence, or learner profile.

AI is opt-in and core practice works without it. Configure a provider first; the setup tool refuses an AI configuration without a provider model (and a key when required):

```bash
python3 scripts/community_setup.py --non-interactive --enable-ai \
  --provider ollama --model llama3.2
docker compose --env-file .env.community -f compose.community.yaml --profile ai up -d --build
```

The setup command stores credentials in a gitignored mode-`0600` file and never prints them or accepts them directly in command arguments. Use its hidden interactive prompt, `--api-key-file`, or `--api-key-stdin` for hosted providers. Ollama is not bundled.

## Documentation

- [Community installation and operations](docs/community-install.md)
- [Security policy and threat model](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Community release checklist](docs/community-release-checklist.md)
- [Architecture](docs/architecture.md)
- [License](LICENSE) and [third-party data notice](NOTICE.md)

`compose.yaml` remains the maintainer's private/local deployment definition and contains machine-specific legacy import mounts. Community users must use `compose.community.yaml`.

## Development and verification

```bash
uv sync --all-groups
npm ci
uv run ruff check app scripts tests
uv run pytest
npm run lint
npm test
npm run build
npx playwright test
```

## Privacy

All learner and AI artifacts stay in local Docker volumes unless you choose an external AI provider, in which case the requested context is sent to that provider under its terms. The application includes no analytics, advertising, crash reporting, or telemetry. API keys are excluded from portable backups.
