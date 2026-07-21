# Operations

## Runtime boundary

The service is intentionally published only on the VM loopback interface:

```text
127.0.0.1:8765 → container:8000
```

It has no public listener and no public signup/authentication surface. Tailscale identity is the preferred access boundary; SSH is the fallback.

## Access through Tailscale

Tailscale Serve proxies tailnet-authenticated HTTPS to the loopback service:

```bash
tailscale serve --bg --yes http://127.0.0.1:8765
tailscale serve status
```

Open from a device signed into the same tailnet:

```text
https://ubuntu-16gb-nbg1-1-hermes.tail1fd6b9.ts.net/
```

The raw VM IP and port remain closed.

## Access through SSH

From your own computer:

```bash
ssh -N -L 8765:127.0.0.1:8765 hermes@YOUR_VM_HOST
```

Keep that terminal open, then visit:

```text
http://127.0.0.1:8765
```

If local port 8765 is occupied, use another local port:

```bash
ssh -N -L 9876:127.0.0.1:8765 hermes@YOUR_VM_HOST
```

Then open `http://127.0.0.1:9876`.

## Deploy/update

Use the verified deploy command. It refuses to build or recreate the service until
SQLite `quick_check` passes for both the live database and a new pre-migration
backup. Startup migrations are forward-only.

```bash
cd /home/hermes/interview-prep-os
git pull --ff-only
.venv/bin/python scripts/deploy.py
```

The command prints `VERIFIED_PRE_MIGRATION_BACKUP=...`, builds the image,
recreates the service, and requires a healthy response from
`http://127.0.0.1:8765/api/health`. Do not replace this sequence with a bare
`docker compose up`: that would remove the backup-before-migration gate.

## Status and logs

```bash
cd /home/hermes/interview-prep-os
docker compose ps
docker compose logs --tail=100 app
```

## Backup and restore

Daily backups are written to `data/backups/` and retained for 30 days. Run manually with:

```bash
cd /home/hermes/interview-prep-os
.venv/bin/python scripts/backup_database.py
```

To restore:

1. Stop the app.
2. Copy the desired backup to `data/interview-prep.db`.
3. Start the app and verify `/api/health` and `/api/bootstrap`.

If a new image has applied migrations 5 or later, **never start an older image
against that migrated database**. Stop the service, restore the verified
pre-migration backup printed by `scripts/deploy.py`, then start the older image.

SQLite WAL mode and the SQLite backup API are used so backups remain consistent while the service is running. Every manual and deploy-time backup runs `PRAGMA quick_check` against the source and copied database before it is accepted.

## Legacy coach bridge

The container receives narrow mounts for the existing coach state and action scripts. Web hint/outcome actions go through the same deterministic `action.py` transitions as Telegram, then the append-only event log is imported back into SQLite. Host-side Telegram actions also re-import the tracker into this database.

This keeps:

- Green/Yellow/Red semantics consistent;
- Accepted separate from independent;
- skip penalty-free;
- Telegram and web views synchronized;
- the existing event log as the migration/audit bridge.

## Security checks

```bash
ss -ltnp | grep 8765
curl -I http://127.0.0.1:8765/api/health
```

Expected: only `127.0.0.1:8765` is listening. Responses include CSP, frame denial, no-sniff, and API no-store headers.
