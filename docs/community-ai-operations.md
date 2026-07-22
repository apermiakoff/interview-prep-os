# Community AI operations

## Enable locally

1. Copy `.env.example` to `.env`. Keep AI disabled while validating the core app.
2. For Ollama, select an installed model and use its internal Compose/network URL. Ollama itself is
   intentionally not bundled: operators control its model, hardware, and lifecycle.
3. For a hosted provider, create a mode-0600 file outside the repository, set
   `INTERVIEW_PREP_AI_API_KEY_FILE` to it, and select `openai`, `anthropic`, or
   `openai_compatible`. Never put a key in Compose YAML or SQLite.
4. Set `INTERVIEW_PREP_AI_ENABLED=true`, then run
   `docker compose --profile ai up -d`. Without the `ai` profile only the app starts, and every core
   workflow remains usable. The app remains bound to `127.0.0.1:8765` by default.

The worker is profile-gated and exits successfully when disabled, so disabled configurations cannot
restart-loop. It needs only the `ai-data` volume and secret file. Do not mount `./data`, source
content, or legacy volumes into it. The tracked `secrets/ai_api_key.empty` is deliberately zero
bytes; hosted providers fail configuration validation until an actual external secret is selected.

## Configuration

- `INTERVIEW_PREP_AI_DB`: separate AI SQLite path.
- `INTERVIEW_PREP_AI_PROVIDER`, `INTERVIEW_PREP_AI_MODEL`, `INTERVIEW_PREP_AI_BASE_URL`.
- `INTERVIEW_PREP_AI_API_KEY` or preferred `INTERVIEW_PREP_AI_API_KEY_FILE`.
- `INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL`: opt-in for non-Ollama private provider targets.
- `INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS`: mandatory comma-separated exact-host allowlist for
  `openai_compatible`. `openai` and `anthropic` accept only their canonical HTTPS API hosts;
  redirects are disabled. Every address returned by DNS is checked at configuration and request time;
  the request-time resolution is used as the literal connection host, while the original Host header
  and HTTPS SNI/certificate hostname are preserved. No target-host DNS lookup occurs between that
  validation and connection. Resolution failure and mixed public/private answers fail closed. IPv4
  and bracketed IPv6 literals are supported.
- `INTERVIEW_PREP_AI_MAX_INPUT_TOKENS`, `INTERVIEW_PREP_AI_MAX_OUTPUT_TOKENS`. The local hard input
  admission bound is the full UTF-8 byte length of the complete rendered system and user prompts plus
  256 fixed protocol-overhead tokens. This intentionally pessimistic tokenizer-independent bound must
  fit before enqueue.
- `INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET`: hard **local admission** ceiling independent of prices.
  Acceptance atomically reserves the hard input bound plus requested maximum output. Missing provider
  usage is replaced with conservative local input/output bounds, never zero. Reported usage is never
  clamped to the reservation: an external provider can exceed or misreport requested output, and the
  full overage is retained so later admissions see it. This is not a provider billing guarantee;
  provider-side limits, credentials, and billing controls remain independently required.
- `INTERVIEW_PREP_AI_MAX_RETRIES`, `INTERVIEW_PREP_AI_LEASE_SECONDS`.

## Backup and recovery

Back up core and AI SQLite independently using SQLite's backup API or while services are stopped.
Keep each database's WAL/SHM files with it if copying live files. AI data may be discarded without
losing canonical attempt evidence. Never restore AI SQLite over the core path.

A worker crash leaves a renewable lease. Claims carry a monotonically increasing fencing generation;
lease renewal runs during provider waits/streams, and every event, retry, failure, cancellation, usage,
message, artifact, and completion write requires the current owner and generation. Stale results are
discarded, and per-run uniqueness indexes prevent duplicate assistant messages, artifacts, or usage.
Provider errors expose normalized codes, not response bodies or credentials. Queued cancellation is an immediate atomic terminal transition that releases its reservation; running
cancellation is cooperative and durable. Repeated cancellation is idempotent, and disconnecting an
SSE client never requests cancellation.

## Residual network risk

The self-hosted v1 design combines canonical/explicit exact-host policy with request-time DNS
validation and literal-IP connection pinning. HTTP redirects are off and credentials are not
constructed until resolution passes. The original hostname remains the HTTP Host and TLS SNI name, so
certificate verification keeps its intended identity. Operators should still restrict egress at the
container/host firewall and keep `ALLOW_PRIVATE_BASE_URL=false` for hosted providers. Ollama
intentionally permits private addresses.
