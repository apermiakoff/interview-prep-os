# Security policy

## Private-alpha scope and threat model

Interview Prep OS is a single-learner, local application. It has no authentication, authorization, accounts, tenant isolation, public-ingress hardening, or secret-management service. The supported boundary is one trusted operator and browser, with Docker publishing only to `127.0.0.1`. It must not be exposed directly to the public internet or an untrusted LAN.

Primary risks are unauthorized network access, browser CSRF, malicious provider URLs, leaked provider credentials, and disclosure of backups containing learner evidence or AI conversations. Docker Community Compose drops Linux capabilities, enables `no-new-privileges`, uses a read-only root filesystem, and separates core and AI volumes; the worker cannot mount core data.

## Browser and API controls

State-changing requests carrying `Origin` or `Referer` must match the request origin or an exact `INTERVIEW_PREP_ALLOWED_ORIGINS` entry. This supports same-origin localhost, SSH forwarding, and explicitly configured private Tailscale origins while rejecting hostile browser origins for core and AI writes. Requests without either header are accepted for local CLI/health/automation under the localhost/private-access assumption. Treat any reverse proxy that strips these headers as trusted infrastructure and never expose it publicly.

`TrustedHostMiddleware`, restrictive response headers, CSP, frame denial, and no-store API responses provide defense in depth. CORS is not authentication. If you need shared or public use, add real authentication, TLS termination, rate limiting, audit logging, and a reviewed proxy policy first.

Provider credentials are read from a server-side mode-`0600` file and masked from status responses. AI base URLs reject embedded credentials, query strings, and fragments; canonical cloud hosts and explicit compatible-host allowlisting reduce SSRF risk. Portable backups exclude keys but remain sensitive.

## Reporting

Report vulnerabilities privately to the repository owner or private-alpha coordinator. Do not open a public issue containing exploit details, API keys, learner data, or provider transcripts. Include version/commit, reproduction, impact, and a suggested mitigation. No formal response SLA exists during private alpha.

## Privacy

There is no telemetry, analytics, advertising, or crash reporting. External AI is opt-in; prompts necessarily send selected learner context to the configured provider under that provider's terms. Ollama can keep inference local when correctly hosted.
