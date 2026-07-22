import { useEffect, useRef, useState } from "react";
import { api, waitForAIRun } from "../api";
import type { AIArtifact, AIStatus, DiagnosisArtifact } from "../types";
import { aiErrorMessage } from "./AIState";

export function DiagnosisPanel() {
  const [status, setStatus] = useState<AIStatus | null>(null); const [history, setHistory] = useState<AIArtifact[]>([]); const [selected, setSelected] = useState(0); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const pending = useRef<string | null>(null);
  const load = async () => { const configured = await api.aiStatus(); setStatus(configured); if (configured.status === "ready") setHistory(await api.aiDiagnosisHistory()); };
  useEffect(() => { load().catch(reason => setError(aiErrorMessage(reason))); }, []);
  const generate = async () => { const key = pending.current || crypto.randomUUID(); pending.current = key; setBusy(true); setError(""); try { const queued = await api.aiGenerate("learning", "learner", "diagnosis", "", key); const run = await waitForAIRun(queued.run.id); if (run.status !== "completed") throw new Error(run.error_message || `Diagnosis ${run.status}.`); pending.current = null; await load(); setSelected(0); } catch (reason) { setError(aiErrorMessage(reason)); } finally { setBusy(false); } };
  const artifact = history[selected]; const diagnosis = artifact?.content as DiagnosisArtifact | undefined;
  return <section className="diagnosis-panel" aria-label="Longitudinal AI diagnosis">
    <header><div><span className="eyebrow">Community AI · evidence-bounded</span><h2>Longitudinal diagnosis</h2></div>{status?.status === "ready" && <button className="button" disabled={busy} onClick={() => void generate()}>{busy ? "Generating…" : artifact ? "Generate new" : "Generate diagnosis"}</button>}</header>
    <p className="policy-note">This is an advisory reading of recorded evidence. Hypotheses are never confirmed facts and cannot alter mastery or scheduling.</p>
    {status?.status === "disabled" && <div className="ai-empty">AI diagnosis is disabled. <a href="#settings/ai">Open AI Setup →</a></div>}
    {error && <div className="ai-error" role="alert"><p>{error}</p>{pending.current && <button className="button" onClick={() => void generate()}>Retry</button>}</div>}
    {history.length > 1 && <label>History<select value={selected} onChange={event => setSelected(Number(event.target.value))}>{history.map((item, index) => <option key={item.id} value={index}>v{item.version} · {new Date(item.created_at).toLocaleDateString()}</option>)}</select></label>}
    {diagnosis && <div className="diagnosis-content"><p className="artifact-meta">AI generated · {artifact.provider}/{artifact.model} · {new Date(artifact.created_at).toLocaleString()}</p><section><h3>Recorded observations</h3>{diagnosis.observations.length ? <ul>{diagnosis.observations.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>Sparse evidence: no reliable observations were available.</p>}</section><section><h3>Hypotheses — not confirmed</h3>{diagnosis.hypotheses.length ? diagnosis.hypotheses.map((item, index) => <article className="hypothesis" key={index}><header><strong>{item.type.replaceAll("_", " ")}</strong><span>{item.status} · {Math.round(item.confidence * 100)}% confidence · unconfirmed</span></header><p>{item.statement}</p>{item.evidence.length ? <ul>{item.evidence.map(ref => <li key={ref.id}><code>{ref.id}</code>{ref.quote ? ` — ${ref.quote}` : ""}</li>)}</ul> : <p className="quiet-note">Sparse evidence — confidence is capped.</p>}</article>) : <p>Sparse evidence: no hypotheses are warranted yet.</p>}</section><section><h3>Experiments for you to perform</h3>{diagnosis.interventions.map((item, index) => <article className="intervention" key={index}><strong>User action required</strong><p>{item.action}</p><small>{item.rationale}</small></article>)}</section></div>}
  </section>;
}
