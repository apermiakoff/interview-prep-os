import { useEffect, useState } from "react";
import { api } from "../api";
import type { AIStatus, AIUsage } from "../types";
import { aiErrorMessage } from "../components/AIState";

const PROVIDERS = [
  ["Ollama", "Local by default; no API key. Base URL is typically http://ollama:11434."],
  ["OpenAI", "Canonical https://api.openai.com/v1 endpoint; server-side key required."],
  ["Anthropic", "Canonical https://api.anthropic.com/v1 endpoint; server-side key required."],
  ["OpenAI-compatible", "Explicit base URL and allowlisted hostname; server-side key required."],
];
const ENV = `INTERVIEW_PREP_AI_ENABLED=true
INTERVIEW_PREP_AI_PROVIDER=ollama
INTERVIEW_PREP_AI_MODEL=llama3.2
INTERVIEW_PREP_AI_BASE_URL=http://ollama:11434
INTERVIEW_PREP_AI_API_KEY_FILE=./secrets/ai_api_key.empty
INTERVIEW_PREP_AI_MONTHLY_TOKEN_BUDGET=1000000
INTERVIEW_PREP_AI_ALLOW_PRIVATE_BASE_URL=false
INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS=
INTERVIEW_PREP_AI_MAX_INPUT_TOKENS=12000
INTERVIEW_PREP_AI_MAX_OUTPUT_TOKENS=2048
INTERVIEW_PREP_AI_MAX_RETRIES=2
INTERVIEW_PREP_AI_LEASE_SECONDS=60`;
export function AISetupView() {
  const [status, setStatus] = useState<AIStatus | null>(null); const [usage, setUsage] = useState<AIUsage | null>(null); const [error, setError] = useState("");
  useEffect(() => { api.aiStatus().then(value => { setStatus(value); if (value.status === "ready") api.aiUsage().then(setUsage).catch(reason => setError(aiErrorMessage(reason))); }).catch(reason => setError(aiErrorMessage(reason))); }, []);
  let host = "not configured"; try { if (status?.base_url) host = new URL(status.base_url).host; } catch { host = "invalid"; }
  return <main className="view page-shell ai-setup" id="main-content"><button className="back-link" onClick={() => history.back()}>← Back</button><div className="section-heading compact"><span className="eyebrow">Settings · private infrastructure</span><h1>Community AI setup</h1><p>Configuration and credentials are read only by the server. This browser cannot read or write provider keys.</p></div>{error && <div className="ai-error">{error}</div>}
    {status?.status === "ready" ? <section className="setup-status"><header><span className="status-pill stable">ready</span><h2>{status.provider} · {status.model}</h2></header><dl><div><dt>Base host</dt><dd>{host}</dd></div><div><dt>Credential</dt><dd>{status.credential_configured ? "configured (value never exposed)" : "not required"}</dd></div><div><dt>Usage</dt><dd>{usage ? `${usage.tokens_used.toLocaleString()} used + ${usage.tokens_reserved.toLocaleString()} reserved` : "loading"}</dd></div><div><dt>Remaining</dt><dd>{usage ? `${usage.tokens_remaining.toLocaleString()} / ${usage.token_budget.toLocaleString()} tokens` : "loading"}</dd></div><div><dt>Output limit</dt><dd>{status.max_output_tokens?.toLocaleString()} tokens</dd></div></dl></section> : <section className="setup-guide"><div className="ai-empty"><strong>Community AI is disabled.</strong><p>Add these fields to the Docker <code>.env</code>, adjust the provider values, then start the opt-in profile.</p></div><pre aria-label="Docker environment fields"><code>{ENV}</code></pre><pre><code>docker compose --profile ai up -d</code></pre></section>}
    <section className="provider-grid" aria-label="AI providers">{PROVIDERS.map(([name, copy]) => <article key={name}><h2>{name}</h2><p>{copy}</p></article>)}</section><p className="policy-note">Prefer <code>INTERVIEW_PREP_AI_API_KEY_FILE</code> with a Docker secret. Never commit a key or place it in browser storage. For OpenAI-compatible hosts, also set <code>INTERVIEW_PREP_AI_ALLOWED_BASE_HOSTS</code>; private non-Ollama endpoints additionally require an explicit private-base opt-in.</p></main>;
}
