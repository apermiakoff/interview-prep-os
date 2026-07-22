# Community installation and operations

## Prerequisites and first boot

Install Docker Engine/Desktop and Compose v2. Use the approved community source archive, not a direct clone of the maintainer repository. From the extracted archive root:

```bash
python3 scripts/community_setup.py --non-interactive
docker compose --env-file .env.community -f compose.community.yaml up -d --build
docker compose --env-file .env.community -f compose.community.yaml ps
curl --fail http://127.0.0.1:8765/api/health
```

The app binds only `127.0.0.1`. Named volumes `core-data` and `ai-data` separately hold the core and AI SQLite databases. Community Compose has no source bind mounts, legacy imports, personal host paths, or tailnet hostname. Enter learner settings on the Profile page.

## Optional AI

Core practice does not require AI. Re-run setup with exactly one provider, then include the profile:

```bash
python3 scripts/community_setup.py --non-interactive --enable-ai --provider openai --model gpt-4.1-mini --api-key-file /secure/path/to/key
# or: --provider anthropic --model YOUR_MODEL --api-key-file /secure/path/to/key
# or: --provider openai_compatible --model YOUR_MODEL --base-url https://allowed.example/v1 --api-key-file /secure/path/to/key
# or: --provider ollama --model llama3.2
docker compose --env-file .env.community -f compose.community.yaml --profile ai up -d --build
```

Canonical OpenAI and Anthropic URLs are enforced. OpenAI-compatible URLs require an exact allowed host. Credentials, query strings, and fragments are forbidden in provider URLs. The key is server-side in `.community-secrets/ai_api_key` (mode `0600`), never sent to the browser. Never put a key directly on the command line: command arguments can be exposed in shell history and process listings. Use an interactive setup, `--api-key-file`, or `--api-key-stdin`. Re-running setup without new key input preserves an existing key, including when disabling AI.

Ollama is **not bundled**. It must run on the host and listen where Docker can reach it. The generated URL is `http://host.docker.internal:11434`; the Compose `extra_hosts: host-gateway` mapping supplies this name on Linux. Configure Ollama's listener/firewall narrowly and do not expose it publicly.

Do not add `--profile ai` until setup succeeds. An enabled worker without a valid model/credential fails closed; it cannot call a provider while AI is disabled.

## Private remote access

Keep the localhost binding. For SSH use `ssh -N -L 8765:127.0.0.1:8765 user@host`. Tailscale Serve can proxy the same loopback port. Add the exact tailnet hostname to `INTERVIEW_PREP_ALLOWED_HOSTS` and full origin (for example `https://host.tailnet.ts.net`) to `INTERVIEW_PREP_ALLOWED_ORIGINS`. Do not change the Compose port binding to `0.0.0.0`.

## Updates

Back up first, fetch only from the authorized private repository, review release notes, then:

```bash
docker compose --env-file .env.community -f compose.community.yaml up -d --build
docker compose --env-file .env.community -f compose.community.yaml ps
```

Migrations are forward-only. Do not run older images against upgraded volumes.

## Portable backup and restore

Both databases are snapshotted separately, checked with SQLite `quick_check`, checksummed, and packed with a key-free manifest:

```bash
CID=$(docker compose --env-file .env.community -f compose.community.yaml ps -q app)
docker compose --env-file .env.community -f compose.community.yaml exec -T app \
  .venv/bin/python scripts/community_data.py backup --core /data/interview-prep.db \
  --ai /ai-data/interview-prep-ai.db --output /data/community-backup.zip
docker cp "$CID:/data/community-backup.zip" ./community-backup.zip
docker compose --env-file .env.community -f compose.community.yaml exec -T app \
  rm /data/community-backup.zip
```

For restore, stop the stack and run a one-off container with an explicit archive bind and overwrite only after verifying the target project:

```bash
docker compose --env-file .env.community -f compose.community.yaml stop
docker compose --env-file .env.community -f compose.community.yaml run --rm --no-deps \
  -v "$PWD/community-backup.zip:/tmp/community-backup.zip:ro" app \
  .venv/bin/python scripts/community_data.py restore --input /tmp/community-backup.zip \
  --core /data/interview-prep.db --ai /ai-data/interview-prep-ai.db --overwrite
docker compose --env-file .env.community -f compose.community.yaml up -d
```

Restore refuses existing destinations without `--overwrite`, validates the exact archive members, checksums, migration tables, schema versions, and both SQLite databases. Keep backups private: they exclude API keys but contain learner evidence and AI conversations.

## Troubleshooting

- `app` unhealthy: inspect `docker compose ... logs app`; verify volume permissions and port availability.
- `community AI is disabled`: configure AI and start with `--profile ai`.
- Ollama connection refused: verify host Ollama listening and Docker's `host.docker.internal` mapping.
- `invalid AI configuration`: correct provider URL/model/key; never place a key in `.env.community`.
- `Invalid host header` or write `403`: add the exact private host/origin values, then recreate containers.
- Reset only if you accept data loss: back up, then `docker compose ... down -v`.

The optional Outtalent curriculum is not part of the community source archive or image. Do not redistribute the maintainer-only `curricula/outtalent.json` without permission.
